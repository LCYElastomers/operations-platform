"""safety observations

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-07 10:30:00

Creates individual Safety Observation records and their categories, and seeds
the category definitions. Also seeds (definitions only, no values) the legacy
aggregate views of the 2026 EHS workbook as monthly metrics in the separate
metric set ``observations_legacy``. Those tallies are not observations and do
not reconcile with each other, so each view is kept as its own section.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFETY = "safety"
CATEGORIES = "observation_categories"
OBSERVATIONS = "observations"
METRIC_SECTIONS = "metric_sections"
METRIC_CATEGORIES = "metric_categories"
METRIC_VALUES = "monthly_metric_values"

# (code, display name) in display order. Names correct the workbook's spelling
# and spacing; the workbook's own labels belong in import mappings, not here.
# Fire and Fire System stay separate until the Safety owner confirms otherwise.
OBSERVATION_CATEGORIES: list[tuple[str, str]] = [
    ("building", "Building"),
    ("chemical", "Chemical"),
    ("confined_space", "Confined Space"),
    ("electrical", "Electrical"),
    ("ergonomics", "Ergonomics"),
    ("fire", "Fire"),
    ("fire_system", "Fire System"),
    ("forklift", "Forklift"),
    ("housekeeping", "Housekeeping"),
    ("loto", "LOTO"),
    ("material_defect", "Material Defect"),
    ("material_handling_lifting", "Material Handling or Lifting"),
    ("non_work_related", "Non-Work Related"),
    ("ppe", "PPE"),
    ("respiratory_protection", "Respiratory Protection"),
    ("slip_trip_fall", "Slip, Trip, Fall"),
    ("stairs_ladders", "Stairs, Ladders"),
    ("tools_equipment", "Tools & Equipment"),
    ("vehicle_company_owned", "Vehicle, Company Owned"),
    ("vehicle_not_company_owned", "Vehicle, Not Company Owned"),
    ("walking_working_surface", "Walking Working Surface"),
    ("work_at_elevation", "Work at Elevation"),
    ("crane", "Crane"),
]

LEGACY_METRIC_SET = "observations_legacy"
_SAFE_SHEET = [code for code, _ in OBSERVATION_CATEGORIES if code != "fire_system"]
_UNSAFE_SHEET = [code for code, _ in OBSERVATION_CATEGORIES if code != "fire"]
_NAMES = dict(OBSERVATION_CATEGORIES)

# The workbook's independent aggregate views (sheet "SSO-Site -25"), one section
# each. Category lists follow the sheet: the Safe table has "Fire", the Unsafe
# table "Fire system".
LEGACY_SECTIONS: list[tuple[str, str, list[tuple[str, str]]]] = [
    (
        "safe_by_category",
        "Safe Act / Condition by Category (legacy workbook)",
        [(code, _NAMES[code]) for code in _SAFE_SHEET],
    ),
    (
        "unsafe_by_category",
        "Unsafe Act / Condition by Category (legacy workbook)",
        [(code, _NAMES[code]) for code in _UNSAFE_SHEET],
    ),
    (
        "act_condition",
        "Act / Condition (legacy workbook)",
        [
            ("safe_act", "Safe Act"),
            ("safe_condition", "Safe Condition"),
            ("unsafe_act", "Unsafe Act"),
            ("unsafe_condition", "Unsafe Condition"),
        ],
    ),
    (
        "total_observations",
        "Total Observations (legacy workbook)",
        [("total_observations", "Total Observations")],
    ),
]


def _seed_categories() -> None:
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
            for order, (code, name) in enumerate(OBSERVATION_CATEGORIES, start=1)
        ],
    )


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


def _optional_text_check(column: str, max_length: int) -> sa.CheckConstraint:
    return sa.CheckConstraint(
        f"{column} IS NULL OR (btrim({column}) <> '' AND char_length({column}) <= {max_length})",
        name=op.f(f"ck_{OBSERVATIONS}_{column}"),
    )


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
        sa.PrimaryKeyConstraint("id", name="pk_observation_categories"),
        sa.UniqueConstraint("code", name="uq_observation_categories_code"),
        schema=SAFETY,
    )
    op.create_table(
        OBSERVATIONS,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("area_location", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("corrective_action", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_observations"),
        sa.ForeignKeyConstraint(
            ["category_id"], [f"{SAFETY}.{CATEGORIES}.id"], name="fk_observations_category"
        ),
        # op.f(): the name is final; the "ck" naming convention must not prefix it again.
        sa.CheckConstraint(
            "outcome IN ('safe', 'unsafe')", name=op.f("ck_observations_outcome")
        ),
        sa.CheckConstraint("kind IN ('act', 'condition')", name=op.f("ck_observations_kind")),
        sa.CheckConstraint(
            "observed_on >= DATE '2000-01-01'", name=op.f("ck_observations_observed_on")
        ),
        _optional_text_check("area_location", 200),
        _optional_text_check("description", 2000),
        _optional_text_check("corrective_action", 2000),
        schema=SAFETY,
    )
    op.create_index("ix_observations_observed_on", OBSERVATIONS, ["observed_on"], schema=SAFETY)
    op.create_index("ix_observations_category_id", OBSERVATIONS, ["category_id"], schema=SAFETY)

    _seed_categories()
    _seed_legacy_definitions()


def downgrade() -> None:
    # Entered observations and imported legacy values would be lost.
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM {SAFETY}.{OBSERVATIONS}) THEN
                    RAISE EXCEPTION 'Cannot downgrade: safety observations exist';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM {SAFETY}.{METRIC_VALUES} v
                    JOIN {SAFETY}.{METRIC_CATEGORIES} c ON c.id = v.category_id
                    JOIN {SAFETY}.{METRIC_SECTIONS} s ON s.id = c.section_id
                    WHERE s.metric_set = '{LEGACY_METRIC_SET}'
                ) THEN
                    RAISE EXCEPTION 'Cannot downgrade: legacy observation values exist';
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
    op.drop_index("ix_observations_category_id", table_name=OBSERVATIONS, schema=SAFETY)
    op.drop_index("ix_observations_observed_on", table_name=OBSERVATIONS, schema=SAFETY)
    op.drop_table(OBSERVATIONS, schema=SAFETY)
    op.drop_table(CATEGORIES, schema=SAFETY)
