"""Claim and process notification outbox rows (SKIP LOCKED)."""

from __future__ import annotations

import datetime as dt
import logging
import random
import secrets
import uuid
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.notifications.context import build_context
from app.notifications.models import (
    EmailDelivery,
    EmailDeliveryAttempt,
    EmailTemplateRevision,
    NotificationEvent,
    NotificationOutbox,
    NotificationSettings,
    NotificationWorkflow,
    WorkflowRecipientRule,
)
from app.notifications.providers.base import EmailMessage, ProviderSendResult
from app.notifications.providers.resend import ResendEmailProvider
from app.notifications.recipients import as_json, resolve_recipients
from app.notifications.templates import render_email

logger = logging.getLogger(__name__)


def _backoff_seconds(attempt: int) -> int:
    """Bounded exponential backoff with jitter: ~30s, 2m, 8m, 30m, 2h."""
    base = min(7200, int(30 * (4 ** max(0, attempt - 1))))
    return base + random.randint(0, min(60, base // 5))  # noqa: S311


def recover_abandoned_locks(session: Session, settings: Settings, *, now: dt.datetime) -> int:
    cutoff = now - dt.timedelta(seconds=settings.email_outbox_lock_seconds)
    result = session.execute(
        update(NotificationOutbox)
        .where(
            NotificationOutbox.status == "processing",
            NotificationOutbox.locked_at.is_not(None),
            NotificationOutbox.locked_at < cutoff,
        )
        .values(
            status="pending",
            locked_at=None,
            locked_by=None,
            available_at=now,
            updated_at=now,
        )
    )
    return result.rowcount or 0


def claim_outbox(
    session: Session,
    *,
    worker_id: str,
    limit: int = 10,
    now: dt.datetime | None = None,
) -> list[NotificationOutbox]:
    """Claim pending rows with SKIP LOCKED. Caller must commit after processing."""
    now = now or dt.datetime.now(dt.UTC)
    settings = get_settings()
    recover_abandoned_locks(session, settings, now=now)
    rows = session.execute(
        text(
            """
            SELECT id FROM notifications.notification_outbox
            WHERE status = 'pending' AND available_at <= :now
            ORDER BY available_at
            FOR UPDATE SKIP LOCKED
            LIMIT :limit
            """
        ),
        {"now": now, "limit": limit},
    ).all()
    claimed: list[NotificationOutbox] = []
    for (row_id,) in rows:
        outbox = session.get(NotificationOutbox, row_id)
        if outbox is None:
            continue
        outbox.status = "processing"
        outbox.locked_at = now
        outbox.locked_by = worker_id
        outbox.updated_at = now
        claimed.append(outbox)
    session.flush()
    return claimed


def _settings_row(session: Session) -> NotificationSettings:
    row = session.get(NotificationSettings, 1)
    if row is None:
        row = NotificationSettings(id=1, emergency_pause=False, updated_by="system")
        session.add(row)
        session.flush()
    return row


def _effective_mode(settings: Settings, *, is_test: bool) -> str:
    if not settings.email_enabled or settings.email_delivery_mode == "disabled":
        return "disabled"
    if settings.email_delivery_mode == "live":
        if not settings.email_live_ready:
            # Never silently fall back from live.
            raise RuntimeError("live_not_configured")
        return "test" if is_test else "live"
    if settings.email_delivery_mode == "redirect":
        if not settings.email_redirect_ready:
            raise RuntimeError("redirect_not_configured")
        return "test" if is_test else "redirect"
    return "disabled"


def process_outbox_row(
    session: Session,
    outbox: NotificationOutbox,
    *,
    settings: Settings | None = None,
    provider: ResendEmailProvider | None = None,
) -> EmailDelivery:
    settings = settings or get_settings()
    now = dt.datetime.now(dt.UTC)
    event = session.get(NotificationEvent, outbox.notification_event_id)
    revision = session.get(EmailTemplateRevision, outbox.template_revision_id)
    workflow = session.get(NotificationWorkflow, outbox.workflow_id)
    if event is None or revision is None or workflow is None:
        raise RuntimeError("outbox row references missing event, revision, or workflow")

    rules = list(
        session.scalars(
            select(WorkflowRecipientRule).where(
                WorkflowRecipientRule.workflow_id == workflow.id
            )
        )
    )
    to_r, cc_r, bcc_r = resolve_recipients(session, rules, payload=event.payload_json)
    pause = _settings_row(session).emergency_pause

    primary = to_r[0] if to_r else None
    entity_url = None
    if settings.app_public_url and event.payload_json.get("action.url"):
        entity_url = str(event.payload_json["action.url"])
    elif settings.app_public_url and event.entity_type == "safety.psm_action":
        entity_url = f"{settings.app_public_url.rstrip('/')}/safety/psm/actions/{event.entity_id}"

    context = build_context(
        payload=event.payload_json,
        settings=settings,
        recipient_name=primary.name if primary else None,
        recipient_email=primary.email if primary else None,
        occurred_at=event.occurred_at,
        entity_reference=event.entity_reference,
        entity_url=entity_url,
    )
    try:
        subject, html, text_body = render_email(
            subject_template=revision.subject_template,
            html_template=revision.html_template,
            text_template=revision.text_template,
            context=context,
        )
    except KeyError as error:
        delivery = _record_delivery(
            session,
            outbox=outbox,
            event=event,
            workflow=workflow,
            revision=revision,
            mode="disabled",
            to_r=to_r,
            cc_r=cc_r,
            bcc_r=bcc_r,
            actual_to=[],
            actual_cc=[],
            actual_bcc=[],
            subject=f"[FAILED] {revision.subject_template}",
            html="",
            text=str(error),
            status="failed",
            now=now,
        )
        _fail_outbox(outbox, now, "render_error", f"Unresolved template variable: {error}")
        return delivery

    if pause or not to_r:
        status = "suppressed" if not to_r else "disabled"
        mode = "disabled"
        delivery = _record_delivery(
            session,
            outbox=outbox,
            event=event,
            workflow=workflow,
            revision=revision,
            mode=mode,
            to_r=to_r,
            cc_r=cc_r,
            bcc_r=bcc_r,
            actual_to=[],
            actual_cc=[],
            actual_bcc=[],
            subject=subject,
            html=html,
            text=text_body
            + (
                "\n\nDelivery was not attempted: "
                + ("emergency pause is on." if pause else "no recipients resolved.")
            ),
            status=status,
            now=now,
        )
        outbox.status = "completed"
        outbox.completed_at = now
        outbox.locked_at = None
        outbox.locked_by = None
        outbox.updated_at = now
        return delivery

    try:
        mode = _effective_mode(settings, is_test=False)
    except RuntimeError as error:
        delivery = _record_delivery(
            session,
            outbox=outbox,
            event=event,
            workflow=workflow,
            revision=revision,
            mode="disabled",
            to_r=to_r,
            cc_r=cc_r,
            bcc_r=bcc_r,
            actual_to=[],
            actual_cc=[],
            actual_bcc=[],
            subject=subject,
            html=html,
            text=text_body + f"\n\nDelivery blocked: {error}.",
            status="failed",
            now=now,
        )
        _fail_outbox(outbox, now, str(error), "Delivery mode is not configured for sending.")
        return delivery

    if mode == "disabled":
        delivery = _record_delivery(
            session,
            outbox=outbox,
            event=event,
            workflow=workflow,
            revision=revision,
            mode="disabled",
            to_r=to_r,
            cc_r=cc_r,
            bcc_r=bcc_r,
            actual_to=[],
            actual_cc=[],
            actual_bcc=[],
            subject=subject,
            html=html,
            text=text_body + "\n\nDelivery was disabled by configuration.",
            status="disabled",
            now=now,
        )
        outbox.status = "completed"
        outbox.completed_at = now
        outbox.locked_at = None
        outbox.locked_by = None
        outbox.updated_at = now
        return delivery

    actual_to = [r.email for r in to_r]
    actual_cc = [r.email for r in cc_r]
    actual_bcc = [r.email for r in bcc_r]
    send_subject = subject
    send_html = html
    send_text = text_body
    if mode == "redirect":
        intended = ", ".join(actual_to + actual_cc + actual_bcc)
        send_subject = f"[NONPROD REDIRECT] {subject}"
        banner = (
            f"<p><strong>Non-production redirect.</strong> "
            f"Intended recipients: {intended}</p>"
        )
        send_html = banner + html
        send_text = f"Non-production redirect. Intended recipients: {intended}\n\n{text_body}"
        actual_to = [settings.email_redirect_to]  # type: ignore[list-item]
        actual_cc = []
        actual_bcc = []

    delivery = _record_delivery(
        session,
        outbox=outbox,
        event=event,
        workflow=workflow,
        revision=revision,
        mode=mode,
        to_r=to_r,
        cc_r=cc_r,
        bcc_r=bcc_r,
        actual_to=[{"email": e, "name": None} for e in actual_to],
        actual_cc=[{"email": e, "name": None} for e in actual_cc],
        actual_bcc=[{"email": e, "name": None} for e in actual_bcc],
        subject=send_subject,
        html=send_html,
        text=send_text,
        status="attempting",
        now=now,
        from_address=settings.email_from_address,
        reply_to=settings.email_reply_to,
    )
    session.flush()

    provider = provider or ResendEmailProvider(settings)
    outbox.attempts += 1
    attempt_number = outbox.attempts
    started = dt.datetime.now(dt.UTC)
    result = provider.send(
        EmailMessage(
            from_email=settings.email_from_address or "",
            from_name=settings.email_from_name,
            to=tuple(actual_to),
            cc=tuple(actual_cc),
            bcc=tuple(actual_bcc),
            reply_to=settings.email_reply_to,
            subject=send_subject,
            html=send_html,
            text=send_text,
        )
    )
    _record_attempt(session, delivery, attempt_number, started, result)
    finished = dt.datetime.now(dt.UTC)
    delivery.attempted_at = started
    if result.accepted:
        delivery.status = "accepted"
        delivery.accepted_at = finished
        delivery.provider_code = provider.code
        delivery.provider_message_id = result.provider_message_id
        outbox.status = "completed"
        outbox.completed_at = finished
        outbox.last_error_code = None
        outbox.last_error_message = None
    elif result.retryable and outbox.attempts < outbox.max_attempts:
        delivery.status = "failed"
        delivery.failed_at = finished
        delivery.provider_code = provider.code
        outbox.status = "pending"
        outbox.available_at = finished + dt.timedelta(seconds=_backoff_seconds(outbox.attempts))
        outbox.last_error_code = result.provider_error_code
        outbox.last_error_message = result.error_message
    else:
        delivery.status = "failed"
        delivery.failed_at = finished
        delivery.provider_code = provider.code
        outbox.status = "failed"
        outbox.completed_at = finished
        outbox.last_error_code = result.provider_error_code
        outbox.last_error_message = result.error_message
    outbox.locked_at = None
    outbox.locked_by = None
    outbox.updated_at = finished
    return delivery


def _fail_outbox(outbox: NotificationOutbox, now: dt.datetime, code: str, message: str) -> None:
    outbox.status = "failed"
    outbox.completed_at = now
    outbox.last_error_code = code
    outbox.last_error_message = message
    outbox.locked_at = None
    outbox.locked_by = None
    outbox.updated_at = now


def _record_delivery(
    session: Session,
    *,
    outbox: NotificationOutbox,
    event: NotificationEvent,
    workflow: NotificationWorkflow,
    revision: EmailTemplateRevision,
    mode: str,
    to_r: list[Any],
    cc_r: list[Any],
    bcc_r: list[Any],
    actual_to: list[Any],
    actual_cc: list[Any],
    actual_bcc: list[Any],
    subject: str,
    html: str,
    text: str,
    status: str,
    now: dt.datetime,
    from_address: str | None = None,
    reply_to: str | None = None,
) -> EmailDelivery:
    delivery = EmailDelivery(
        id=uuid.uuid4(),
        outbox_id=outbox.id,
        notification_event_id=event.id,
        workflow_id=workflow.id,
        template_revision_id=revision.id,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        delivery_mode=mode,
        intended_to_json=as_json(to_r),
        intended_cc_json=as_json(cc_r),
        intended_bcc_json=as_json(bcc_r),
        actual_to_json=actual_to,
        actual_cc_json=actual_cc,
        actual_bcc_json=actual_bcc,
        from_address=from_address,
        reply_to=reply_to,
        rendered_subject=subject,
        rendered_html=html,
        rendered_text=text,
        status=status,
        queued_at=now,
        is_test=False,
    )
    session.add(delivery)
    return delivery


def _record_attempt(
    session: Session,
    delivery: EmailDelivery,
    attempt_number: int,
    started: dt.datetime,
    result: ProviderSendResult,
) -> None:
    session.add(
        EmailDeliveryAttempt(
            email_delivery_id=delivery.id,
            attempt_number=attempt_number,
            started_at=started,
            completed_at=dt.datetime.now(dt.UTC),
            status="accepted" if result.accepted else "failed",
            provider_http_status=result.http_status,
            provider_error_code=result.provider_error_code,
            sanitized_provider_response_json=result.sanitized_response,
            error_message=result.error_message,
            retryable=result.retryable,
        )
    )


def process_pending(session: Session, *, limit: int = 20) -> int:
    worker_id = f"worker-{secrets.token_hex(4)}"
    claimed = claim_outbox(session, worker_id=worker_id, limit=limit)
    settings = get_settings()
    for row in claimed:
        process_outbox_row(session, row, settings=settings)
    return len(claimed)
