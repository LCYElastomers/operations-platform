"""official safety observation categories

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-12 10:00:00

Replaces the Safety Observation categories offered for new entries with the
official list, in its alphabetical order. ``safety.observation_categories``
stays the single source of truth; the API offers only active categories.

Nothing is rewritten:

- Observations are not touched. Each keeps the category it was entered with,
  and its stored name, even when that category is no longer offered.
- Categories that are not on the official list are retired (``active = false``)
  and sorted after the official ones; their codes and names are unchanged.
  No old category is mapped to a new one (e.g. "Forklift" is not turned into
  "Powered Industrial Trucks", "PPE" not into "Personal Protective Equipment").
- Official categories whose code and name already exist (Building, Electrical,
  Ergonomics, Housekeeping, Tools & Equipment) keep their row, so their
  observations count under the official category.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFETY = "safety"
CATEGORIES = "observation_categories"
OBSERVATIONS = "observations"

# (code, label) in display order. Labels exactly as issued by the Safety owner.
OFFICIAL_CATEGORIES: list[tuple[str, str]] = [
    ("awareness_focus", "Awareness and Focus"),
    ("building", "Building"),
    ("contractors", "Contractors"),
    ("crane_hoist", "Crane and Hoist"),
    ("cryogenics_bulk_gases", "Cryogenics and Bulk Gases"),
    ("dot_hazmat_transportation", "DOT Hazardous Material Transportation"),
    ("driving", "Driving"),
    ("electrical", "Electrical"),
    ("environmental", "Environmental"),
    ("ergonomics", "Ergonomics"),
    ("fall_protection", "Fall Protection"),
    ("fire_safety", "Fire Safety"),
    ("first_aid", "First Aid"),
    ("guarding", "Guarding"),
    ("hazard_communications", "Hazard Communications"),
    ("hot_work", "Hot Work"),
    ("housekeeping", "Housekeeping"),
    ("lockout_tagout", "Lockout Tagout"),
    ("material_handling", "Material Handling"),
    ("personal_protective_equipment", "Personal Protective Equipment"),
    ("policies_procedures", "Policies and Procedures"),
    ("powered_industrial_trucks", "Powered Industrial Trucks"),
    ("security_incident", "Security Incident"),
    ("storage", "Storage"),
    ("tools_equipment", "Tools & Equipment"),
    ("training", "Training"),
]

# The categories seeded by 0004, in their order; restored on downgrade.
PREVIOUS_CATEGORIES: list[str] = [
    "building",
    "chemical",
    "confined_space",
    "electrical",
    "ergonomics",
    "fire",
    "fire_system",
    "forklift",
    "housekeeping",
    "loto",
    "material_defect",
    "material_handling_lifting",
    "non_work_related",
    "ppe",
    "respiratory_protection",
    "slip_trip_fall",
    "stairs_ladders",
    "tools_equipment",
    "vehicle_company_owned",
    "vehicle_not_company_owned",
    "walking_working_surface",
    "work_at_elevation",
    "crane",
]

# Retired categories sort after the official ones, keeping their old order.
RETIRED_ORDER_OFFSET = 1000

_categories = sa.table(
    CATEGORIES,
    sa.column("code", sa.Text),
    sa.column("name", sa.Text),
    sa.column("display_order", sa.Integer),
    sa.column("active", sa.Boolean),
    schema=SAFETY,
)


def upgrade() -> None:
    official = [code for code, _ in OFFICIAL_CATEGORIES]
    op.execute(
        _categories.update()
        .where(_categories.c.code.not_in(official))
        .where(_categories.c.active.is_(True))
        .values(active=False, display_order=_categories.c.display_order + RETIRED_ORDER_OFFSET)
    )
    # An official category that already exists is reactivated and reordered;
    # its name is never changed, so stored observations read as they did.
    rows = ",\n            ".join(
        f"('{code}', '{name}', {order}, true)"
        for order, (code, name) in enumerate(OFFICIAL_CATEGORIES, start=1)
    )
    op.execute(
        sa.text(
            f"""
            INSERT INTO {SAFETY}.{CATEGORIES} (code, name, display_order, active)
            VALUES
            {rows}
            ON CONFLICT (code) DO UPDATE
            SET active = true, display_order = EXCLUDED.display_order
            """
        )
    )


def downgrade() -> None:
    added = [code for code, _ in OFFICIAL_CATEGORIES if code not in PREVIOUS_CATEGORIES]
    quoted = ", ".join(f"'{code}'" for code in added)
    # Observations entered with a new category would lose their category.
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM {SAFETY}.{OBSERVATIONS} o
                    JOIN {SAFETY}.{CATEGORIES} c ON c.id = o.category_id
                    WHERE c.code IN ({quoted})
                ) THEN
                    RAISE EXCEPTION 'Cannot downgrade: observations use the official categories';
                END IF;
            END
            $$
            """
        )
    )
    op.execute(_categories.delete().where(_categories.c.code.in_(added)))
    for order, code in enumerate(PREVIOUS_CATEGORIES, start=1):
        op.execute(
            _categories.update()
            .where(_categories.c.code == code)
            .values(active=True, display_order=order)
        )
