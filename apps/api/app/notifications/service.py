"""Administration business logic for the shared Notifications domain."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit.recorder import AuditChange, record_changes
from app.core.config import Settings
from app.notifications import context_providers, templates
from app.notifications.context import build_context
from app.notifications.models import (
    EmailDelivery,
    EmailDeliveryAttempt,
    EmailTemplate,
    EmailTemplateRevision,
    NotificationEvent,
    NotificationEventType,
    NotificationOutbox,
    NotificationSettings,
    NotificationWorkflow,
    WorkflowRecipientRule,
)
from app.notifications.providers.base import EmailMessage
from app.notifications.providers.resend import ResendEmailProvider
from app.notifications.recipients import resolve_recipients
from app.notifications.registry import allowed_variables
from app.notifications.schemas import (
    DeliveryAttemptOut,
    DeliveryDetailOut,
    DeliveryFilters,
    DeliveryListItem,
    EventTypeOut,
    OverviewOut,
    PreviewOut,
    RecentDeliverySummary,
    RecipientRuleOut,
    RetryOut,
    SettingsOut,
    TemplateOut,
    TemplateRevisionOut,
    TestPreviewOut,
    TestSendOut,
    ValidateOut,
    WorkflowOut,
)

ENTITY_TEMPLATE = "notifications.email_template"
ENTITY_REVISION = "notifications.email_template_revision"
ENTITY_WORKFLOW = "notifications.workflow"
ENTITY_SETTINGS = "notifications.settings"


class NotificationsNotFoundError(LookupError):
    pass


class NotificationsRuleError(ValueError):
    def __init__(self, error: str, message: str) -> None:
        super().__init__(message)
        self.error = error
        self.message = message


@dataclass(frozen=True)
class Actor:
    actor_id: str
    user_id: uuid.UUID | None = None


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _audit(
    session: Session,
    *,
    actor: Actor,
    changes: list[AuditChange],
) -> None:
    record_changes(
        session,
        actor_id=actor.actor_id,
        change_set_id=uuid.uuid4(),
        occurred_at=_now(),
        changes=changes,
    )


def _settings_row(session: Session) -> NotificationSettings:
    row = session.get(NotificationSettings, 1)
    if row is None:
        row = NotificationSettings(id=1, emergency_pause=False, updated_by="system")
        session.add(row)
        session.flush()
    return row


def _revision_out(row: EmailTemplateRevision) -> TemplateRevisionOut:
    return TemplateRevisionOut(
        id=row.id,
        template_id=row.template_id,
        revision_number=row.revision_number,
        status=row.status,  # type: ignore[arg-type]
        subject_template=row.subject_template,
        html_template=row.html_template,
        text_template=row.text_template,
        variable_schema_json=row.variable_schema_json,
        created_at=row.created_at,
        created_by=row.created_by,
        published_at=row.published_at,
        published_by=row.published_by,
    )


def _template_out(session: Session, template: EmailTemplate) -> TemplateOut:
    revisions = session.scalars(
        select(EmailTemplateRevision)
        .where(EmailTemplateRevision.template_id == template.id)
        .order_by(EmailTemplateRevision.revision_number.desc())
    ).all()
    draft = next((r for r in revisions if r.status == "draft"), None)
    published = None
    if template.current_published_revision_id is not None:
        published = session.get(EmailTemplateRevision, template.current_published_revision_id)
    return TemplateOut(
        id=template.id,
        code=template.code,
        display_name=template.display_name,
        description=template.description,
        module_code=template.module_code,
        active=template.active,
        current_published_revision_id=template.current_published_revision_id,
        draft_revision=_revision_out(draft) if draft else None,
        published_revision=_revision_out(published) if published else None,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _rule_out(rule: WorkflowRecipientRule) -> RecipientRuleOut:
    return RecipientRuleOut(
        id=rule.id,
        recipient_type=rule.recipient_type,  # type: ignore[arg-type]
        strategy_code=rule.strategy_code,
        strategy_config_json=rule.strategy_config_json or {},
        active=rule.active,
        display_order=rule.display_order,
    )


def _workflow_out(session: Session, workflow: NotificationWorkflow) -> WorkflowOut:
    template = session.get(EmailTemplate, workflow.template_id)
    rules = session.scalars(
        select(WorkflowRecipientRule)
        .where(WorkflowRecipientRule.workflow_id == workflow.id)
        .order_by(WorkflowRecipientRule.display_order, WorkflowRecipientRule.id)
    ).all()
    return WorkflowOut(
        id=workflow.id,
        code=workflow.code,
        display_name=workflow.display_name,
        event_type_code=workflow.event_type_code,
        template_id=workflow.template_id,
        template_code=template.code if template else "",
        enabled=workflow.enabled,
        delivery_timing_code=workflow.delivery_timing_code,  # type: ignore[arg-type]
        schedule_config_json=workflow.schedule_config_json,
        recipient_rules=[_rule_out(r) for r in rules],
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def _overview_warnings(settings: Settings, emergency_pause: bool) -> list[str]:
    warnings: list[str] = []
    if not settings.email_enabled:
        warnings.append("Email delivery is disabled (EMAIL_ENABLED is off).")
    if settings.email_delivery_mode == "live" and not settings.email_live_ready:
        warnings.append("Live delivery mode is selected but required settings are incomplete.")
    if settings.email_delivery_mode == "redirect" and not settings.email_redirect_ready:
        warnings.append("Redirect delivery mode is selected but redirect settings are incomplete.")
    if settings.email_provider == "none":
        warnings.append("No email provider is configured (EMAIL_PROVIDER=none).")
    if emergency_pause:
        warnings.append("Emergency pause is active; outbound delivery is suppressed.")
    return warnings


def overview(session: Session, settings: Settings, *, days: int = 7) -> OverviewOut:
    since = _now() - dt.timedelta(days=max(1, days))
    emergency = _settings_row(session).emergency_pause
    pending = session.scalar(
        select(func.count())
        .select_from(NotificationOutbox)
        .where(NotificationOutbox.status == "pending")
    ) or 0
    accepted = session.scalar(
        select(func.count())
        .select_from(EmailDelivery)
        .where(EmailDelivery.status == "accepted", EmailDelivery.queued_at >= since)
    ) or 0
    failed = session.scalar(
        select(func.count())
        .select_from(EmailDelivery)
        .where(
            EmailDelivery.status.in_(("failed", "bounced", "complained")),
            EmailDelivery.queued_at >= since,
        )
    ) or 0
    recent_rows = session.execute(
        select(EmailDelivery, NotificationWorkflow.code)
        .outerjoin(NotificationWorkflow, NotificationWorkflow.id == EmailDelivery.workflow_id)
        .order_by(EmailDelivery.queued_at.desc())
        .limit(10)
    ).all()
    recent = [
        RecentDeliverySummary(
            id=delivery.id,
            status=delivery.status,
            rendered_subject=delivery.rendered_subject,
            queued_at=delivery.queued_at,
            is_test=delivery.is_test,
            workflow_code=workflow_code,
        )
        for delivery, workflow_code in recent_rows
    ]
    return OverviewOut(
        provider=settings.email_provider,
        api_key_configured=settings.resend_configured,
        delivery_mode=settings.email_delivery_mode,
        email_enabled=settings.email_enabled,
        emergency_pause=emergency,
        pending_outbox=pending,
        accepted_count=accepted,
        failed_count=failed,
        warnings=_overview_warnings(settings, emergency),
        recent_deliveries=recent,
    )


def list_event_types(session: Session) -> list[EventTypeOut]:
    rows = session.scalars(
        select(NotificationEventType).order_by(
            NotificationEventType.module_code, NotificationEventType.code
        )
    ).all()
    return [
        EventTypeOut(
            code=row.code,
            display_name=row.display_name,
            module_code=row.module_code,
            description=row.description,
            active=row.active,
            variables=list((row.context_schema_json or {}).get("variables") or []),
        )
        for row in rows
    ]


def list_templates(session: Session) -> list[TemplateOut]:
    templates_rows = session.scalars(
        select(EmailTemplate).order_by(EmailTemplate.module_code, EmailTemplate.code)
    ).all()
    return [_template_out(session, row) for row in templates_rows]


def get_template(session: Session, template_id: int) -> TemplateOut:
    template = session.get(EmailTemplate, template_id)
    if template is None:
        raise NotificationsNotFoundError()
    return _template_out(session, template)


def get_revision(session: Session, template_id: int, revision_id: int) -> TemplateRevisionOut:
    revision = session.get(EmailTemplateRevision, revision_id)
    if revision is None or revision.template_id != template_id:
        raise NotificationsNotFoundError()
    return _revision_out(revision)


def create_draft_from_published(
    session: Session,
    template_id: int,
    *,
    actor: Actor,
) -> TemplateRevisionOut:
    template = session.get(EmailTemplate, template_id)
    if template is None:
        raise NotificationsNotFoundError()
    if template.current_published_revision_id is None:
        raise NotificationsRuleError(
            "no_published_revision", "Publish a revision before creating a draft."
        )
    published = session.get(EmailTemplateRevision, template.current_published_revision_id)
    if published is None:
        raise NotificationsNotFoundError()
    existing_draft = session.scalar(
        select(EmailTemplateRevision.id).where(
            EmailTemplateRevision.template_id == template_id,
            EmailTemplateRevision.status == "draft",
        )
    )
    if existing_draft is not None:
        raise NotificationsRuleError(
            "draft_exists", "A draft revision already exists for this template."
        )
    max_number = session.scalar(
        select(func.max(EmailTemplateRevision.revision_number)).where(
            EmailTemplateRevision.template_id == template_id
        )
    ) or 0
    draft = EmailTemplateRevision(
        template_id=template_id,
        revision_number=max_number + 1,
        status="draft",
        subject_template=published.subject_template,
        html_template=published.html_template,
        text_template=published.text_template,
        variable_schema_json=published.variable_schema_json,
        created_by=actor.actor_id,
    )
    session.add(draft)
    template.updated_by = actor.actor_id
    template.updated_at = _now()
    session.flush()
    _audit(
        session,
        actor=actor,
        changes=[
            AuditChange(
                action="create",
                entity_type=ENTITY_REVISION,
                entity_key=str(draft.id),
                old_value=None,
                new_value={
                    "template_id": template_id,
                    "revision_number": draft.revision_number,
                    "status": "draft",
                },
            )
        ],
    )
    return _revision_out(draft)


def update_draft(
    session: Session,
    template_id: int,
    revision_id: int,
    *,
    actor: Actor,
    subject_template: str | None,
    html_template: str | None,
    text_template: str | None,
) -> TemplateRevisionOut:
    revision = session.get(EmailTemplateRevision, revision_id)
    if revision is None or revision.template_id != template_id:
        raise NotificationsNotFoundError()
    if revision.status != "draft":
        raise NotificationsRuleError("not_draft", "Only draft revisions can be edited.")
    template = session.get(EmailTemplate, template_id)
    if template is None:
        raise NotificationsNotFoundError()
    old = {
        "subject_template": revision.subject_template,
        "html_template": revision.html_template,
        "text_template": revision.text_template,
    }
    if subject_template is not None:
        revision.subject_template = subject_template.strip()
    if html_template is not None:
        revision.html_template = templates.sanitize_html(html_template)
    if text_template is not None:
        revision.text_template = text_template
    template.updated_by = actor.actor_id
    template.updated_at = _now()
    session.flush()
    _audit(
        session,
        actor=actor,
        changes=[
            AuditChange(
                action="update",
                entity_type=ENTITY_REVISION,
                entity_key=str(revision.id),
                old_value=old,
                new_value={
                    "subject_template": revision.subject_template,
                    "html_template": revision.html_template,
                    "text_template": revision.text_template,
                },
            )
        ],
    )
    return _revision_out(revision)


def validate_revision(
    session: Session, template_id: int, revision_id: int, *, event_type_code: str
) -> ValidateOut:
    revision = session.get(EmailTemplateRevision, revision_id)
    if revision is None or revision.template_id != template_id:
        raise NotificationsNotFoundError()
    result = templates.validate_templates(
        event_type_code=event_type_code,
        subject=revision.subject_template,
        html=revision.html_template,
        text=revision.text_template,
    )
    return ValidateOut(
        valid=result.valid,
        unresolved_variables=list(result.unresolved_variables),
        unsupported_variables=list(result.unsupported_variables),
        unsafe_content_findings=list(result.unsafe_content_findings),
        missing_required=list(result.missing_required),
    )


def _resolve_context(
    session: Session,
    settings: Settings,
    *,
    event_type_code: str,
    context: dict[str, Any] | None,
    psm_action_id: int | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = dict(context or {})
    if psm_action_id is not None:
        try:
            payload.update(
                context_providers.get_psm_action_context(
                    session, psm_action_id, settings=settings
                )
            )
        except LookupError as error:
            raise NotificationsNotFoundError() from error
    return build_context(
        payload=payload,
        settings=settings,
        recipient_name=str(payload.get("owner_name") or payload.get("recipient.name") or ""),
        recipient_email=str(payload.get("owner_email") or payload.get("recipient.email") or ""),
        occurred_at=_now(),
        entity_reference=str(
            payload.get("entity.reference") or payload.get("action.reference") or ""
        ),
        entity_url=str(payload.get("entity.url") or payload.get("action.url") or ""),
    )


def preview_revision(
    session: Session,
    settings: Settings,
    template_id: int,
    revision_id: int,
    *,
    event_type_code: str,
    context: dict[str, Any] | None,
    psm_action_id: int | None,
) -> PreviewOut:
    revision = session.get(EmailTemplateRevision, revision_id)
    if revision is None or revision.template_id != template_id:
        raise NotificationsNotFoundError()
    ctx = _resolve_context(
        session,
        settings,
        event_type_code=event_type_code,
        context=context,
        psm_action_id=psm_action_id,
    )
    try:
        subject, html, text = templates.render_email(
            subject_template=revision.subject_template,
            html_template=revision.html_template,
            text_template=revision.text_template,
            context=ctx,
        )
    except KeyError as error:
        raise NotificationsRuleError(
            "unresolved_variable", f"Unresolved template variable: {error}"
        ) from error
    return PreviewOut(subject=subject, html=html, text=text)


def publish_revision(
    session: Session,
    template_id: int,
    revision_id: int,
    *,
    actor: Actor,
    event_type_code: str,
) -> TemplateOut:
    validation = validate_revision(
        session, template_id, revision_id, event_type_code=event_type_code
    )
    if not validation.valid:
        raise NotificationsRuleError("validation_failed", "Template validation failed.")
    revision = session.get(EmailTemplateRevision, revision_id)
    template = session.get(EmailTemplate, template_id)
    if revision is None or template is None or revision.template_id != template_id:
        raise NotificationsNotFoundError()
    if revision.status != "draft":
        raise NotificationsRuleError("not_draft", "Only a draft revision can be published.")
    now = _now()
    previous_published_id = template.current_published_revision_id
    if previous_published_id is not None:
        previous = session.get(EmailTemplateRevision, previous_published_id)
        if previous is not None and previous.status == "published":
            previous.status = "retired"
    revision.status = "published"
    revision.published_at = now
    revision.published_by = actor.actor_id
    revision.variable_schema_json = {"variables": sorted(allowed_variables(event_type_code))}
    template.current_published_revision_id = revision.id
    template.updated_by = actor.actor_id
    template.updated_at = now
    session.flush()
    _audit(
        session,
        actor=actor,
        changes=[
            AuditChange(
                action="update",
                entity_type=ENTITY_TEMPLATE,
                entity_key=str(template.id),
                old_value={"current_published_revision_id": previous_published_id},
                new_value={"current_published_revision_id": revision.id},
            ),
            AuditChange(
                action="update",
                entity_type=ENTITY_REVISION,
                entity_key=str(revision.id),
                old_value={"status": "draft"},
                new_value={"status": "published", "published_at": now.isoformat()},
            ),
        ],
    )
    return _template_out(session, template)


def list_workflows(session: Session) -> list[WorkflowOut]:
    rows = session.scalars(select(NotificationWorkflow).order_by(NotificationWorkflow.code)).all()
    return [_workflow_out(session, row) for row in rows]


def get_workflow(session: Session, workflow_id: int) -> WorkflowOut:
    workflow = session.get(NotificationWorkflow, workflow_id)
    if workflow is None:
        raise NotificationsNotFoundError()
    return _workflow_out(session, workflow)


def update_workflow(
    session: Session,
    workflow_id: int,
    *,
    actor: Actor,
    display_name: str | None,
    enabled: bool | None,
    delivery_timing_code: str | None,
    schedule_config_json: dict[str, Any] | None,
    recipient_rules: list[Any] | None,
) -> WorkflowOut:
    workflow = session.get(NotificationWorkflow, workflow_id)
    if workflow is None:
        raise NotificationsNotFoundError()
    template = session.get(EmailTemplate, workflow.template_id)
    old_enabled = workflow.enabled
    if display_name is not None:
        workflow.display_name = display_name.strip()
    if delivery_timing_code is not None:
        workflow.delivery_timing_code = delivery_timing_code
    if schedule_config_json is not None:
        workflow.schedule_config_json = schedule_config_json
    if enabled is True:
        if template is None or template.current_published_revision_id is None:
            raise NotificationsRuleError(
                "no_published_template",
                "Enable the workflow only after its template has a published revision.",
            )
        workflow.enabled = True
    elif enabled is False:
        workflow.enabled = False
    if recipient_rules is not None:
        for existing in session.scalars(
            select(WorkflowRecipientRule).where(WorkflowRecipientRule.workflow_id == workflow_id)
        ):
            session.delete(existing)
        for index, rule in enumerate(recipient_rules):
            session.add(
                WorkflowRecipientRule(
                    workflow_id=workflow_id,
                    recipient_type=rule.recipient_type,
                    strategy_code=rule.strategy_code,
                    strategy_config_json=rule.strategy_config_json or {},
                    active=rule.active,
                    display_order=rule.display_order if rule.display_order else index,
                )
            )
    workflow.updated_by = actor.actor_id
    workflow.updated_at = _now()
    session.flush()
    _audit(
        session,
        actor=actor,
        changes=[
            AuditChange(
                action="update",
                entity_type=ENTITY_WORKFLOW,
                entity_key=str(workflow.id),
                old_value={"enabled": old_enabled},
                new_value={
                    "enabled": workflow.enabled,
                    **(
                        {"event": "enable" if workflow.enabled else "disable"}
                        if old_enabled != workflow.enabled
                        else {}
                    ),
                },
            )
        ],
    )
    return _workflow_out(session, workflow)


def _delivery_filters_query(filters: DeliveryFilters):
    statement = (
        select(
            EmailDelivery,
            NotificationEvent.event_type_code,
            NotificationWorkflow.code,
            NotificationEvent.entity_reference,
        )
        .outerjoin(NotificationEvent, NotificationEvent.id == EmailDelivery.notification_event_id)
        .outerjoin(NotificationWorkflow, NotificationWorkflow.id == EmailDelivery.workflow_id)
    )
    if filters.status:
        statement = statement.where(EmailDelivery.status == filters.status)
    if filters.from_date:
        start = dt.datetime.combine(filters.from_date, dt.time.min, tzinfo=dt.UTC)
        statement = statement.where(EmailDelivery.queued_at >= start)
    if filters.to_date:
        end = dt.datetime.combine(filters.to_date, dt.time.max, tzinfo=dt.UTC)
        statement = statement.where(EmailDelivery.queued_at <= end)
    if filters.event_type_code:
        statement = statement.where(NotificationEvent.event_type_code == filters.event_type_code)
    if filters.module_code:
        statement = statement.join(
            NotificationEventType,
            NotificationEventType.code == NotificationEvent.event_type_code,
        ).where(NotificationEventType.module_code == filters.module_code)
    if filters.workflow_id:
        statement = statement.where(EmailDelivery.workflow_id == filters.workflow_id)
    if filters.search:
        term = f"%{filters.search.strip()}%"
        statement = statement.where(
            or_(
                EmailDelivery.rendered_subject.ilike(term),
                NotificationEvent.entity_reference.ilike(term),
            )
        )
    return statement


def list_deliveries(
    session: Session, filters: DeliveryFilters
) -> tuple[list[DeliveryListItem], int]:
    base = _delivery_filters_query(filters)
    count_stmt = select(func.count()).select_from(
        base.with_only_columns(EmailDelivery.id).order_by(None).subquery()
    )
    total = session.scalar(count_stmt) or 0
    rows = session.execute(
        base.order_by(EmailDelivery.queued_at.desc())
        .offset(filters.offset)
        .limit(filters.limit)
    ).all()
    items = [
        DeliveryListItem(
            id=delivery.id,
            status=delivery.status,
            delivery_mode=delivery.delivery_mode,
            rendered_subject=delivery.rendered_subject,
            queued_at=delivery.queued_at,
            is_test=delivery.is_test,
            event_type_code=event_type_code,
            workflow_code=workflow_code,
            entity_type=delivery.entity_type,
            entity_id=delivery.entity_id,
            entity_reference=entity_reference,
        )
        for delivery, event_type_code, workflow_code, entity_reference in rows
    ]
    return items, total


def get_delivery_detail(
    session: Session,
    delivery_id: uuid.UUID,
    *,
    include_bcc: bool,
) -> DeliveryDetailOut:
    row = session.execute(
        select(
            EmailDelivery,
            NotificationEvent.event_type_code,
            NotificationWorkflow.code,
            NotificationEvent.entity_reference,
        )
        .outerjoin(NotificationEvent, NotificationEvent.id == EmailDelivery.notification_event_id)
        .outerjoin(NotificationWorkflow, NotificationWorkflow.id == EmailDelivery.workflow_id)
        .where(EmailDelivery.id == delivery_id)
    ).one_or_none()
    if row is None:
        raise NotificationsNotFoundError()
    delivery, event_type_code, workflow_code, entity_reference = row
    attempts = session.scalars(
        select(EmailDeliveryAttempt)
        .where(EmailDeliveryAttempt.email_delivery_id == delivery.id)
        .order_by(EmailDeliveryAttempt.attempt_number)
    ).all()
    bcc_intended = delivery.intended_bcc_json if include_bcc else []
    bcc_actual = delivery.actual_bcc_json if include_bcc else []
    return DeliveryDetailOut(
        id=delivery.id,
        status=delivery.status,
        delivery_mode=delivery.delivery_mode,
        rendered_subject=delivery.rendered_subject,
        rendered_html=delivery.rendered_html,
        rendered_text=delivery.rendered_text,
        queued_at=delivery.queued_at,
        attempted_at=delivery.attempted_at,
        accepted_at=delivery.accepted_at,
        failed_at=delivery.failed_at,
        is_test=delivery.is_test,
        outbox_id=delivery.outbox_id,
        notification_event_id=delivery.notification_event_id,
        workflow_id=delivery.workflow_id,
        workflow_code=workflow_code,
        event_type_code=event_type_code,
        entity_type=delivery.entity_type,
        entity_id=delivery.entity_id,
        entity_reference=entity_reference,
        intended_to_json=delivery.intended_to_json,
        intended_cc_json=delivery.intended_cc_json,
        intended_bcc_json=bcc_intended,
        actual_to_json=delivery.actual_to_json,
        actual_cc_json=delivery.actual_cc_json,
        actual_bcc_json=bcc_actual,
        provider_code=delivery.provider_code,
        provider_message_id=delivery.provider_message_id,
        attempts=[
            DeliveryAttemptOut(
                attempt_number=a.attempt_number,
                started_at=a.started_at,
                completed_at=a.completed_at,
                status=a.status,
                provider_http_status=a.provider_http_status,
                provider_error_code=a.provider_error_code,
                error_message=a.error_message,
                retryable=a.retryable,
            )
            for a in attempts
        ],
    )


def retry_delivery(session: Session, delivery_id: uuid.UUID, *, actor: Actor) -> RetryOut:
    delivery = session.get(EmailDelivery, delivery_id)
    if delivery is None:
        raise NotificationsNotFoundError()
    if delivery.outbox_id is None:
        raise NotificationsRuleError(
            "not_retryable", "This delivery is not linked to an outbox row."
        )
    outbox = session.get(NotificationOutbox, delivery.outbox_id)
    if outbox is None:
        raise NotificationsNotFoundError()
    if outbox.status not in ("failed", "completed"):
        raise NotificationsRuleError(
            "not_retryable", "Only failed or completed outbox rows can be retried."
        )
    now = _now()
    if outbox.attempts >= outbox.max_attempts:
        outbox.max_attempts = outbox.max_attempts + 1
    outbox.status = "pending"
    outbox.available_at = now
    outbox.completed_at = None
    outbox.locked_at = None
    outbox.locked_by = None
    outbox.updated_at = now
    session.flush()
    _audit(
        session,
        actor=actor,
        changes=[
            AuditChange(
                action="update",
                entity_type="notifications.outbox",
                entity_key=str(outbox.id),
                old_value={"status": "failed"},
                new_value={"status": "pending", "delivery_id": str(delivery_id)},
            )
        ],
    )
    return RetryOut(outbox_id=outbox.id, status=outbox.status)


def _effective_test_mode(settings: Settings) -> str:
    if not settings.email_enabled or settings.email_delivery_mode == "disabled":
        return "disabled"
    if settings.email_delivery_mode == "live":
        return "test" if settings.email_live_ready else "disabled"
    if settings.email_delivery_mode == "redirect":
        return "test" if settings.email_redirect_ready else "disabled"
    return "disabled"


def _resolve_test_revision_and_workflow(
    session: Session,
    *,
    template_id: int | None,
    workflow_id: int | None,
    template_revision_id: int | None,
) -> tuple[EmailTemplateRevision, NotificationWorkflow | None, str]:
    workflow: NotificationWorkflow | None = None
    if workflow_id is not None:
        workflow = session.get(NotificationWorkflow, workflow_id)
        if workflow is None:
            raise NotificationsNotFoundError()
        template_id = workflow.template_id
    if template_id is None:
        raise NotificationsRuleError("template_required", "Provide a template or workflow.")
    template = session.get(EmailTemplate, template_id)
    if template is None:
        raise NotificationsNotFoundError()
    revision: EmailTemplateRevision | None = None
    if template_revision_id is not None:
        revision = session.get(EmailTemplateRevision, template_revision_id)
    elif template.current_published_revision_id is not None:
        revision = session.get(EmailTemplateRevision, template.current_published_revision_id)
    if revision is None or revision.template_id != template_id:
        raise NotificationsRuleError(
            "no_revision", "No template revision is available for testing."
        )
    event_type = workflow.event_type_code if workflow else "notifications.test"
    return revision, workflow, event_type


def test_preview(
    session: Session,
    settings: Settings,
    *,
    template_id: int | None,
    workflow_id: int | None,
    template_revision_id: int | None,
    event_type_code: str | None,
    context: dict[str, Any] | None,
    psm_action_id: int | None,
    to_email: str | None,
) -> TestPreviewOut:
    revision, workflow, default_event = _resolve_test_revision_and_workflow(
        session,
        template_id=template_id,
        workflow_id=workflow_id,
        template_revision_id=template_revision_id,
    )
    event_type = event_type_code or default_event
    merged_context = dict(context or {})
    if to_email:
        merged_context["recipient.email"] = to_email
        merged_context["owner_email"] = to_email
    ctx = _resolve_context(
        session,
        settings,
        event_type_code=event_type,
        context=merged_context,
        psm_action_id=psm_action_id,
    )
    subject, html, text = templates.render_email(
        subject_template=revision.subject_template,
        html_template=revision.html_template,
        text_template=revision.text_template,
        context=ctx,
    )
    subject = f"[TEST] {subject}"
    intended = [to_email] if to_email else []
    if workflow is not None and not intended:
        rules = list(
            session.scalars(
                select(WorkflowRecipientRule).where(
                    WorkflowRecipientRule.workflow_id == workflow.id
                )
            )
        )
        payload = context or {}
        if psm_action_id is not None:
            psm_ctx = context_providers.get_psm_action_context(
                session, psm_action_id, settings=settings
            )
            payload = {**payload, **psm_ctx}
        to_r, _, _ = resolve_recipients(session, rules, payload=payload)
        intended = [r.email for r in to_r]
    mode = _effective_test_mode(settings)
    return TestPreviewOut(
        subject=subject,
        html=html,
        text=text,
        intended_to=intended,
        delivery_mode=mode,
    )


def test_send(
    session: Session,
    settings: Settings,
    *,
    actor: Actor,
    template_id: int | None,
    workflow_id: int | None,
    template_revision_id: int | None,
    event_type_code: str | None,
    context: dict[str, Any] | None,
    psm_action_id: int | None,
    to_email: str,
) -> TestSendOut:
    preview = test_preview(
        session,
        settings,
        template_id=template_id,
        workflow_id=workflow_id,
        template_revision_id=template_revision_id,
        event_type_code=event_type_code,
        context=context,
        psm_action_id=psm_action_id,
        to_email=to_email,
    )
    revision, workflow, _ = _resolve_test_revision_and_workflow(
        session,
        template_id=template_id,
        workflow_id=workflow_id,
        template_revision_id=template_revision_id,
    )
    mode = preview.delivery_mode
    now = _now()
    status = "disabled"
    if mode == "disabled":
        delivery = EmailDelivery(
            id=uuid.uuid4(),
            template_revision_id=revision.id,
            workflow_id=workflow.id if workflow else None,
            delivery_mode="disabled",
            intended_to_json=[{"email": to_email, "name": None}],
            intended_cc_json=[],
            intended_bcc_json=[],
            actual_to_json=[],
            actual_cc_json=[],
            actual_bcc_json=[],
            rendered_subject=preview.subject,
            rendered_html=preview.html,
            rendered_text=preview.text,
            status="disabled",
            queued_at=now,
            is_test=True,
            created_by=actor.actor_id,
        )
        session.add(delivery)
        session.flush()
        return TestSendOut(
            delivery_id=delivery.id,
            status=delivery.status,
            delivery_mode=delivery.delivery_mode,
            rendered_subject=delivery.rendered_subject,
        )

    provider = ResendEmailProvider(settings)
    send_to = (to_email,)
    send_subject = preview.subject
    send_html = preview.html
    send_text = preview.text
    if settings.email_delivery_mode == "redirect" and settings.email_redirect_to:
        intended = to_email
        send_subject = f"[TEST][NONPROD REDIRECT] {preview.subject.removeprefix('[TEST] ')}"
        banner = f"<p><strong>Test redirect.</strong> Intended recipient: {intended}</p>"
        send_html = banner + preview.html
        send_text = f"Test redirect. Intended recipient: {intended}\n\n{preview.text}"
        send_to = (settings.email_redirect_to,)

    delivery = EmailDelivery(
        id=uuid.uuid4(),
        template_revision_id=revision.id,
        workflow_id=workflow.id if workflow else None,
        delivery_mode=mode,
        intended_to_json=[{"email": to_email, "name": None}],
        intended_cc_json=[],
        intended_bcc_json=[],
        actual_to_json=[{"email": e, "name": None} for e in send_to],
        actual_cc_json=[],
        actual_bcc_json=[],
        from_address=settings.email_from_address,
        reply_to=settings.email_reply_to,
        rendered_subject=send_subject,
        rendered_html=send_html,
        rendered_text=send_text,
        status="attempting",
        queued_at=now,
        is_test=True,
        created_by=actor.actor_id,
    )
    session.add(delivery)
    session.flush()
    result = provider.send(
        EmailMessage(
            from_email=settings.email_from_address or "",
            from_name=settings.email_from_name,
            to=send_to,
            cc=(),
            bcc=(),
            reply_to=settings.email_reply_to,
            subject=send_subject,
            html=send_html,
            text=send_text,
        )
    )
    finished = _now()
    delivery.attempted_at = now
    session.add(
        EmailDeliveryAttempt(
            email_delivery_id=delivery.id,
            attempt_number=1,
            started_at=now,
            completed_at=finished,
            status="accepted" if result.accepted else "failed",
            provider_http_status=result.http_status,
            provider_error_code=result.provider_error_code,
            sanitized_provider_response_json=result.sanitized_response,
            error_message=result.error_message,
            retryable=result.retryable,
        )
    )
    if result.accepted:
        delivery.status = "accepted"
        delivery.accepted_at = finished
        delivery.provider_code = provider.code
        delivery.provider_message_id = result.provider_message_id
        status = "accepted"
    else:
        delivery.status = "failed"
        delivery.failed_at = finished
        delivery.provider_code = provider.code
        status = "failed"
    session.flush()
    return TestSendOut(
        delivery_id=delivery.id,
        status=status,
        delivery_mode=delivery.delivery_mode,
        rendered_subject=delivery.rendered_subject,
    )


def get_settings(session: Session, settings: Settings) -> SettingsOut:
    row = _settings_row(session)
    return SettingsOut(
        provider=settings.email_provider,
        api_key_configured=settings.resend_configured,
        email_enabled=settings.email_enabled,
        delivery_mode=settings.email_delivery_mode,
        email_from_address=settings.email_from_address,
        email_from_name=settings.email_from_name,
        email_reply_to=settings.email_reply_to,
        email_redirect_to=settings.email_redirect_to,
        emergency_pause=row.emergency_pause,
    )


def update_settings(
    session: Session,
    settings: Settings,
    *,
    actor: Actor,
    emergency_pause: bool | None,
) -> SettingsOut:
    row = _settings_row(session)
    old_pause = row.emergency_pause
    if emergency_pause is not None:
        row.emergency_pause = emergency_pause
        row.updated_by = actor.actor_id
        row.updated_at = _now()
        session.flush()
        _audit(
            session,
            actor=actor,
            changes=[
                AuditChange(
                    action="update",
                    entity_type=ENTITY_SETTINGS,
                    entity_key="1",
                    old_value={"emergency_pause": old_pause},
                    new_value={"emergency_pause": row.emergency_pause},
                )
            ],
        )
    return get_settings(session, settings)
