"""Email notifications about PSM actions: an outbox in ``safety.psm_notifications``.

A business change queues its notification in the same transaction; delivery
happens afterwards and never blocks or undoes the change. A notification is
``sent`` only once the mail server accepted it, ``failed`` (with the reason,
logged) otherwise, and stays ``queued`` while outgoing email is not configured.
Owners are emailed at the address recorded on the action, so they need no
platform account.

Reminders and queued deliveries can be run by a host scheduler:

    python -m app.safety.psm.notifications remind   # queue due-soon/overdue reminders, deliver
    python -m app.safety.psm.notifications deliver  # send what is queued
"""

import argparse
import datetime as dt
import logging
import sys
from collections.abc import Callable, Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.models import User
from app.core import mail
from app.core.config import Settings, get_settings
from app.safety.psm.models import (
    PsmAction,
    PsmNotification,
    PsmNotificationSettings,
    PsmRecommendation,
)
from app.safety.psm.reference import ACTION_STATUSES, NOTIFICATION_EVENTS
from app.safety.site_calendar import site_today

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5

SETTING_OF_EVENT = {
    "action_assigned": "notify_on_assignment",
    "owner_changed": "notify_on_assignment",
    "due_date_changed": "notify_on_due_date_change",
    "status_changed": "notify_on_status_change",
    "closure_requested": "notify_on_status_change",
    "closure_approved": "notify_on_status_change",
    "closure_returned": "notify_on_status_change",
    "reopened": "notify_on_status_change",
    "comment_added": "notify_on_comment",
    "due_soon": "due_soon_reminders",
    "overdue": "overdue_reminders",
}


def settings_row(session: Session) -> PsmNotificationSettings | None:
    return session.get(PsmNotificationSettings, 1)


def recipient(session: Session, action: PsmAction) -> tuple[str | None, str | None]:
    """The owner's name and email: the address recorded on the action, else the
    linked user's account email."""
    email = action.owner_email
    if email is None and action.owner_user_id is not None:
        user = session.get(User, action.owner_user_id)
        email = user.email if user is not None and user.status == "active" else None
    return action.owner_name, email


def _date(value: dt.date | None) -> str:
    return value.isoformat() if value is not None else "Not scheduled"


def render(
    event: str,
    action: PsmAction,
    recommendation: PsmRecommendation,
    detail: str | None,
    base_url: str | None,
) -> tuple[str, str]:
    """Subject and plain-text body. Values are as recorded, never reworded."""
    label = NOTIFICATION_EVENTS[event]
    subject = f"[PSM] {action.action_number} – {label}"
    lines = [
        f"{label}: {action.action_number}",
        "",
        f"Recommendation: {recommendation.display_id}",
        f"Area / Equipment: {recommendation.area_equipment}",
        f"Action: {action.title}",
    ]
    if action.description:
        lines.append(f"Task: {action.description}")
    lines += [
        f"Owner: {action.owner_name or 'Unassigned'}",
        f"Due date: {_date(action.due_date)}",
        f"Status: {ACTION_STATUSES[action.status]}",
    ]
    if detail:
        lines += ["", detail]
    if base_url:
        lines += ["", f"Open the action: {base_url.rstrip('/')}/safety/psm/actions/{action.id}"]
    lines += [
        "",
        "Recommendation:",
        recommendation.recommendation_text,
        "",
        "This message was sent by the Operations Platform (Process Safety Management).",
    ]
    return subject, "\n".join(lines)


def enqueue(
    session: Session,
    *,
    action: PsmAction,
    recommendation: PsmRecommendation,
    event: str,
    detail: str | None = None,
    dedupe_key: str | None = None,
    base_url: str | None = None,
) -> int | None:
    """Queue a notification in the caller's transaction. None when the setting
    for the event is off (or a reminder with this key was already queued)."""
    row = settings_row(session)
    if row is None or not getattr(row, SETTING_OF_EVENT[event]):
        return None
    name, email = recipient(session, action)
    subject, body = render(event, action, recommendation, detail, base_url)
    values = {
        "action_id": action.id,
        "event_type": event,
        "recipient_name": name,
        "recipient_email": email,
        "subject": subject,
        "body": body,
        "status": "queued" if email else "skipped",
        "status_detail": None if email else "No email address is recorded for the owner.",
        "dedupe_key": dedupe_key,
    }
    statement = insert(PsmNotification).values(**values)
    if dedupe_key is not None:
        statement = statement.on_conflict_do_nothing(
            index_elements=["dedupe_key"], index_where=PsmNotification.dedupe_key.is_not(None)
        )
    return session.scalar(statement.returning(PsmNotification.id))


