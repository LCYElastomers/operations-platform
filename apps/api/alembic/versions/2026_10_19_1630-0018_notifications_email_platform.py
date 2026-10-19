"""notifications email platform

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-19 16:30:00

Creates the shared ``notifications`` schema: event types, events, email templates
and revisions, workflows, recipient rules, outbox, deliveries, attempts, and
singleton settings.

Seeds event-type catalog rows, a draft ``psm.action.assigned`` template, a
disabled owner workflow, default settings, and ``notifications.*`` permissions.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOTIFICATIONS = "notifications"
CORE = "core"

PERMISSIONS = (
    "notifications.view",
    "notifications.templates.manage",
    "notifications.workflows.manage",
    "notifications.delivery.view",
    "notifications.delivery.retry",
    "notifications.test.send",
    "notifications.settings.manage",
)
MODULE_LABELS = {"notifications": "Notifications"}
ROLE_GRANTS = {
    "ADMIN": PERMISSIONS,
    "SAFETY_ADMIN": ("notifications.view", "notifications.delivery.view"),
    "PSM_ADMIN": ("notifications.view", "notifications.delivery.view"),
}

_CODE_PATTERN = "code ~ '^[a-z][a-z0-9_.]{1,99}$'"

# (code, display_name, module_code, description, variables)
EVENT_TYPE_SEEDS: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    (
        "psm.action.assigned",
        "PSM action assigned",
        "psm",
        "A PSM action was created or first assigned to an owner.",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "action.reference",
            "action.title",
            "action.owner_name",
            "action.due_date",
            "action.status",
            "action.url",
            "recommendation.reference",
        ),
    ),
    (
        "psm.action.owner_changed",
        "PSM action owner changed",
        "psm",
        "The owner of a PSM action changed.",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "action.reference",
            "action.title",
            "action.owner_name",
            "action.due_date",
            "action.status",
            "action.url",
            "recommendation.reference",
        ),
    ),
    (
        "psm.action.due_date_changed",
        "PSM action due date changed",
        "psm",
        "The due date of a PSM action changed.",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "action.reference",
            "action.title",
            "action.owner_name",
            "action.due_date",
            "action.status",
            "action.url",
            "recommendation.reference",
        ),
    ),
    (
        "psm.action.due_soon",
        "PSM action due soon",
        "psm",
        "A PSM action is due within the reminder window.",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "action.reference",
            "action.title",
            "action.owner_name",
            "action.due_date",
            "action.status",
            "action.url",
            "recommendation.reference",
        ),
    ),
    (
        "psm.action.overdue",
        "PSM action overdue",
        "psm",
        "A PSM action is past its due date.",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "action.reference",
            "action.title",
            "action.owner_name",
            "action.due_date",
            "action.status",
            "action.url",
            "recommendation.reference",
        ),
    ),
    (
        "psm.closure.requested",
        "PSM closure requested",
        "psm",
        "Closure of a PSM action was requested.",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "action.reference",
            "action.title",
            "action.owner_name",
            "action.due_date",
            "action.status",
            "action.url",
            "recommendation.reference",
        ),
    ),
    (
        "psm.closure.approved",
        "PSM closure approved",
        "psm",
        "Closure of a PSM action was approved.",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "action.reference",
            "action.title",
            "action.owner_name",
            "action.due_date",
            "action.status",
            "action.url",
            "recommendation.reference",
        ),
    ),
    (
        "psm.closure.returned",
        "PSM closure returned",
        "psm",
        "A PSM closure request was returned.",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "action.reference",
            "action.title",
            "action.owner_name",
            "action.due_date",
            "action.status",
            "action.url",
            "recommendation.reference",
        ),
    ),
    (
        "psm.action.reopened",
        "PSM action reopened",
        "psm",
        "A closed PSM action was reopened.",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "action.reference",
            "action.title",
            "action.owner_name",
            "action.due_date",
            "action.status",
            "action.url",
            "recommendation.reference",
        ),
    ),
    (
        "incident.created",
        "Incident created",
        "incident",
        "An incident record was created.",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "incident.reference",
            "incident.occurrence_date",
            "incident.area",
            "incident.classifications",
            "incident.description",
            "incident.url",
        ),
    ),
    (
        "incident.psif_identified",
        "Incident PSIF identified",
        "incident",
        "An incident was designated as a PSIF.",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "incident.reference",
            "incident.occurrence_date",
            "incident.area",
            "incident.classifications",
            "incident.description",
            "incident.url",
        ),
    ),
    (
        "observation.action.assigned",
        "Observation action assigned",
        "safetyObservation",
        "An observation follow-up action was assigned.",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "observation.reference",
            "observation.url",
        ),
    ),
    (
        "observation.action.overdue",
        "Observation action overdue",
        "safetyObservation",
        "An observation follow-up action is overdue.",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "observation.reference",
            "observation.url",
        ),
    ),
    (
        "permit.created",
        "Permit created",
        "permit",
        "A permit was created (registered for future use).",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "permit.number",
            "permit.type",
            "permit.area",
            "permit.location",
            "permit.issued_at",
            "permit.expires_at",
            "permit.url",
        ),
    ),
    (
        "permit.issued",
        "Permit issued",
        "permit",
        "A permit was issued (registered for future use).",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "permit.number",
            "permit.type",
            "permit.area",
            "permit.location",
            "permit.issued_at",
            "permit.expires_at",
            "permit.url",
        ),
    ),
    (
        "permit.amended",
        "Permit amended",
        "permit",
        "A permit was amended (registered for future use).",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "permit.number",
            "permit.type",
            "permit.area",
            "permit.location",
            "permit.issued_at",
            "permit.expires_at",
            "permit.url",
        ),
    ),
    (
        "permit.expiring",
        "Permit expiring",
        "permit",
        "A permit is nearing expiry (registered for future use).",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "permit.number",
            "permit.type",
            "permit.area",
            "permit.location",
            "permit.issued_at",
            "permit.expires_at",
            "permit.url",
        ),
    ),
    (
        "permit.expired",
        "Permit expired",
        "permit",
        "A permit expired (registered for future use).",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "permit.number",
            "permit.type",
            "permit.area",
            "permit.location",
            "permit.issued_at",
            "permit.expires_at",
            "permit.url",
        ),
    ),
    (
        "permit.closed",
        "Permit closed",
        "permit",
        "A permit was closed (registered for future use).",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "permit.number",
            "permit.type",
            "permit.area",
            "permit.location",
            "permit.issued_at",
            "permit.expires_at",
            "permit.url",
        ),
    ),
    (
        "permit.cancelled",
        "Permit cancelled",
        "permit",
        "A permit was cancelled (registered for future use).",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "permit.number",
            "permit.type",
            "permit.area",
            "permit.location",
            "permit.issued_at",
            "permit.expires_at",
            "permit.url",
        ),
    ),
    (
        "notifications.test",
        "Notification test",
        "notifications",
        "Administration Test Center send; never a production business event.",
        (
            "recipient.name",
            "recipient.email",
            "app.base_url",
            "event.occurred_at",
            "entity.reference",
            "entity.url",
            "test.note",
        ),
    ),
)

_PSM_ASSIGNED_SUBJECT = "[PSM] Action assigned: {{action.reference}}"
_PSM_ASSIGNED_HTML = """\
<p>Hello {{recipient.name}},</p>
<p>PSM action <a href="{{action.url}}">{{action.reference}}</a> — {{action.title}} was assigned to you.</p>
<p>Owner: {{action.owner_name}}<br/>Due: {{action.due_date}}<br/>Status: {{action.status}}</p>
<p><a href="{{action.url}}">Open action</a></p>
"""
_PSM_ASSIGNED_TEXT = """\
Hello {{recipient.name}},

