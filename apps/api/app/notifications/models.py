"""Permanent logged tables for the shared Notifications domain."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SCHEMA = "notifications"


def _timestamps() -> tuple[Mapped[dt.datetime], Mapped[dt.datetime]]:
    created = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    return created, updated  # type: ignore[return-value]


class NotificationEventType(Base):
    __tablename__ = "notification_event_types"
    __table_args__ = (
        CheckConstraint("code ~ '^[a-z][a-z0-9_.]{1,99}$'", name="code"),
        CheckConstraint(
            "btrim(display_name) <> '' AND char_length(display_name) <= 200",
            name="display_name",
        ),
        CheckConstraint(
            "btrim(module_code) <> '' AND char_length(module_code) <= 60",
            name="module_code",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    module_code: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, server_default=text("''"), nullable=False)
    context_schema_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NotificationEvent(Base):
    __tablename__ = "notification_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_notification_events_idempotency_key"),
        Index("ix_notification_events_type_occurred", "event_type_code", "occurred_at"),
        Index("ix_notification_events_entity", "entity_type", "entity_id"),
        CheckConstraint(
            "btrim(idempotency_key) <> '' AND char_length(idempotency_key) <= 300",
            name="idempotency",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_type_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{SCHEMA}.notification_event_types.code", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    entity_reference: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core.users.id", ondelete="RESTRICT")
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EmailTemplate(Base):
    __tablename__ = "email_templates"
    __table_args__ = (
        CheckConstraint("code ~ '^[a-z][a-z0-9_.]{1,99}$'", name="code"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, server_default=text("''"), nullable=False)
    module_code: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    current_published_revision_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)


class EmailTemplateRevision(Base):
    __tablename__ = "email_template_revisions"
    __table_args__ = (
        UniqueConstraint(
            "template_id", "revision_number", name="uq_email_template_revisions_number"
        ),
        CheckConstraint("status IN ('draft', 'published', 'retired')", name="status"),
        CheckConstraint("revision_number >= 1", name="revision_number"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(f"{SCHEMA}.email_templates.id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    subject_template: Mapped[str] = mapped_column(Text, nullable=False)
    html_template: Mapped[str] = mapped_column(Text, nullable=False)
    text_template: Mapped[str] = mapped_column(Text, nullable=False)
    variable_schema_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[str | None] = mapped_column(Text)


class NotificationWorkflow(Base):
    __tablename__ = "notification_workflows"
    __table_args__ = (
        CheckConstraint("code ~ '^[a-z][a-z0-9_.]{1,99}$'", name="code"),
        CheckConstraint("delivery_timing_code IN ('immediate', 'scheduled')", name="timing"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    event_type_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{SCHEMA}.notification_event_types.code", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(f"{SCHEMA}.email_templates.id", ondelete="RESTRICT"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    delivery_timing_code: Mapped[str] = mapped_column(
        Text, server_default=text("'immediate'"), nullable=False
    )
    schedule_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    recipient_resolution_config_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)


class WorkflowRecipientRule(Base):
    __tablename__ = "workflow_recipient_rules"
    __table_args__ = (
        CheckConstraint("recipient_type IN ('to', 'cc', 'bcc')", name="recipient_type"),
        CheckConstraint(
            "strategy_code IN ("
            "'entity_owner', 'entity_creator', 'assigned_user', 'assigned_external_email', "
            "'specific_user', 'specific_role', 'department', 'distribution_group', 'custom_email'"
            ")",
            name="strategy",
        ),
        Index("ix_workflow_recipient_rules_workflow", "workflow_id", "display_order"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{SCHEMA}.notification_workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_type: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_code: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_config_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        UniqueConstraint(
            "notification_event_id", "workflow_id", name="uq_notification_outbox_event_workflow"
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')",
            name="status",
        ),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="attempts"),
        Index("ix_notification_outbox_claim", "status", "available_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    notification_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.notification_events.id", ondelete="RESTRICT"), nullable=False
    )
    workflow_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{SCHEMA}.notification_workflows.id", ondelete="RESTRICT"),
        nullable=False,
    )
    template_revision_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{SCHEMA}.email_template_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), nullable=False)
    available_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, server_default=text("5"), nullable=False)
    locked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(Text)
    last_error_code: Mapped[str | None] = mapped_column(Text)
    last_error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EmailDelivery(Base):
    __tablename__ = "email_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'queued', 'attempting', 'accepted', 'failed', 'suppressed', 'disabled', "
            "'delivered', 'bounced', 'complained'"
            ")",
            name="status",
        ),
        CheckConstraint(
            "delivery_mode IN ('disabled', 'redirect', 'live', 'test')", name="delivery_mode"
        ),
        Index("ix_email_deliveries_queued", "queued_at"),
        Index("ix_email_deliveries_provider_message", "provider_message_id"),
        Index("ix_email_deliveries_entity", "entity_type", "entity_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    outbox_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.notification_outbox.id", ondelete="RESTRICT")
    )
    notification_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.notification_events.id", ondelete="RESTRICT")
    )
    workflow_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(f"{SCHEMA}.notification_workflows.id", ondelete="RESTRICT")
    )
    template_revision_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{SCHEMA}.email_template_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    delivery_mode: Mapped[str] = mapped_column(Text, nullable=False)
    intended_to_json: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    intended_cc_json: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    intended_bcc_json: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    actual_to_json: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    actual_cc_json: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    actual_bcc_json: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    from_address: Mapped[str | None] = mapped_column(Text)
    reply_to: Mapped[str | None] = mapped_column(Text)
    rendered_subject: Mapped[str] = mapped_column(Text, nullable=False)
    rendered_html: Mapped[str] = mapped_column(Text, nullable=False)
    rendered_text: Mapped[str] = mapped_column(Text, nullable=False)
    provider_code: Mapped[str | None] = mapped_column(Text)
    provider_message_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    queued_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attempted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_test: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    created_by: Mapped[str | None] = mapped_column(Text)


class EmailDeliveryAttempt(Base):
    __tablename__ = "email_delivery_attempts"
    __table_args__ = (
        UniqueConstraint(
            "email_delivery_id", "attempt_number", name="uq_email_delivery_attempts_number"
        ),
        CheckConstraint("attempt_number >= 1", name="attempt_number"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email_delivery_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.email_deliveries.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    provider_http_status: Mapped[int | None] = mapped_column(Integer)
    provider_error_code: Mapped[str | None] = mapped_column(Text)
    sanitized_provider_response_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)


class NotificationSettings(Base):
    """Singleton non-secret settings (id = 1). Never stores RESEND_API_KEY."""

    __tablename__ = "notification_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    emergency_pause: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
