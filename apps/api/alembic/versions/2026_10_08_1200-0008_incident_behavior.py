"""incident behavior

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-08 12:00:00

Adds annual Behavior tagging for Incident & Near Miss:

- ``safety.behavior_categories``: the Behavior taxonomy of the 2026 LCY EHS
  workbook ('Behavior'!A4:A27), all 24 categories in source order.
- ``safety.annual_behavior_counts``: one row per (category, reporting year).
  The workbook records Behavior only as annual category totals, so there is
  no month column: no month is ever invented and an annual value is never
  copied into months. A missing row is unreported, distinct from a stored 0.

Behavior values are tags: one incident may carry several, so their total is
not required to equal the Incident total. The denominator (Incident reports)
is read from the stored monthly Incident total and never stored here.

Annual counts are a stopgap until incidents are recorded as events; the
counts table can then be retired without touching the taxonomy or the
monthly metrics.

Seeds definitions only. Historical counts are loaded with
``python -m app.safety.behavior.legacy_import`` from a reviewed mapping.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFETY = "safety"
CATEGORIES = "behavior_categories"
COUNTS = "annual_behavior_counts"

# (code, display name) in source order, 'Behavior'!A4:A27. Display names keep the
# workbook labels; only 'PPE Respiritory' (A20) is respelled and the trailing space
# of 'Pushing & Pulling ' (A24) trimmed. The mapping file keeps the source labels.
BEHAVIOR_CATEGORIES: list[tuple[str, str]] = [
    ("pre_post_job_inspection", "Pre & Post Job Inspection"),
    ("communications_of_hazards", "Communications Of Hazards"),
    ("eyes_on_path", "Eyes On Path"),
    ("knowledge_of_task", "Knowledge of Task"),
    ("line_of_fire", "Line Of Fire"),
    ("pinch_points", "Pinch Points"),
    ("energy_isolation", "Energy Isolation"),
    ("get_assistance", "Get Assistance"),
    ("housekeeping", "Housekeeping"),
    ("walking_working_surfaces", "Walking & Working Surfaces"),
    ("ppe_eye", "PPE Eye"),
    ("ppe_hands", "PPE Hands"),
    ("eyes_on_task", "Eyes On Task"),
    ("hot_work", "Hot work"),
    ("tool_equipment_selection", "Tool Equipment Selection"),
    ("ascending_descending", "Ascending / Descending"),
    ("ppe_respiratory", "PPE Respiratory"),
    ("tool_use", "Tool Use"),
    ("lifting_lowering", "Lifting & Lowering"),
    ("twisting", "Twisting"),
    ("pushing_pulling", "Pushing & Pulling"),
    ("ppe_body", "PPE Body"),
    ("temp_extreme", "Temp Extreme"),
    ("confined_space", "Confined Space"),
]


def upgrade() -> None:
    op.create_table(
        CATEGORIES,
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_behavior_categories"),
        sa.UniqueConstraint("code", name="uq_behavior_categories_code"),
        # op.f(): the name is final; the "ck" naming convention must not prefix it again.
        sa.CheckConstraint(
            "code ~ '^[a-z0-9_]{1,100}$'", name=op.f("ck_behavior_categories_code")
        ),
        sa.CheckConstraint(
            "name = btrim(name) AND name <> '' AND char_length(name) <= 200",
            name=op.f("ck_behavior_categories_name"),
        ),
        schema=SAFETY,
    )
    op.create_table(
        COUNTS,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("reporting_year", sa.SmallInteger(), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_annual_behavior_counts"),
        sa.ForeignKeyConstraint(
            ["category_id"],
            [f"{SAFETY}.{CATEGORIES}.id"],
            name="fk_annual_behavior_counts_category",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "category_id", "reporting_year", name="uq_annual_behavior_counts_category_year"
        ),
        sa.CheckConstraint(
            "reporting_year BETWEEN 2000 AND 2100",
            name=op.f("ck_annual_behavior_counts_reporting_year"),
        ),
        sa.CheckConstraint("value >= 0", name=op.f("ck_annual_behavior_counts_value_non_negative")),
        schema=SAFETY,
    )

    categories = sa.table(
        CATEGORIES,
        sa.column("code", sa.Text),
        sa.column("name", sa.Text),
        sa.column("display_order", sa.Integer),
        schema=SAFETY,
    )
    op.bulk_insert(
        categories,
        [
            {"code": code, "name": name, "display_order": order}
            for order, (code, name) in enumerate(BEHAVIOR_CATEGORIES, start=1)
        ],
    )


# Entered or imported Behavior counts would be lost by a downgrade.
DOWNGRADE_GUARD = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM {SAFETY}.{COUNTS}) THEN
            RAISE EXCEPTION 'Cannot downgrade: Behavior counts exist';
        END IF;
    END
    $$
"""


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_GUARD))
    op.drop_table(COUNTS, schema=SAFETY)
    op.drop_table(CATEGORIES, schema=SAFETY)