PSM action {{action.reference}} — {{action.title}} was assigned to you.

Owner: {{action.owner_name}}
Due: {{action.due_date}}
Status: {{action.status}}

Open: {{action.url}}
"""

TABLES_CREATE_ORDER = (
    "notification_event_types",
    "notification_events",
    "email_templates",
    "email_template_revisions",
    "notification_workflows",
    "workflow_recipient_rules",
    "notification_outbox",
    "email_deliveries",
    "email_delivery_attempts",
    "notification_settings",
)

TABLES_DROP_ORDER = tuple(reversed(TABLES_CREATE_ORDER))


def _ck(table: str, name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _fk(
    table: str,
    column: str,
    target: str,
    *,
    target_schema: str = NOTIFICATIONS,
    ondelete: str = "RESTRICT",
) -> sa.ForeignKeyConstraint:
    referred = target.split(".")[0]
    return sa.ForeignKeyConstraint(
        [column],
        [f"{target_schema}.{target}"],
        name=op.f(f"fk_{table}_{column}_{referred}"),
        ondelete=ondelete,
    )


def _timestamps(*, include_updated: bool = True) -> list[sa.Column]:
    cols = [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]
    if include_updated:
        cols.append(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )
    return cols


def _audit_stamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Text(), nullable=False),
    ]


def _permission_description(code: str) -> str:
    module, action = code.split(".", 1)
    return f"{MODULE_LABELS[module]}: {action}"


def _context_schema(variables: tuple[str, ...]) -> dict[str, Any]:
    return {"variables": list(variables)}


def _ensure_schema() -> None:
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = '{NOTIFICATIONS}') THEN
                    CREATE SCHEMA {NOTIFICATIONS};
                END IF;
            END
            $$
            """
        )
    )


