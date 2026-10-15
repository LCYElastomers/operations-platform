"""process safety management

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-12 16:00:00

Creates the Process Safety Management tables in the ``safety`` schema:
studies (and the ``safety.areas`` they cover), recommendations, hazard
scenarios, actions, action updates, evidence attachments, the notification
outbox and settings, and the reference lists (study types, departments,
process nodes, PSM elements).

Seeds reference data only, never recommendations or actions:

- study type PHA;
- the 14 OSHA 1910.119 PSM elements (for audits);
- departments, as named in the Department column of the historical PHA sheets
  of PSM Dashboard 1.xlsx (2024 PHA - 500,800,900; 2023 PHA - 100,200;
  2021 PHA -300,400,600), trimmed, without the sheets' footer totals. Both
  "Health & Safety" and "Health and Safety (EHS)" appear there and are kept as
  written; an administrator may deactivate one;
- the notification settings row.

Process nodes come from the reviewed import of the 2026 PHA sheet.

Adds the ``psm.*`` permissions, grants them to ADMIN and SAFETY_ADMIN (all),
SAFETY_USER (view, manage actions, request closure) and VIEWER (view), and adds
the standard role PSM_ADMIN.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFETY = "safety"
CORE = "core"

PERMISSIONS = (
    "psm.view",
    "psm.manageStudies",
    "psm.editRecommendations",
    "psm.decideDisposition",
    "psm.manageActions",
    "psm.requestClosure",
    "psm.verifyClosure",
    "psm.reopen",
    "psm.admin",
    "psm.import",
    "psm.export",
)
MODULE_LABEL = "Process Safety Management"
ROLE_GRANTS = {
    "ADMIN": PERMISSIONS,
    "SAFETY_ADMIN": PERMISSIONS,
    "SAFETY_USER": ("psm.view", "psm.manageActions", "psm.requestClosure"),
    "VIEWER": ("psm.view",),
}
NEW_ROLE = (
    "PSM_ADMIN",
    "PSM Administrator",
    "Administers Process Safety Management: PHA studies, recommendations and hazard "
    "scenarios, dispositions, actions, closure verification, reference data, imports and "
    "exports. No other Safety, Quality, user or role administration.",
)
NEW_ROLE_PERMISSIONS = ("app.view", *PERMISSIONS)

DEPARTMENTS = (
    "Contractor Management",
    "Engineering",
    "Health & Safety",
    "Health and Safety (EHS)",
    "Instrumentation & Controls",
    "Leadership",
    "Maintenance",
    "Mechanical Integrity",
    "Operations",
    "Reliability",
)

PSM_ELEMENTS = (
    ("employee_participation", "Employee Participation", "1910.119(c)"),
    ("process_safety_information", "Process Safety Information", "1910.119(d)"),
    ("process_hazard_analysis", "Process Hazard Analysis", "1910.119(e)"),
    ("operating_procedures", "Operating Procedures", "1910.119(f)"),
    ("training", "Training", "1910.119(g)"),
    ("contractors", "Contractors", "1910.119(h)"),
    ("pre_startup_safety_review", "Pre-Startup Safety Review", "1910.119(i)"),
    ("mechanical_integrity", "Mechanical Integrity", "1910.119(j)"),
    ("hot_work_permit", "Hot Work Permit", "1910.119(k)"),
    ("management_of_change", "Management of Change", "1910.119(l)"),
    ("incident_investigation", "Incident Investigation", "1910.119(m)"),
    ("emergency_planning_and_response", "Emergency Planning and Response", "1910.119(n)"),
    ("compliance_audits", "Compliance Audits", "1910.119(o)"),
    ("trade_secrets", "Trade Secrets", "1910.119(p)"),
)

NAME_KEY_SQL = "lower(regexp_replace(btrim(name), '\\s+', ' ', 'g'))"
EMAIL_PATTERN = "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$"


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _text(column: str, length: int, *, optional: bool = False) -> str:
    rule = f"btrim({column}) <> '' AND char_length({column}) <= {length}"
    return f"{column} IS NULL OR ({rule})" if optional else rule


def _ck(table: str, name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _fk(table: str, column: str, target: str, target_schema: str = SAFETY, ondelete: str = "RESTRICT") -> sa.ForeignKeyConstraint:
    referred = target.split(".")[0]
    return sa.ForeignKeyConstraint(
        [column],
        [f"{target_schema}.{target}"],
        name=op.f(f"fk_{table}_{column}_{referred}"),
        ondelete=ondelete,
    )


def _now() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
    ]


def _user_index(table: str, column: str) -> None:
    op.create_index(op.f(f"ix_{SAFETY}_{table}_{column}"), table, [column], schema=SAFETY)


DISPOSITIONS = ("pending_review", "accepted", "rejected")
ACTION_STATUSES = ("not_started", "in_progress", "pending_verification", "closed")
RISKS = ("high", "medium", "low")
STUDY_STATUSES = ("active", "complete", "archived")
EVIDENCE_TYPES = (
    "engineering_calculation",
    "moc",
    "work_order",
    "photo",
    "pid",
    "procedure",
    "training_record",
    "inspection",
    "other",
)
UPDATE_TYPES = (
    "comment",
    "status_change",
    "closure_request",
    "closure_approved",
    "closure_returned",
    "reopened",
    "assignment",
    "disposition",
)
NOTIFICATION_EVENTS = (
    "action_assigned",
    "owner_changed",
    "due_date_changed",
    "due_soon",
    "overdue",
    "status_changed",
    "comment_added",
    "closure_requested",
    "closure_approved",
    "closure_returned",
    "reopened",
)
NOTIFICATION_STATUSES = ("queued", "sent", "failed", "skipped")


def _create_reference_tables() -> None:
    t = "psm_study_types"
    op.create_table(
        t,
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _now(),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint("code", name=op.f(f"uq_{t}_code")),
        _ck(t, "code", "code ~ '^[a-z0-9_]{1,50}$'"),
        _ck(t, "name", _text("name", 100)),
        schema=SAFETY,
    )
    for t, length in (("psm_departments", 200), ("psm_process_nodes", 1000)):
        op.create_table(
            t,
            sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("name_key", sa.Text(), nullable=False),
            sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("display_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
            *_stamps(),
            sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
            sa.UniqueConstraint("name_key", name=op.f(f"uq_{t}_name_key")),
            _ck(t, "name", _text("name", length)),
            _ck(t, "name_key", f"name_key = {NAME_KEY_SQL}"),
            schema=SAFETY,
        )
    t = "psm_elements"
    op.create_table(
        t,
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("regulation", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint("code", name=op.f(f"uq_{t}_code")),
        _ck(t, "code", "code ~ '^[a-z0-9_]{1,50}$'"),
        _ck(t, "name", _text("name", 200)),
        schema=SAFETY,
    )


def _create_studies() -> None:
    t = "psm_studies"
    op.create_table(
        t,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("study_code", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("study_type_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("recommendation_prefix", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("study_date", sa.Date(), nullable=True),
        sa.Column("source_file_name", sa.Text(), nullable=True),
        sa.Column("source_sheet_name", sa.Text(), nullable=True),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("source_key", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_stamps(),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint("study_code", name=op.f(f"uq_{t}_study_code")),
        sa.UniqueConstraint("recommendation_prefix", name=op.f(f"uq_{t}_recommendation_prefix")),
        _fk(t, "study_type_id", "psm_study_types.id"),
        _ck(t, "study_code", "study_code ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,59}$'"),
        _ck(t, "recommendation_prefix", "recommendation_prefix ~ '^[A-Z0-9][A-Z0-9-]{0,29}$'"),
        _ck(t, "title", _text("title", 200)),
        _ck(t, "year", "year BETWEEN 1990 AND 2100"),
        _ck(t, "status", _in("status", STUDY_STATUSES)),
        _ck(t, "description", _text("description", 8000, optional=True)),
        _ck(
            t,
            "source_key",
            "source_key IS NULL OR (btrim(source_key) <> '' AND char_length(source_key) <= 300)",
        ),
        _ck(t, "version", "version >= 1"),
        schema=SAFETY,
    )
    op.create_index(
        "uq_psm_studies_source_key",
        t,
        ["source_key"],
        unique=True,
        schema=SAFETY,
        postgresql_where=sa.text("source_key IS NOT NULL"),
    )
    op.create_index("ix_psm_studies_year", t, ["year"], schema=SAFETY)

    t = "psm_study_areas"
    op.create_table(
        t,
        sa.Column("study_id", sa.BigInteger(), nullable=False),
        sa.Column("area_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("study_id", "area_id", name=op.f(f"pk_{t}")),
        _fk(t, "study_id", "psm_studies.id", ondelete="CASCADE"),
        _fk(t, "area_id", "areas.id"),
        schema=SAFETY,
    )
    op.create_index("ix_psm_study_areas_area_id", t, ["area_id"], schema=SAFETY)


def _create_recommendations() -> None:
    t = "psm_recommendations"
    op.create_table(
        t,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("study_id", sa.BigInteger(), nullable=False),
        sa.Column("recommendation_number", sa.Integer(), nullable=False),
        sa.Column("display_id", sa.Text(), nullable=False),
        sa.Column("area_equipment", sa.Text(), nullable=False),
        sa.Column("recommendation_text", sa.Text(), nullable=False),
        sa.Column("process_node_id", sa.Integer(), nullable=True),
        sa.Column("disposition", sa.Text(), server_default=sa.text("'pending_review'"), nullable=False),
        sa.Column("disposition_justification", sa.Text(), nullable=True),
        sa.Column("disposition_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("disposition_by_name", sa.Text(), nullable=True),
        sa.Column("disposition_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_draft", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("source_row_start", sa.Integer(), nullable=True),
        sa.Column("source_row_end", sa.Integer(), nullable=True),
        sa.Column("source_key", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_stamps(),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by", sa.Text(), nullable=True),
        sa.Column("archive_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint(
            "study_id", "recommendation_number", name=op.f(f"uq_{t}_study_id_recommendation_number")
        ),
        sa.UniqueConstraint("display_id", name=op.f(f"uq_{t}_display_id")),
        _fk(t, "study_id", "psm_studies.id"),
        _fk(t, "process_node_id", "psm_process_nodes.id"),
        _fk(t, "disposition_by_user_id", "users.id", target_schema=CORE),
        _ck(t, "recommendation_number", "recommendation_number BETWEEN 1 AND 9999"),
        _ck(t, "area_equipment", _text("area_equipment", 200)),
        _ck(t, "recommendation_text", _text("recommendation_text", 8000)),
        _ck(t, "disposition", _in("disposition", DISPOSITIONS)),
        _ck(
            t,
            "rejected_has_justification",
            "disposition <> 'rejected' OR disposition_justification IS NOT NULL",
        ),
        _ck(t, "decided_has_time", "disposition = 'pending_review' OR disposition_at IS NOT NULL"),
        _ck(
            t,
            "disposition_justification",
            _text("disposition_justification", 8000, optional=True),
        ),
        _ck(t, "notes", _text("notes", 8000, optional=True)),
        _ck(t, "archive_reason", "(archived_at IS NULL) = (archive_reason IS NULL)"),
        _ck(
            t,
            "source_key",
            "source_key IS NULL OR (btrim(source_key) <> '' AND char_length(source_key) <= 300)",
        ),
        _ck(t, "version", "version >= 1"),
        schema=SAFETY,
    )
    op.create_index(
        "uq_psm_recommendations_source_key",
        t,
        ["source_key"],
        unique=True,
        schema=SAFETY,
        postgresql_where=sa.text("source_key IS NOT NULL"),
    )
    op.create_index("ix_psm_recommendations_disposition", t, ["disposition"], schema=SAFETY)
    op.create_index("ix_psm_recommendations_process_node_id", t, ["process_node_id"], schema=SAFETY)
    op.create_index("ix_psm_recommendations_archived_at", t, ["archived_at"], schema=SAFETY)
    _user_index(t, "disposition_by_user_id")

    t = "psm_scenarios"
    op.create_table(
        t,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("recommendation_id", sa.BigInteger(), nullable=False),
        sa.Column("sequence_number", sa.SmallInteger(), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("cause", sa.Text(), nullable=False),
        sa.Column("consequence", sa.Text(), nullable=False),
        sa.Column("risk", sa.Text(), nullable=False),
        sa.Column("risk_source", sa.Text(), nullable=True),
        sa.Column("area_equipment", sa.Text(), nullable=True),
        sa.Column("process_node_id", sa.Integer(), nullable=True),
        sa.Column("source_row", sa.Integer(), nullable=True),
        sa.Column("source_cells", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_stamps(),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint(
            "recommendation_id",
            "sequence_number",
            name=op.f(f"uq_{t}_recommendation_id_sequence_number"),
            deferrable=True,
            initially="DEFERRED",
        ),
        _fk(t, "recommendation_id", "psm_recommendations.id"),
        _fk(t, "process_node_id", "psm_process_nodes.id"),
        _ck(t, "sequence_number", "sequence_number BETWEEN 1 AND 999"),
        _ck(t, "event", _text("event", 8000)),
        _ck(t, "cause", _text("cause", 8000)),
        _ck(t, "consequence", _text("consequence", 8000)),
        _ck(t, "risk", _in("risk", RISKS)),
        _ck(t, "area_equipment", _text("area_equipment", 200, optional=True)),
        _ck(t, "version", "version >= 1"),
        schema=SAFETY,
    )
    op.create_index("ix_psm_scenarios_risk", t, ["risk"], schema=SAFETY)
    op.create_index("ix_psm_scenarios_process_node_id", t, ["process_node_id"], schema=SAFETY)


def _create_actions() -> None:
    t = "psm_actions"
    op.create_table(
        t,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("recommendation_id", sa.BigInteger(), nullable=False),
        sa.Column("action_number", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("owner_name", sa.Text(), nullable=True),
        sa.Column("owner_email", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'not_started'"), nullable=False),
        sa.Column("closure_summary", sa.Text(), nullable=True),
        sa.Column("closure_exception_reason", sa.Text(), nullable=True),
        sa.Column("closure_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closure_requested_by", sa.Text(), nullable=True),
        sa.Column("closure_requested_by_name", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by", sa.Text(), nullable=True),
        sa.Column("verified_by_name", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("return_reason", sa.Text(), nullable=True),
        sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reopen_reason", sa.Text(), nullable=True),
        sa.Column("requires_resolution", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_stamps(),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by", sa.Text(), nullable=True),
        sa.Column("archive_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint("recommendation_id", name=op.f(f"uq_{t}_recommendation_id")),
        sa.UniqueConstraint("action_number", name=op.f(f"uq_{t}_action_number")),
        _fk(t, "recommendation_id", "psm_recommendations.id"),
        _fk(t, "department_id", "psm_departments.id"),
        _fk(t, "owner_user_id", "users.id", target_schema=CORE),
        _ck(t, "action_number", "action_number ~ '^PSM-ACT-[0-9]{4}-[0-9]{3,6}$'"),
        _ck(t, "title", _text("title", 500)),
        _ck(t, "description", _text("description", 8000, optional=True)),
        _ck(t, "owner_name", _text("owner_name", 200, optional=True)),
        _ck(
            t,
            "owner_email",
            "owner_email IS NULL OR (owner_email = lower(btrim(owner_email)) "
            f"AND char_length(owner_email) <= 254 AND owner_email ~ '{EMAIL_PATTERN}')",
        ),
        _ck(t, "status", _in("status", ACTION_STATUSES)),
        _ck(
            t,
            "closure_requested",
            "status NOT IN ('pending_verification', 'closed') "
            "OR (closure_summary IS NOT NULL AND closure_requested_at IS NOT NULL)",
        ),
        _ck(
            t,
            "closed_is_verified",
            "status <> 'closed' OR (closed_at IS NOT NULL AND verified_at IS NOT NULL "
            "AND verified_by IS NOT NULL)",
        ),
        _ck(t, "closed_at", "status = 'closed' OR closed_at IS NULL"),
        _ck(t, "archive_reason", "(archived_at IS NULL) = (archive_reason IS NULL)"),
        _ck(t, "version", "version >= 1"),
        schema=SAFETY,
    )
    for column in ("status", "due_date", "department_id", "owner_name", "archived_at"):
        op.create_index(f"ix_psm_actions_{column}", t, [column], schema=SAFETY)
    _user_index(t, "owner_user_id")

    t = "psm_action_updates"
    op.create_table(
        t,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("action_id", sa.BigInteger(), nullable=False),
        sa.Column("update_type", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("previous_status", sa.Text(), nullable=True),
        sa.Column("new_status", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_name", sa.Text(), nullable=False),
        _now(),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        _fk(t, "action_id", "psm_actions.id"),
        _fk(t, "created_by_user_id", "users.id", target_schema=CORE),
        _ck(t, "update_type", _in("update_type", UPDATE_TYPES)),
        _ck(t, "body", _text("body", 8000)),
        _ck(t, "previous_status", f"previous_status IS NULL OR {_in('previous_status', ACTION_STATUSES)}"),
        _ck(t, "new_status", f"new_status IS NULL OR {_in('new_status', ACTION_STATUSES)}"),
        schema=SAFETY,
    )
    op.create_index("ix_psm_action_updates_action_id", t, ["action_id", "created_at"], schema=SAFETY)
    _user_index(t, "created_by_user_id")

    t = "psm_attachments"
    op.create_table(
        t,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("recommendation_id", sa.BigInteger(), nullable=True),
        sa.Column("action_id", sa.BigInteger(), nullable=True),
        sa.Column("evidence_type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("original_file_name", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("uploaded_by", sa.Text(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("uploaded_by_name", sa.Text(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by", sa.Text(), nullable=True),
        sa.Column("removed_by_name", sa.Text(), nullable=True),
        sa.Column("removal_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        _fk(t, "recommendation_id", "psm_recommendations.id"),
        _fk(t, "action_id", "psm_actions.id"),
        _fk(t, "uploaded_by_user_id", "users.id", target_schema=CORE),
        _ck(t, "one_parent", "(recommendation_id IS NULL) <> (action_id IS NULL)"),
        _ck(t, "evidence_type", _in("evidence_type", EVIDENCE_TYPES)),
        _ck(t, "original_file_name", _text("original_file_name", 255)),
        _ck(t, "description", _text("description", 1000, optional=True)),
        _ck(t, "size_bytes", "size_bytes > 0"),
        _ck(t, "sha256", "sha256 ~ '^[0-9a-f]{64}$'"),
        _ck(t, "removal_reason", "(removed_at IS NULL) = (removal_reason IS NULL)"),
        schema=SAFETY,
    )
    op.create_index("ix_psm_attachments_recommendation_id", t, ["recommendation_id"], schema=SAFETY)
    op.create_index("ix_psm_attachments_action_id", t, ["action_id"], schema=SAFETY)
    _user_index(t, "uploaded_by_user_id")

    t = "psm_attachment_contents"
    op.create_table(
        t,
        sa.Column("attachment_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("attachment_id", name=op.f(f"pk_{t}")),
        _fk(t, "attachment_id", "psm_attachments.id"),
        schema=SAFETY,
    )

    t = "psm_notifications"
    op.create_table(
        t,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("action_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("recipient_name", sa.Text(), nullable=True),
        sa.Column("recipient_email", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        _now(),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        _fk(t, "action_id", "psm_actions.id"),
        _ck(t, "event_type", _in("event_type", NOTIFICATION_EVENTS)),
        _ck(t, "status", _in("status", NOTIFICATION_STATUSES)),
        _ck(t, "attempts", "attempts >= 0"),
        _ck(t, "sent_at", "status <> 'sent' OR sent_at IS NOT NULL"),
        schema=SAFETY,
    )
    op.create_index(
        "uq_psm_notifications_dedupe_key",
        t,
        ["dedupe_key"],
        unique=True,
        schema=SAFETY,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )
    op.create_index("ix_psm_notifications_status", t, ["status"], schema=SAFETY)
    op.create_index("ix_psm_notifications_action_id", t, ["action_id"], schema=SAFETY)

    t = "psm_notification_settings"
    op.create_table(
        t,
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("notify_on_assignment", sa.Boolean(), nullable=False),
        sa.Column("notify_on_due_date_change", sa.Boolean(), nullable=False),
        sa.Column("notify_on_status_change", sa.Boolean(), nullable=False),
        sa.Column("notify_on_comment", sa.Boolean(), nullable=False),
        sa.Column("due_soon_reminders", sa.Boolean(), nullable=False),
        sa.Column("overdue_reminders", sa.Boolean(), nullable=False),
        sa.Column("due_soon_days", sa.SmallInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        _ck(t, "single_row", "id = 1"),
        _ck(t, "due_soon_days", "due_soon_days BETWEEN 1 AND 90"),
        schema=SAFETY,
    )


def _name_key(name: str) -> str:
    return " ".join(name.split()).lower()


def _seed() -> None:
    op.bulk_insert(
        sa.table(
            "psm_study_types",
            sa.column("code", sa.Text),
            sa.column("name", sa.Text),
            sa.column("display_order", sa.Integer),
            schema=SAFETY,
        ),
        [{"code": "pha", "name": "PHA", "display_order": 1}],
    )
    op.bulk_insert(
        sa.table(
            "psm_departments",
            sa.column("name", sa.Text),
            sa.column("name_key", sa.Text),
            sa.column("display_order", sa.Integer),
            sa.column("created_by", sa.Text),
            sa.column("updated_by", sa.Text),
            schema=SAFETY,
        ),
        [
            {
                "name": name,
                "name_key": _name_key(name),
                "display_order": order,
                "created_by": "migration-0015",
                "updated_by": "migration-0015",
            }
            for order, name in enumerate(DEPARTMENTS, start=1)
        ],
    )
    op.bulk_insert(
        sa.table(
            "psm_elements",
            sa.column("code", sa.Text),
            sa.column("name", sa.Text),
            sa.column("regulation", sa.Text),
            sa.column("display_order", sa.Integer),
            schema=SAFETY,
        ),
        [
            {"code": code, "name": name, "regulation": regulation, "display_order": order}
            for order, (code, name, regulation) in enumerate(PSM_ELEMENTS, start=1)
        ],
    )
    op.bulk_insert(
        sa.table(
            "psm_notification_settings",
            sa.column("id", sa.SmallInteger),
            sa.column("notify_on_assignment", sa.Boolean),
            sa.column("notify_on_due_date_change", sa.Boolean),
            sa.column("notify_on_status_change", sa.Boolean),
            sa.column("notify_on_comment", sa.Boolean),
            sa.column("due_soon_reminders", sa.Boolean),
            sa.column("overdue_reminders", sa.Boolean),
            sa.column("due_soon_days", sa.SmallInteger),
            sa.column("updated_by", sa.Text),
            schema=SAFETY,
        ),
        [
            {
                "id": 1,
                "notify_on_assignment": True,
                "notify_on_due_date_change": True,
                "notify_on_status_change": True,
                "notify_on_comment": False,
                "due_soon_reminders": True,
                "overdue_reminders": True,
                "due_soon_days": 7,
                "updated_by": "migration-0015",
            }
        ],
    )


def _grant() -> None:
    op.bulk_insert(
        sa.table(
            "permissions",
            sa.column("code", sa.Text),
            sa.column("module", sa.Text),
            sa.column("description", sa.Text),
            schema=CORE,
        ),
        [
            {"code": code, "module": "psm", "description": f"{MODULE_LABEL}: {code.split('.', 1)[1]}"}
            for code in PERMISSIONS
        ],
    )
    code, name, description = NEW_ROLE
    op.bulk_insert(
        sa.table(
            "roles",
            sa.column("code", sa.Text),
            sa.column("name", sa.Text),
            sa.column("description", sa.Text),
            sa.column("is_system", sa.Boolean),
            schema=CORE,
        ),
        [{"code": code, "name": name, "description": description, "is_system": True}],
    )
    grants = [(role, permission) for role, codes in ROLE_GRANTS.items() for permission in codes]
    grants += [(code, permission) for permission in NEW_ROLE_PERMISSIONS]
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
    _create_reference_tables()
    _create_studies()
    _create_recommendations()
    _create_actions()
    _seed()
    _grant()


# Process Safety Management records and role assignments are never discarded by a downgrade.
DOWNGRADE_GUARD = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM {SAFETY}.psm_studies) THEN
            RAISE EXCEPTION 'Cannot downgrade: Process Safety Management studies exist';
        END IF;
        IF EXISTS (SELECT 1 FROM {CORE}.user_roles WHERE role_code = '{NEW_ROLE[0]}') THEN
            RAISE EXCEPTION 'Cannot downgrade: users hold the {NEW_ROLE[0]} role';
        END IF;
    END
    $$
"""


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_GUARD))
    codes = ", ".join(f"'{code}'" for code in PERMISSIONS)
    op.execute(sa.text(f"DELETE FROM {CORE}.role_permissions WHERE permission_code IN ({codes})"))
    op.execute(sa.text(f"DELETE FROM {CORE}.role_permissions WHERE role_code = '{NEW_ROLE[0]}'"))
    op.execute(sa.text(f"DELETE FROM {CORE}.roles WHERE code = '{NEW_ROLE[0]}'"))
    op.execute(sa.text(f"DELETE FROM {CORE}.permissions WHERE code IN ({codes})"))
    for table in (
        "psm_notification_settings",
        "psm_notifications",
        "psm_attachment_contents",
        "psm_attachments",
        "psm_action_updates",
        "psm_actions",
        "psm_scenarios",
        "psm_recommendations",
        "psm_study_areas",
        "psm_studies",
        "psm_elements",
        "psm_process_nodes",
        "psm_departments",
        "psm_study_types",
    ):
        op.drop_table(table, schema=SAFETY)
