"""Transactional notification event publisher.

Callers pass their existing SQLAlchemy session. The event and outbox rows are
written in that transaction; Resend is never called here.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.notifications.models import (
    EmailTemplate,
    NotificationEvent,
    NotificationEventType,
    NotificationOutbox,
    NotificationWorkflow,
)
from app.notifications.registry import BY_CODE


class UnknownEventTypeError(ValueError):
    pass


class InactiveEventTypeError(ValueError):
    pass


def has_enabled_workflow(session: Session, event_type_code: str) -> bool:
    return (
        session.scalar(
            select(NotificationWorkflow.id).where(
                NotificationWorkflow.event_type_code == event_type_code,
                NotificationWorkflow.enabled.is_(True),
            ).limit(1)
        )
        is not None
    )


def publish_notification_event(
    session: Session,
    *,
    event_type_code: str,
    entity_type: str,
    entity_id: str,
    entity_reference: str | None,
    payload: dict[str, Any],
    actor_user_id: uuid.UUID | None,
    idempotency_key: str,
    occurred_at: dt.datetime | None = None,
    correlation_id: uuid.UUID | None = None,
    settings: Settings | None = None,
) -> NotificationEvent | None:
    """Insert the event (idempotent) and outbox rows for enabled immediate workflows.

    Returns the event row, or the existing row when the idempotency key already
    exists. Never calls a provider. ``payload`` must not contain secrets.
    """
    cfg = settings or get_settings()
    if event_type_code not in BY_CODE:
        raise UnknownEventTypeError(event_type_code)
    event_type = session.scalar(
        select(NotificationEventType).where(NotificationEventType.code == event_type_code)
    )
    if event_type is None or not event_type.active:
        raise InactiveEventTypeError(event_type_code)

    now = occurred_at or dt.datetime.now(dt.UTC)
    statement = (
        insert(NotificationEvent)
        .values(
            id=uuid.uuid4(),
            event_type_code=event_type_code,
            entity_type=entity_type,
            entity_id=str(entity_id),
            entity_reference=entity_reference,
            payload_json=payload,
            occurred_at=now,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(NotificationEvent.id)
    )
    inserted_id = session.execute(statement).scalar_one_or_none()
    event = session.scalar(
        select(NotificationEvent).where(NotificationEvent.idempotency_key == idempotency_key)
    )
    if event is None:
        raise RuntimeError("notification event missing after insert")
    if inserted_id is None:
        # Prior publish already created outbox rows for this key.
        return event

    workflows = session.scalars(
        select(NotificationWorkflow).where(
            NotificationWorkflow.event_type_code == event_type_code,
            NotificationWorkflow.enabled.is_(True),
            NotificationWorkflow.delivery_timing_code == "immediate",
        )
    ).all()
    max_attempts = cfg.email_outbox_max_attempts
    for workflow in workflows:
        template = session.get(EmailTemplate, workflow.template_id)
        if template is None or template.current_published_revision_id is None:
            continue
        session.execute(
            insert(NotificationOutbox)
            .values(
                id=uuid.uuid4(),
                notification_event_id=event.id,
                workflow_id=workflow.id,
                template_revision_id=template.current_published_revision_id,
                status="pending",
                available_at=now,
                attempts=0,
                max_attempts=max_attempts,
            )
            .on_conflict_do_nothing(constraint="uq_notification_outbox_event_workflow")
        )
    return event