def _create_notification_event_types() -> None:
    t = "notification_event_types"
    op.create_table(
        t,
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("module_code", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "context_schema_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint("code", name=op.f(f"uq_{t}_code")),
        _ck(t, "code", _CODE_PATTERN),
        _ck(
            t,
            "display_name",
            "btrim(display_name) <> '' AND char_length(display_name) <= 200",
        ),
        _ck(t, "module_code", "btrim(module_code) <> '' AND char_length(module_code) <= 60"),
        schema=NOTIFICATIONS,
    )


def _create_notification_events() -> None:
    t = "notification_events"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type_code", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("entity_reference", sa.Text(), nullable=True),
        sa.Column(
            "payload_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_notification_events_idempotency_key")),
        _fk(t, "event_type_code", "notification_event_types.code"),
        _fk(t, "actor_user_id", "users.id", target_schema=CORE),
        _ck(
            t,
            "idempotency",
            "btrim(idempotency_key) <> '' AND char_length(idempotency_key) <= 300",
        ),
        schema=NOTIFICATIONS,
    )
    op.create_index(
        op.f(f"ix_{NOTIFICATIONS}_{t}_event_type_code"),
        t,
        ["event_type_code"],
        schema=NOTIFICATIONS,
    )
    op.create_index(
        "ix_notification_events_type_occurred",
        t,
        ["event_type_code", "occurred_at"],
        schema=NOTIFICATIONS,
    )
    op.create_index(
        "ix_notification_events_entity",
        t,
        ["entity_type", "entity_id"],
        schema=NOTIFICATIONS,
    )