def deliver(
    sessions: Callable[[], Session],
    settings: Settings,
    ids: Sequence[int] | None = None,
    *,
    limit: int = 200,
    send: Callable[[Settings, mail.OutgoingMail], None] = mail.send,
) -> dict[str, int]:
    """Send queued notifications, one transaction each. Without outgoing email
    configured nothing is attempted and the notifications stay queued."""
    counts = {"sent": 0, "failed": 0, "queued": 0}
    if not settings.mail_enabled:
        return counts
    n = PsmNotification
    with sessions() as session:
        statement = select(n.id).where(n.status == "queued", n.attempts < MAX_ATTEMPTS)
        if ids is not None:
            statement = statement.where(n.id.in_(ids))
        pending = list(session.scalars(statement.order_by(n.id).limit(limit)))
    for notification_id in pending:
        with sessions() as session:
            row = session.scalar(
                select(n)
                .where(n.id == notification_id, n.status == "queued")
                .with_for_update(skip_locked=True)
            )
            if row is None or row.recipient_email is None:
                continue
            now = dt.datetime.now(dt.UTC)
            row.attempts += 1
            row.last_attempt_at = now
            try:
                send(
                    settings,
                    mail.OutgoingMail(
                        row.recipient_email, row.recipient_name, row.subject, row.body
                    ),
                )
            except (mail.MailDeliveryError, mail.MailNotConfiguredError) as error:
                row.status = "failed" if row.attempts >= MAX_ATTEMPTS else "queued"
                row.status_detail = str(error)
                if row.status == "failed":
                    counts["failed"] += 1
                else:
                    counts["queued"] += 1
                logger.warning(
                    "psm notification delivery failed",
                    extra={
                        "notification_id": row.id,
                        "event_type": row.event_type,
                        "attempt": row.attempts,
                        "reason": str(error),
                    },
                )
            else:
                row.status = "sent"
                row.status_detail = None
                row.sent_at = now
                counts["sent"] += 1
            session.commit()
    return counts


def remind(session: Session, today: dt.date, base_url: str | None = None) -> dict[str, int]:
    """Queue due-soon and overdue reminders for open actions, once per due date."""
    row = settings_row(session)
    counts = {"due_soon": 0, "overdue": 0}
    if row is None:
        return counts
    horizon = today + dt.timedelta(days=row.due_soon_days)
    found = session.execute(
        select(PsmAction, PsmRecommendation)
        .join(PsmRecommendation, PsmRecommendation.id == PsmAction.recommendation_id)
        .where(
            PsmAction.status != "closed",
            PsmAction.archived_at.is_(None),
            PsmAction.due_date.is_not(None),
            PsmAction.due_date <= horizon,
            PsmRecommendation.archived_at.is_(None),
            PsmRecommendation.disposition == "accepted",
        )
    ).all()
    for action, recommendation in found:
        assert action.due_date is not None  # noqa: S101 - filtered above
        event = "overdue" if action.due_date < today else "due_soon"
        queued = enqueue(
            session,
            action=action,
            recommendation=recommendation,
            event=event,
            detail=f"Due date: {action.due_date.isoformat()}",
            dedupe_key=f"{event}:{action.id}:{action.due_date.isoformat()}",
            base_url=base_url,
        )
        if queued is not None:
            counts[event] += 1
    session.commit()
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    from app.db.session import get_sessionmaker

    parser = argparse.ArgumentParser(prog="python -m app.safety.psm.notifications")
    parser.add_argument("command", choices=("remind", "deliver"))
    args = parser.parse_args(argv)
    settings = get_settings()
    sessions = get_sessionmaker()
    if args.command == "remind":
        with sessions() as session:
            counts = remind(session, site_today(dt.datetime.now(dt.UTC)), settings.app_public_url)
        print(f"Queued reminders: {counts['due_soon']} due soon, {counts['overdue']} overdue.")
    if not settings.mail_enabled:
        print("Outgoing email is not configured (SMTP_HOST, SMTP_FROM); notifications stay queued.")
        return 0
    result = deliver(sessions, settings)
    print(
        f"Delivered: {result['sent']} sent, {result['failed']} failed, "
        f"{result['queued']} left queued for retry."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
