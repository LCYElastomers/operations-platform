"""safety performance

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-07 15:30:00

Creates monthly worked hours (``safety.performance_hours``) and pre-platform
annual history (``safety.performance_annual_legacy``) for Safety Performance
rates, and seeds (definitions only, no values) the ``performance_legacy``
monthly metric set that holds pre-2026 workbook event counts.

Seeds no hours, counts, rates or targets. Historical data is loaded only by the
reviewed import tooling, never by this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFETY = "safety"
HOURS = "performance_hours"
ANNUAL = "performance_annual_legacy"
METRIC_SECTIONS = "metric_sections"
METRIC_CATEGORIES = "metric_categories"
METRIC_VALUES = "monthly_metric_values"

LEGACY_METRIC_SET = "performance_legacy"
# One category per rate numerator. The pre-2026 workbook has a single combined
# Property & Equipment Damage count, not separate property and equipment counts.
LEGACY_SECTIONS: list[tuple[str, str, list[tuple[str, str]]]] = [
    (
        "recordable",
        "Recordable Injuries & Illnesses (legacy workbook)",
        [("recordable", "Recordable Injuries & Illnesses")],
    ),
    ("first_aid", "First Aid (legacy workbook)", [("first_aid", "First Aid")]),
    (
        "lopc",
        "Loss of Primary Containment (LOPC) (legacy workbook)",
        [("lopc", "Loss of Primary Containment (LOPC)")],
    ),
    (
        "property_equipment_damage",
        "Property & Equipment Damage (legacy workbook)",
        [("property_equipment_damage", "Property & Equipment Damage")],
    ),
]


def _audit_columns() -> list[sa.Column]:
    return [
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
    ]


def _seed_legacy_definitions() -> None:
    sections = sa.table(
        METRIC_SECTIONS,
        sa.column("id", sa.Integer),
        sa.column("metric_set", sa.Text),
        sa.column("code", sa.Text),
        sa.column("name", sa.Text),
        sa.column("display_order", sa.Integer),
        schema=SAFETY,
    )
    categories = sa.table(
        METRIC_CATEGORIES,
        sa.column("section_id", sa.Integer),
        sa.column("code", sa.Text),
        sa.column("name", sa.Text),
        sa.column("display_order", sa.Integer),
        schema=SAFETY,
    )
    op.bulk_insert(
        sections,
        [
            {"metric_set": LEGACY_METRIC_SET, "code": code, "name": name, "display_order": order}
            for order, (code, name, _) in enumerate(LEGACY_SECTIONS, start=1)
        ],
    )
    for section_code, _, section_categories in LEGACY_SECTIONS:
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
                        sections.c.metric_set == LEGACY_METRIC_SET,
                        sections.c.code == section_code,
                    ),
                )
            )


def upgrade() -> None:
    op.create_table(
        HOURS,
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("reporting_year", sa.SmallInteger(), nullable=False),
        sa.Column("reporting_month", sa.SmallInteger(), nullable=False),
        sa.Column("total_hours", sa.Numeric(10, 2), nullable=False),
        sa.Column("hourly_hours", sa.Numeric(10, 2), nullable=True),
        sa.Column("salary_hours", sa.Numeric(10, 2), nullable=True),
        sa.Column("month_closed", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_performance_hours"),
        sa.UniqueConstraint(
            "reporting_year", "reporting_month", name="uq_performance_hours_year_month"
        ),
        # op.f(): the name is final; the "ck" naming convention must not prefix it again.
        sa.CheckConstraint(
            "reporting_year BETWEEN 2000 AND 2100",
            name=op.f("ck_performance_hours_reporting_year"),
        ),
        sa.CheckConstraint(
            "reporting_month BETWEEN 1 AND 12",
            name=op.f("ck_performance_hours_reporting_month"),
        ),
        sa.CheckConstraint("total_hours >= 0", name=op.f("ck_performance_hours_total_hours")),
        sa.CheckConstraint(
            "hourly_hours IS NULL OR hourly_hours >= 0",
            name=op.f("ck_performance_hours_hourly_hours"),
        ),
        sa.CheckConstraint(
            "salary_hours IS NULL OR salary_hours >= 0",
            name=op.f("ck_performance_hours_salary_hours"),
        ),
        sa.CheckConstraint(
            "hourly_hours IS NULL OR salary_hours IS NULL "
            "OR hourly_hours + salary_hours = total_hours",
            name=op.f("ck_performance_hours_breakdown_total"),
        ),
        schema=SAFETY,
    )

    op.create_table(
        ANNUAL,
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("reporting_year", sa.SmallInteger(), nullable=False),
        sa.Column("recordables", sa.Integer(), nullable=False),
        sa.Column("total_hours", sa.Numeric(10, 2), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_performance_annual_legacy"),
        sa.UniqueConstraint("reporting_year", name="uq_performance_annual_legacy_reporting_year"),
        sa.CheckConstraint(
            "reporting_year BETWEEN 2000 AND 2100",
            name=op.f("ck_performance_annual_legacy_reporting_year"),
        ),
        sa.CheckConstraint(
            "recordables >= 0", name=op.f("ck_performance_annual_legacy_recordables")
        ),
        sa.CheckConstraint(
            "total_hours > 0", name=op.f("ck_performance_annual_legacy_total_hours")
        ),
        sa.CheckConstraint(
            "source = btrim(source) AND source <> '' AND char_length(source) <= 500",
            name=op.f("ck_performance_annual_legacy_source"),
        ),
        schema=SAFETY,
    )

    _seed_legacy_definitions()


def downgrade() -> None:
    # Entered hours, closed months and imported history would be lost.
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM {SAFETY}.{HOURS}) THEN
                    RAISE EXCEPTION 'Cannot downgrade: safety performance hours exist';
                END IF;
                IF EXISTS (SELECT 1 FROM {SAFETY}.{ANNUAL}) THEN
                    RAISE EXCEPTION 'Cannot downgrade: legacy annual performance rows exist';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM {SAFETY}.{METRIC_VALUES} v
                    JOIN {SAFETY}.{METRIC_CATEGORIES} c ON c.id = v.category_id
                    JOIN {SAFETY}.{METRIC_SECTIONS} s ON s.id = c.section_id
                    WHERE s.metric_set = '{LEGACY_METRIC_SET}'
                ) THEN
                    RAISE EXCEPTION 'Cannot downgrade: legacy performance values exist';
                END IF;
            END
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            DELETE FROM {SAFETY}.{METRIC_CATEGORIES}
            WHERE section_id IN (
                SELECT id FROM {SAFETY}.{METRIC_SECTIONS} WHERE metric_set = '{LEGACY_METRIC_SET}'
            )
            """
        )
    )
    op.execute(
        sa.text(
            f"DELETE FROM {SAFETY}.{METRIC_SECTIONS} WHERE metric_set = '{LEGACY_METRIC_SET}'"
        )
    )
    op.drop_table(ANNUAL, schema=SAFETY)
    op.drop_table(HOURS, schema=SAFETY)
