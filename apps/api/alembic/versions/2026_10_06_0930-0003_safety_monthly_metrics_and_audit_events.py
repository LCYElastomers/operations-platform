"""platform audit events and safety monthly metrics

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06 09:30:00

Seeds the Incident & Near Miss section and category definitions only. No
metric values are seeded; historical values are loaded separately with
``python -m app.safety.legacy_import``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CORE = "core"
SAFETY = "safety"
AUDIT_EVENTS = "audit_events"
SECTIONS = "metric_sections"
CATEGORIES = "metric_categories"
VALUES = "monthly_metric_values"

INCIDENTS = "incidents"

# (section code, section name, [(category code, category name), ...]) in display order.
# Incident and Near Miss totals are explicit source metrics. Incident Classification
# is a separate breakdown whose categories are not mutually exclusive, so it is
# never summed into the Incident total. Single-category blocks hold the block's
# monthly count until the workbook's row breakdown for that block is confirmed.
INCIDENT_SECTIONS: list[tuple[str, str, list[tuple[str, str]]]] = [
    (
        "incident_near_miss_totals",
        "Incident & Near Miss Totals",
        [("near_miss", "Near Miss"), ("incident", "Incident")],
    ),
    (
        "incident_classification",
        "Incident Classification",
        [
            ("first_aid", "First Aid"),
            ("recordable_injury", "Recordable Injury"),
            ("lost_time_injury", "Lost Time Injury"),
            ("restricted", "Restricted"),
            ("occupational_illness", "Occupational Illness"),
            ("hazardous_condition", "Hazardous Condition"),
            ("spill_release", "Spill / Release"),
            ("fire", "Fire"),
            ("pit_accident", "PIT Accident"),
            ("property_damage", "Property Damage"),
            ("equipment_damage_failure", "Equipment Damage / Failure"),
            ("non_work_related", "Non-Work Related"),
            ("regulatory", "Regulatory"),
        ],
    ),
    ("lopc", "LOPC", [("lopc", "LOPC")]),
    (
        "property_equipment_damage",
        "Property / Equipment Damage",
        [("property_equipment_damage", "Property / Equipment Damage")],
    ),
    ("pit", "PIT", [("pit", "PIT")]),
    ("psif", "PSIF", [("psif", "PSIF")]),
]


def _seed_incident_definitions() -> None:
    sections = sa.table(
        SECTIONS,
        sa.column("id", sa.Integer),
        sa.column("metric_set", sa.Text),
        sa.column("code", sa.Text),
        sa.column("name", sa.Text),
        sa.column("display_order", sa.Integer),
        schema=SAFETY,
    )
    categories = sa.table(
        CATEGORIES,
        sa.column("section_id", sa.Integer),
        sa.column("code", sa.Text),
        sa.column("name", sa.Text),
        sa.column("display_order", sa.Integer),
        schema=SAFETY,
    )
    op.bulk_insert(
        sections,
        [
            {"metric_set": INCIDENTS, "code": code, "name": name, "display_order": order}
            for order, (code, name, _) in enumerate(INCIDENT_SECTIONS, start=1)
        ],
    )
    for section_code, _, section_categories in INCIDENT_SECTIONS:
        for order, (code, name) in enumerate(section_categories, start=1):
            op.execute(
                categories.insert().from_select(
                    ["section_id", "code", "name", "display_order"],
                    sa.select(
                        sections.c.id,
                        sa.literal(code, sa.Text),
                        sa.literal(name, sa.Text),
                        sa.literal(order, sa.Integer),
                    ).where(
                        sections.c.metric_set == INCIDENTS,
                        sections.c.code == section_code,
                    ),
                )
            )


def upgrade() -> None:
    op.create_table(
        AUDIT_EVENTS,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("change_set_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_key", sa.Text(), nullable=False),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        # op.f(): the name is final; the "ck" naming convention must not prefix it again.
        sa.CheckConstraint(
            "action IN ('create', 'update', 'delete')", name=op.f("ck_audit_events_action")
        ),
        schema=CORE,
    )
    op.create_index(
        "ix_audit_events_entity",
        AUDIT_EVENTS,
        ["entity_type", "entity_key", sa.text("occurred_at DESC")],
        schema=CORE,
    )
    op.create_index(
        "ix_audit_events_occurred_at_desc",
        AUDIT_EVENTS,
        [sa.text("occurred_at DESC")],
        schema=CORE,
    )

    # Only create the schema when missing, so a DBA can pre-create it for a
    # role that lacks CREATE on the database.
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = '{SAFETY}') THEN
                    CREATE SCHEMA {SAFETY};
                END IF;
            END
            $$
            """
        )
    )

    op.create_table(
        SECTIONS,
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("metric_set", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_metric_sections"),
        sa.UniqueConstraint("metric_set", "code", name="uq_metric_sections_metric_set_code"),
        schema=SAFETY,
    )
    op.create_table(
        CATEGORIES,
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("section_id", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_metric_categories"),
        sa.ForeignKeyConstraint(
            ["section_id"], [f"{SAFETY}.{SECTIONS}.id"], name="fk_metric_categories_section"
        ),
        sa.UniqueConstraint("section_id", "code", name="uq_metric_categories_section_id_code"),
        schema=SAFETY,
    )
    op.create_table(
        VALUES,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("reporting_year", sa.SmallInteger(), nullable=False),
        sa.Column("reporting_month", sa.SmallInteger(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_monthly_metric_values"),
        sa.ForeignKeyConstraint(
            ["category_id"],
            [f"{SAFETY}.{CATEGORIES}.id"],
            name="fk_monthly_metric_values_category",
        ),
        sa.UniqueConstraint(
            "category_id",
            "reporting_year",
            "reporting_month",
            name="uq_monthly_metric_values_category_year_month",
        ),
        sa.CheckConstraint(
            "reporting_month BETWEEN 1 AND 12",
            name=op.f("ck_monthly_metric_values_reporting_month"),
        ),
        sa.CheckConstraint(
            "reporting_year BETWEEN 2000 AND 2100",
            name=op.f("ck_monthly_metric_values_reporting_year"),
        ),
        sa.CheckConstraint(
            "value >= 0", name=op.f("ck_monthly_metric_values_value_non_negative")
        ),
        schema=SAFETY,
    )

    _seed_incident_definitions()


def downgrade() -> None:
    # Entered Safety values and audit history would be lost.
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM {SAFETY}.{VALUES}) THEN
                    RAISE EXCEPTION 'Cannot downgrade: safety monthly metric values exist';
                END IF;
                IF EXISTS (SELECT 1 FROM {CORE}.{AUDIT_EVENTS}) THEN
                    RAISE EXCEPTION 'Cannot downgrade: audit events exist';
                END IF;
            END
            $$
            """
        )
    )
    op.drop_table(VALUES, schema=SAFETY)
    op.drop_table(CATEGORIES, schema=SAFETY)
    op.drop_table(SECTIONS, schema=SAFETY)

    # Drop the schema only if this role owns it and nothing else lives in it.
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_namespace n
                    WHERE n.nspname = '{SAFETY}'
                      AND pg_get_userbyid(n.nspowner) = current_user
                ) AND NOT EXISTS (
                    SELECT 1 FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = '{SAFETY}'
                ) THEN
                    DROP SCHEMA {SAFETY};
                END IF;
            END
            $$
            """
        )
    )

    op.drop_index("ix_audit_events_occurred_at_desc", table_name=AUDIT_EVENTS, schema=CORE)
    op.drop_index("ix_audit_events_entity", table_name=AUDIT_EVENTS, schema=CORE)
    op.drop_table(AUDIT_EVENTS, schema=CORE)