def _create_email_templates() -> None:
    t = "email_templates"
    op.create_table(
        t,
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("module_code", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("current_published_revision_id", sa.Integer(), nullable=True),
        *_audit_stamps(),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint("code", name=op.f(f"uq_{t}_code")),
        _ck(t, "code", _CODE_PATTERN),
        schema=NOTIFICATIONS,
    )


def _create_email_template_revisions() -> None:
    t = "email_template_revisions"
    op.create_table(
        t,
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("subject_template", sa.Text(), nullable=False),
        sa.Column("html_template", sa.Text(), nullable=False),
        sa.Column("text_template", sa.Text(), nullable=False),
        sa.Column(
            "variable_schema_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint(
            "template_id",
            "revision_number",
            name=op.f("uq_email_template_revisions_number"),
        ),
        _fk(t, "template_id", "email_templates.id"),
        _ck(t, "status", "status IN ('draft', 'published', 'retired')"),
        _ck(t, "revision_number", "revision_number >= 1"),
        schema=NOTIFICATIONS,
    )
    op.create_index(
        "uq_email_template_revisions_one_draft",
        t,
        ["template_id"],
        unique=True,
        schema=NOTIFICATIONS,
        postgresql_where=sa.text("status = 'draft'"),
    )


def _link_email_templates_published_revision() -> None:
    op.create_foreign_key(
        op.f("fk_email_templates_current_published_revision_id_email_template_revisions"),
        "email_templates",
        "email_template_revisions",
        ["current_published_revision_id"],
        ["id"],
        source_schema=NOTIFICATIONS,
        referent_schema=NOTIFICATIONS,
        ondelete="RESTRICT",
    )


def _create_notification_workflows() -> None:
    t = "notification_workflows"
    op.create_table(
        t,
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("event_type_code", sa.Text(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "delivery_timing_code",
            sa.Text(),
            server_default=sa.text("'immediate'"),
            nullable=False,
        ),
        sa.Column("schedule_config_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "recipient_resolution_config_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *_audit_stamps(),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint("code", name=op.f(f"uq_{t}_code")),
        _fk(t, "event_type_code", "notification_event_types.code"),
        _fk(t, "template_id", "email_templates.id"),
        _ck(t, "code", _CODE_PATTERN),
        _ck(t, "timing", "delivery_timing_code IN ('immediate', 'scheduled')"),
        schema=NOTIFICATIONS,
    )
    op.create_index(
        op.f(f"ix_{NOTIFICATIONS}_{t}_event_type_code"),
        t,
        ["event_type_code"],
        schema=NOTIFICATIONS,
    )


def _create_workflow_recipient_rules() -> None:
    t = "workflow_recipient_rules"
    op.create_table(
        t,
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("recipient_type", sa.Text(), nullable=False),
        sa.Column("strategy_code", sa.Text(), nullable=False),
        sa.Column(
            "strategy_config_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        _fk(t, "workflow_id", "notification_workflows.id", ondelete="CASCADE"),
        _ck(t, "recipient_type", "recipient_type IN ('to', 'cc', 'bcc')"),
        _ck(
            t,
            "strategy",
            "strategy_code IN ("
            "'entity_owner', 'entity_creator', 'assigned_user', 'assigned_external_email', "
            "'specific_user', 'specific_role', 'department', 'distribution_group', 'custom_email'"
            ")",
        ),
        schema=NOTIFICATIONS,
    )
    op.create_index(
        "ix_workflow_recipient_rules_workflow",
        t,
        ["workflow_id", "display_order"],
        schema=NOTIFICATIONS,
    )


def _create_notification_outbox() -> None:
    t = "notification_outbox"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("notification_event_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("template_revision_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint(
            "notification_event_id",
            "workflow_id",
            name=op.f("uq_notification_outbox_event_workflow"),
        ),
        _fk(t, "notification_event_id", "notification_events.id"),
        _fk(t, "workflow_id", "notification_workflows.id"),
        _fk(t, "template_revision_id", "email_template_revisions.id"),
        _ck(
            t,
            "status",
            "status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')",
        ),
        _ck(t, "attempts", "attempts >= 0 AND max_attempts >= 1"),
        schema=NOTIFICATIONS,
    )
    op.create_index(
        "ix_notification_outbox_claim",
        t,
        ["status", "available_at"],
        schema=NOTIFICATIONS,
    )


def _create_email_deliveries() -> None:
    t = "email_deliveries"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("outbox_id", sa.Uuid(), nullable=True),
        sa.Column("notification_event_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_id", sa.Integer(), nullable=True),
        sa.Column("template_revision_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=True),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("delivery_mode", sa.Text(), nullable=False),
        sa.Column(
            "intended_to_json",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "intended_cc_json",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "intended_bcc_json",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "actual_to_json",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "actual_cc_json",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "actual_bcc_json",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("from_address", sa.Text(), nullable=True),
        sa.Column("reply_to", sa.Text(), nullable=True),
        sa.Column("rendered_subject", sa.Text(), nullable=False),
        sa.Column("rendered_html", sa.Text(), nullable=False),
        sa.Column("rendered_text", sa.Text(), nullable=False),
        sa.Column("provider_code", sa.Text(), nullable=True),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "queued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("is_test", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        _fk(t, "outbox_id", "notification_outbox.id"),
        _fk(t, "notification_event_id", "notification_events.id"),
        _fk(t, "workflow_id", "notification_workflows.id"),
        _fk(t, "template_revision_id", "email_template_revisions.id"),
        _ck(
            t,
            "status",
            "status IN ("
            "'queued', 'attempting', 'accepted', 'failed', 'suppressed', 'disabled', "
            "'delivered', 'bounced', 'complained'"
            ")",
        ),
        _ck(t, "delivery_mode", "delivery_mode IN ('disabled', 'redirect', 'live', 'test')"),
        schema=NOTIFICATIONS,
    )
    op.create_index("ix_email_deliveries_queued", t, ["queued_at"], schema=NOTIFICATIONS)
    op.create_index(
        "ix_email_deliveries_provider_message",
        t,
        ["provider_message_id"],
        schema=NOTIFICATIONS,
    )
    op.create_index(
        "ix_email_deliveries_entity",
        t,
        ["entity_type", "entity_id"],
        schema=NOTIFICATIONS,
    )


def _create_email_delivery_attempts() -> None:
    t = "email_delivery_attempts"
    op.create_table(
        t,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("email_delivery_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("provider_http_status", sa.Integer(), nullable=True),
        sa.Column("provider_error_code", sa.Text(), nullable=True),
        sa.Column("sanitized_provider_response_json", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint(
            "email_delivery_id",
            "attempt_number",
            name=op.f("uq_email_delivery_attempts_number"),
        ),
        _fk(t, "email_delivery_id", "email_deliveries.id"),
        _ck(t, "attempt_number", "attempt_number >= 1"),
        schema=NOTIFICATIONS,
    )


def _create_notification_settings() -> None:
    t = "notification_settings"
    op.create_table(
        t,
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("emergency_pause", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        _ck(t, "singleton", "id = 1"),
        schema=NOTIFICATIONS,
    )


def _create_tables() -> None:
    _create_notification_event_types()
    _create_notification_events()
    _create_email_templates()
    _create_email_template_revisions()
    _link_email_templates_published_revision()
    _create_notification_workflows()
    _create_workflow_recipient_rules()
    _create_notification_outbox()
    _create_email_deliveries()
    _create_email_delivery_attempts()
    _create_notification_settings()


def _seed_event_types() -> None:
    rows = [
        {
            "code": code,
            "display_name": display_name,
            "module_code": module_code,
            "description": description,
            "context_schema_json": _context_schema(variables),
        }
        for code, display_name, module_code, description, variables in EVENT_TYPE_SEEDS
    ]
    op.bulk_insert(
        sa.table(
            "notification_event_types",
            sa.column("code", sa.Text),
            sa.column("display_name", sa.Text),
            sa.column("module_code", sa.Text),
            sa.column("description", sa.Text),
            sa.column("context_schema_json", postgresql.JSONB),
            schema=NOTIFICATIONS,
        ),
        rows,
    )


def _seed_template_and_workflow() -> None:
    migration_actor = "migration-0018"
    psm_vars = _context_schema(EVENT_TYPE_SEEDS[0][4])
    op.bulk_insert(
        sa.table(
            "email_templates",
            sa.column("code", sa.Text),
            sa.column("display_name", sa.Text),
            sa.column("description", sa.Text),
            sa.column("module_code", sa.Text),
            sa.column("created_by", sa.Text),
            sa.column("updated_by", sa.Text),
            schema=NOTIFICATIONS,
        ),
        [
            {
                "code": "psm.action.assigned",
                "display_name": "PSM action assigned",
                "description": "",
                "module_code": "psm",
                "created_by": migration_actor,
                "updated_by": migration_actor,
            }
        ],
    )
    conn = op.get_bind()
    template_id = conn.execute(
        sa.text(
            f"SELECT id FROM {NOTIFICATIONS}.email_templates WHERE code = 'psm.action.assigned'"
        )
    ).scalar_one()
    op.bulk_insert(
        sa.table(
            "email_template_revisions",
            sa.column("template_id", sa.Integer),
            sa.column("revision_number", sa.Integer),
            sa.column("status", sa.Text),
            sa.column("subject_template", sa.Text),
            sa.column("html_template", sa.Text),
            sa.column("text_template", sa.Text),
            sa.column("variable_schema_json", postgresql.JSONB),
            sa.column("created_by", sa.Text),
            schema=NOTIFICATIONS,
        ),
        [
            {
                "template_id": template_id,
                "revision_number": 1,
                "status": "draft",
                "subject_template": _PSM_ASSIGNED_SUBJECT,
                "html_template": _PSM_ASSIGNED_HTML,
                "text_template": _PSM_ASSIGNED_TEXT,
                "variable_schema_json": psm_vars,
                "created_by": migration_actor,
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "notification_workflows",
            sa.column("code", sa.Text),
            sa.column("display_name", sa.Text),
            sa.column("event_type_code", sa.Text),
            sa.column("template_id", sa.Integer),
            sa.column("enabled", sa.Boolean),
            sa.column("created_by", sa.Text),
            sa.column("updated_by", sa.Text),
            schema=NOTIFICATIONS,
        ),
        [
            {
                "code": "psm.action.assigned.owner",
                "display_name": "PSM action assigned (owner)",
                "event_type_code": "psm.action.assigned",
                "template_id": template_id,
                "enabled": False,
                "created_by": migration_actor,
                "updated_by": migration_actor,
            }
        ],
    )
    workflow_id = conn.execute(
        sa.text(
            f"SELECT id FROM {NOTIFICATIONS}.notification_workflows "
            "WHERE code = 'psm.action.assigned.owner'"
        )
    ).scalar_one()
    op.bulk_insert(
        sa.table(
            "workflow_recipient_rules",
            sa.column("workflow_id", sa.Integer),
            sa.column("recipient_type", sa.Text),
            sa.column("strategy_code", sa.Text),
            sa.column("strategy_config_json", postgresql.JSONB),
            schema=NOTIFICATIONS,
        ),
        [
            {
                "workflow_id": workflow_id,
                "recipient_type": "to",
                "strategy_code": "assigned_external_email",
                "strategy_config_json": {},
            }
        ],
    )


def _seed_settings() -> None:
    op.bulk_insert(
        sa.table(
            "notification_settings",
            sa.column("id", sa.Integer),
            sa.column("emergency_pause", sa.Boolean),
            sa.column("updated_by", sa.Text),
            schema=NOTIFICATIONS,
        ),
        [{"id": 1, "emergency_pause": False, "updated_by": "migration-0018"}],
    )


def _grant_permissions() -> None:
    op.bulk_insert(
        sa.table(
            "permissions",
            sa.column("code", sa.Text),
            sa.column("module", sa.Text),
            sa.column("description", sa.Text),
            schema=CORE,
        ),
        [
            {
                "code": code,
                "module": "notifications",
                "description": _permission_description(code),
            }
            for code in PERMISSIONS
        ],
    )
    grants = [(role, permission) for role, codes in ROLE_GRANTS.items() for permission in codes]
    values = ",\n            ".join(f"('{role}', '{permission}')" for role, permission in grants)
    op.execute(
        sa.text(
            f"""
            INSERT INTO {CORE}.role_permissions (role_code, permission_code)
            SELECT v.role_code, v.permission_code
            FROM (VALUES
            {values}
            ) AS v (role_code, permission_code)
            WHERE EXISTS (SELECT 1 FROM {CORE}.roles r WHERE r.code = v.role_code)
            ON CONFLICT DO NOTHING
            """
        )
    )


def upgrade() -> None:
    _ensure_schema()
    _create_tables()
    _seed_event_types()
    _seed_template_and_workflow()
    _seed_settings()
    _grant_permissions()


DOWNGRADE_GUARD = f"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM {NOTIFICATIONS}.notification_events) THEN
        RAISE EXCEPTION 'Cannot downgrade: notification events exist';
    END IF;
    IF EXISTS (SELECT 1 FROM {NOTIFICATIONS}.email_deliveries) THEN
        RAISE EXCEPTION 'Cannot downgrade: email deliveries exist';
    END IF;
    IF EXISTS (SELECT 1 FROM {NOTIFICATIONS}.notification_outbox) THEN
        RAISE EXCEPTION 'Cannot downgrade: notification outbox rows exist';
    END IF;
END
$$
"""


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_GUARD))
    codes = ", ".join(f"'{code}'" for code in PERMISSIONS)
    op.execute(sa.text(f"DELETE FROM {CORE}.role_permissions WHERE permission_code IN ({codes})"))
    op.execute(sa.text(f"DELETE FROM {CORE}.permissions WHERE code IN ({codes})"))
    op.drop_constraint(
        op.f("fk_email_templates_current_published_revision_id_email_template_revisions"),
        "email_templates",
        schema=NOTIFICATIONS,
        type_="foreignkey",
    )
    for table in TABLES_DROP_ORDER:
        op.drop_table(table, schema=NOTIFICATIONS)
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = '{NOTIFICATIONS}'
                ) THEN
                    RAISE EXCEPTION 'Cannot downgrade: notifications schema is not empty';
                END IF;
            END
            $$
            """
        )
    )
    op.execute(sa.text(f"DROP SCHEMA IF EXISTS {NOTIFICATIONS}"))
