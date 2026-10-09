"""quality corrective action reports

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-09 17:00:00

Schema only; seeds nothing and changes no existing table.

- ``quality.cars``: Corrective Action Reports, structured by the sections of
  form QMS-006-1 Rev. 2. Days open, past due, cost totals and progress are
  calculated by the API, never stored. An optional link to one Quality Cost
  record.
- ``quality.car_actions``: the corrective actions of a report.
- ``quality.car_why_steps``: the Why-Why worksheet rows.
- ``quality.car_approvals``: approvals recorded on a report (name and date).
- ``quality.car_references``: links from a report to other records or documents.

Historical CAR workbooks are imported by ``python -m app.quality.car.legacy_import``,
never by this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUALITY = "quality"
CARS = "cars"
ACTIONS = "car_actions"
WHY_STEPS = "car_why_steps"
APPROVALS = "car_approvals"
REFERENCES = "car_references"

PRODUCTION_COLUMNS = ("product", "campaign", "lot", "location", "counterparty")
WHY_HEADER_TEXT_COLUMNS = (
    "complaint_number",
    "dr_number",
    "material_name",
    "po_number",
    "supplier",
    "production_lot",
    "quantity_affected",
)
SHORT_TEXT_COLUMNS = (
    "requested_by",
    "assigned_to",
    "closure_approved_by",
    "previous_car",
    "containment_owner",
    "disposition_other",
    "incident_type",
    "equipment_involved",
    "work_order_number",
    "reviewer",
    "follow_up_reference",
    *PRODUCTION_COLUMNS,
    *WHY_HEADER_TEXT_COLUMNS,
)
LONG_TEXT_COLUMNS = (
    "nonconformity_description",
    "objective_evidence",
    "immediate_actions",
    "investigation_summary",
    "true_root_cause",
    "similar_nonconformities",
    "procedures_revised",
    "supporting_documents",
    "success_criteria",
    "effectiveness_evidence",
    "migration_notes",
)
CODE_COLUMNS = ("source_code", "department_code", "root_cause_code")
MONEY_COLUMNS = ("material_loss", "production_time_loss", "other_costs")
WHY_TEXT_COLUMNS = ("what", "why", "root_cause", "countermeasure", "who")
APPROVAL_FUNCTIONS = (
    "quality",
    "department_supervisor",
    "safety_environmental",
    "operations_maintenance",
    "engineering",
    "process_manager",
)


def _optional_text(column: str, length: int) -> str:
    return f"{column} IS NULL OR (btrim({column}) <> '' AND char_length({column}) <= {length})"


def _check(table: str, name: str, condition: str) -> sa.CheckConstraint:
    # op.f(): the names are final; the "ck" naming convention must not prefix them again.
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _audit_columns(*, updated: bool = True) -> list[sa.Column]:
    columns = [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
    ]
    if updated:
        columns += [
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("updated_by", sa.Text(), nullable=False),
        ]
    return columns


def _car_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["car_id"], [f"{QUALITY}.{CARS}.id"], name=f"fk_{table}_car", ondelete="RESTRICT"
    )


def _text(*columns: str) -> list[sa.Column]:
    return [sa.Column(column, sa.Text(), nullable=True) for column in columns]


def _dates(*columns: str) -> list[sa.Column]:
    return [sa.Column(column, sa.Date(), nullable=True) for column in columns]


def _flags(*columns: str) -> list[sa.Column]:
    return [sa.Column(column, sa.Boolean(), nullable=True) for column in columns]


def upgrade() -> None:
    op.create_table(
        CARS,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("car_number", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        *_text("requested_by"),
        sa.Column("request_date", sa.Date(), nullable=False),
        *_text("assigned_to"),
        *_dates("due_date"),
        *_text("status"),
        *_dates("date_closed"),
        *_text("closure_approved_by", "source_code", "department_code"),
        *_dates("started_on"),
        sa.Column("started_time", sa.Time(), nullable=True),
        *_dates("ended_on"),
        sa.Column("ended_time", sa.Time(), nullable=True),
        *_flags("previous_occurrence"),
        *_text(
            "previous_car",
            "nonconformity_description",
            "objective_evidence",
            "immediate_actions",
            "containment_owner",
        ),
        *_dates("containment_completed_on"),
        sa.Column(
            "disposition_codes",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        *_text("disposition_other"),
        *_flags("safety_hazard", "environmental_hazard", "customer_impact"),
        *_text(
            "incident_type",
            "root_cause_code",
            "equipment_involved",
            "work_order_number",
            "investigation_summary",
            "true_root_cause",
            "similar_nonconformities",
        ),
        *_flags("similar_issue_found", "additional_action_required"),
        *_text("procedures_revised"),
        *_flags("training_completed"),
        *_text("supporting_documents"),
        *_dates("plan_completed_on"),
        *_text("success_criteria", "effectiveness_evidence", "reviewer"),
        *_dates("review_date"),
        *_text("effectiveness_result", "follow_up_reference"),
        *(sa.Column(column, sa.Numeric(), nullable=True) for column in MONEY_COLUMNS),
        sa.Column("quality_cost_record_id", sa.BigInteger(), nullable=True),
        *_text(*PRODUCTION_COLUMNS, "complaint_number"),
        *_dates("date_reported"),
        *_text("dr_number", "material_name", "po_number", "supplier"),
        *_dates("date_delivered"),
        *_text("production_lot", "quantity_affected"),
        sa.Column("legacy_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *_text("migration_notes"),
        sa.Column("source", sa.Text(), server_default=sa.text("'manual'"), nullable=False),
        *_text("source_key", "source_reference"),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_cars"),
        sa.ForeignKeyConstraint(
            ["quality_cost_record_id"],
            [f"{QUALITY}.cost_records.id"],
            name="fk_cars_quality_cost_record",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("car_number", name="uq_cars_car_number"),
        _check(CARS, "car_number", "car_number ~ '^[A-Z]{1,5}-[0-9]{4}-[0-9]{3,6}$'"),
        _check(CARS, "subject", "btrim(subject) <> '' AND char_length(subject) <= 200"),
        _check(
            CARS, "request_date", "request_date BETWEEN DATE '2000-01-01' AND DATE '2100-12-31'"
        ),
        _check(CARS, "status", "status IS NULL OR status IN ('open', 'closed')"),
        _check(CARS, "status_required", "status IS NOT NULL OR source = 'legacy_import'"),
        _check(
            CARS,
            "closed_has_date",
            "(status = 'closed') = (date_closed IS NOT NULL) "
            "OR (status IS NULL AND date_closed IS NULL)",
        ),
        _check(
            CARS, "date_closed_after_request", "date_closed IS NULL OR date_closed >= request_date"
        ),
        _check(
            CARS,
            "effectiveness_result",
            "effectiveness_result IS NULL "
            "OR effectiveness_result IN ('effective', 'not_effective')",
        ),
        *(_check(CARS, c, f"{c} IS NULL OR {c} ~ '^[a-z_]+$'") for c in CODE_COLUMNS),
        _check(
            CARS,
            "disposition_codes",
            "array_position(disposition_codes, NULL) IS NULL "
            "AND array_to_string(disposition_codes, ',') ~ '^([a-z_]+(,[a-z_]+)*)?$'",
        ),
        *(_check(CARS, c, _optional_text(c, 200)) for c in SHORT_TEXT_COLUMNS),
        *(_check(CARS, c, _optional_text(c, 8000)) for c in LONG_TEXT_COLUMNS),
        *(_check(CARS, c, f"{c} >= 0") for c in MONEY_COLUMNS),
        _check(CARS, "source", "source IN ('manual', 'legacy_import')"),
        _check(
            CARS,
            "source_key",
            "source_key IS NULL OR (btrim(source_key) <> '' AND char_length(source_key) <= 200)",
        ),
        _check(CARS, "version", "version >= 1"),
        schema=QUALITY,
    )
    op.create_index(
        "uq_cars_source_key",
        CARS,
        ["source_key"],
        unique=True,
        schema=QUALITY,
        postgresql_where=sa.text("source_key IS NOT NULL"),
    )
    op.create_index(
        "uq_cars_quality_cost_record_id",
        CARS,
        ["quality_cost_record_id"],
        unique=True,
        schema=QUALITY,
        postgresql_where=sa.text("quality_cost_record_id IS NOT NULL"),
    )
    op.create_index("ix_cars_request_date", CARS, ["request_date"], schema=QUALITY)
    op.create_index("ix_cars_status_due_date", CARS, ["status", "due_date"], schema=QUALITY)

    op.create_table(
        ACTIONS,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("car_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        *_text("owner"),
        *_dates("target_date"),
        *_text("status"),
        *_dates("completed_on"),
        *_text("procedures_revised"),
        *_flags("training_completed"),
        *_text("supporting_documents"),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_car_actions"),
        _car_fk(ACTIONS),
        _check(ACTIONS, "action", "btrim(action) <> '' AND char_length(action) <= 8000"),
        _check(
            ACTIONS,
            "status",
            "status IS NULL OR status IN ('open', 'in_progress', 'complete', 'on_hold')",
        ),
        _check(ACTIONS, "completed_on", "completed_on IS NULL OR status = 'complete'"),
        _check(ACTIONS, "position", "position >= 1"),
        _check(ACTIONS, "owner", _optional_text("owner", 200)),
        _check(ACTIONS, "procedures_revised", _optional_text("procedures_revised", 8000)),
        _check(ACTIONS, "supporting_documents", _optional_text("supporting_documents", 8000)),
        _check(ACTIONS, "version", "version >= 1"),
        schema=QUALITY,
    )
    op.create_index("ix_car_actions_car_id", ACTIONS, ["car_id"], schema=QUALITY)

    op.create_table(
        WHY_STEPS,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("car_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        *_text(*WHY_TEXT_COLUMNS),
        *_dates("target_date"),
        *_audit_columns(updated=False),
        sa.PrimaryKeyConstraint("id", name="pk_car_why_steps"),
        _car_fk(WHY_STEPS),
        sa.UniqueConstraint("car_id", "position", name="uq_car_why_steps_car_id_position"),
        _check(WHY_STEPS, "position", "position >= 1"),
        *(_check(WHY_STEPS, c, _optional_text(c, 8000)) for c in WHY_TEXT_COLUMNS),
        schema=QUALITY,
    )

    op.create_table(
        APPROVALS,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("car_id", sa.BigInteger(), nullable=False),
        sa.Column("function_code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        *_dates("approved_on"),
        *_audit_columns(updated=False),
        sa.PrimaryKeyConstraint("id", name="pk_car_approvals"),
        _car_fk(APPROVALS),
        sa.UniqueConstraint(
            "car_id", "function_code", name="uq_car_approvals_car_id_function_code"
        ),
        _check(
            APPROVALS,
            "function_code",
            f"function_code IN ({', '.join(repr(f) for f in APPROVAL_FUNCTIONS)})",
        ),
        _check(APPROVALS, "name", "btrim(name) <> '' AND char_length(name) <= 200"),
        schema=QUALITY,
    )

    op.create_table(
        REFERENCES,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("car_id", sa.BigInteger(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_key", sa.Text(), nullable=False),
        *_text("label"),
        *_audit_columns(updated=False),
        sa.PrimaryKeyConstraint("id", name="pk_car_references"),
        _car_fk(REFERENCES),
        sa.UniqueConstraint(
            "car_id",
            "target_type",
            "target_key",
            name="uq_car_references_car_id_target_type_target_key",
        ),
        _check(REFERENCES, "target_type", "target_type ~ '^[a-z_]+$'"),
        _check(
            REFERENCES, "target_key", "btrim(target_key) <> '' AND char_length(target_key) <= 200"
        ),
        _check(REFERENCES, "label", _optional_text("label", 200)),
        schema=QUALITY,
    )
    op.create_index(
        "ix_car_references_target", REFERENCES, ["target_type", "target_key"], schema=QUALITY
    )


# Corrective Action Reports would be lost by a downgrade.
DOWNGRADE_GUARD = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM {QUALITY}.{CARS}) THEN
            RAISE EXCEPTION 'Cannot downgrade: Corrective Action Reports exist';
        END IF;
    END
    $$
"""


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_GUARD))
    op.drop_table(REFERENCES, schema=QUALITY)
    op.drop_table(APPROVALS, schema=QUALITY)
    op.drop_table(WHY_STEPS, schema=QUALITY)
    op.drop_table(ACTIONS, schema=QUALITY)
    op.drop_table(CARS, schema=QUALITY)
