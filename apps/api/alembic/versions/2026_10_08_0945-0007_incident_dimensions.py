"""incident dimensions

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08 09:45:00

Adds the Incident & Near Miss analytical dimensions:

- ``safety.areas``: the site's reporting areas (process units, support areas
  and organizations), seeded from the 2026 LCY EHS workbook's area grids.
- ``safety.metric_categories.area_id``: links a category to an area. Only the
  ``incidents_by_area`` and ``near_misses_by_area`` sections may (and must)
  hold area-linked categories; a trigger enforces this, since a CHECK
  constraint cannot read the section.
- ``safety.metric_categories.description``: optional reviewer-facing text,
  seeded only where the workbook defines a category (Near-Miss Cause comments).
- Seven ``incidents`` sections: incidents and near misses by area, near-miss
  potential and cause, LOPC contributing factor, injury cause and body part.

Seeds definitions only. No monthly values are seeded; historical values are
loaded with ``python -m app.safety.legacy_import`` from reviewed mappings.
Breakdowns are analytical tags: no database rule requires them to add up to
the Incident, Near Miss, LOPC or injury totals.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFETY = "safety"
AREAS = "areas"
SECTIONS = "metric_sections"
CATEGORIES = "metric_categories"
VALUES = "monthly_metric_values"
INCIDENTS = "incidents"
AREA_SECTIONS = ("incidents_by_area", "near_misses_by_area")
AREA_KINDS = ("process_unit", "support", "organization")

# (code, name, description, kind) in display order. Descriptions of 100-900 are the
# area names in the comments on 'Dash'!B27:B35; the other areas have none.
SEED_AREAS: list[tuple[str, str, str | None, str]] = [
    ("100", "100", "Ingredient Prep", "process_unit"),
    ("200", "200", "Monomer Purification", "process_unit"),
    ("300", "300", "Reactions", "process_unit"),
    ("400", "400", "Blending & Stripping", "process_unit"),
    ("500", "500", "Solvent Purification", "process_unit"),
    ("600", "600", "Utilities", "process_unit"),
    ("700", "700", "Finishing", "process_unit"),
    ("800", "800", "Monomer & Waste Hydrocarbons", "process_unit"),
    ("900", "900", "Blowdown & Flare", "process_unit"),
    ("whse", "WHSE", None, "support"),
    ("maint", "Maintenance", None, "support"),
    ("lab", "Lab", None, "support"),
    ("mundy", "MUNDY", None, "organization"),
    ("admin", "Admin", None, "support"),
    ("third_party", "3rd Party", None, "organization"),
]

Category = tuple[str, str, str | None]

# Near-Miss Cause descriptions: the subcategory lists in the comments on
# 'Incident Data'!P39:P49, verbatim (one line per item, as in the source).
NEAR_MISS_CAUSES: list[Category] = [
    (
        "human_performance",
        "Human Performance",
        "Complacency\nInattention\nLack of Situational Awareness\nDistraction\nRushing\n"
        "Fatigue\nPoor Decision Making\nFailure to Follow Procedure\n"
        "Assumption Instead of Verification\nIncorrect Lineup\nFailure to Stop Work\n"
        "Taking a Shortcut\nAt-Risk Behavior\nNormalization of Deviation\nComplacency\n"
        "Assumption\nFailure to Verify\nOverconfidence\nPoor Hazard Recognition",
    ),
    (
        "communication",
        "Communication",
        "Poor Shift Handover\nInadequate Pre-job Brief\nMiscommunication\n"
        "No Communication Between Work Groups\nContractor Communication Failure\n"
        "Incomplete Work Permit Discussion",
    ),
    (
        "training_competency",
        "Training / Competency",
        "nsufficient Training\nInexperienced Worker\nSkill Deficiency\n"
        "Poor Understanding of Hazards\nInadequate Qualification\nLack of Refresher Training",
    ),
    (
        "procedures",
        "Procedures",
        "Procedure Not Available\nProcedure Not Followed\nProcedure Incorrect\n"
        "Procedure Outdated\nProcedure Too Complex\nMissing Critical Step",
    ),
    (
        "equipment_maintenance",
        "Equipment / Maintenance",
        "Equipment Failure\nInstrument Failure\nValve Failure\nHose Failure\nGasket Failure\n"
        "Flange Leak\nCorrosion\nWear\nImproper Installation\n"
        "Preventive Maintenance Deficiency\nMechanical Integrity Deficiency",
    ),
    (
        "design_engineering",
        "Design / Engineering",
        "Poor Equipment Design\nInadequate Guarding\nErgonomic Design Issue\nLayout Issue\n"
        "Poor Accessibility\nLack of Secondary Containment\nInsufficient Ventilation\n"
        "Inadequate Safety Device",
    ),
    (
        "work_planning",
        "Work Planning",
        "Poor Job Planning\nInadequate Hazard Assessment\nMissing JSA/JHA\n"
        "Inadequate Permit Review\nIncorrect Work Sequence\nInadequate Resources\n"
        "Schedule Pressure",
    ),
    (
        "housekeeping",
        "Housekeeping",
        "Slip Hazard\nTrip Hazard\nPoor Material Storage\nBlocked Access\n"
        "Obstructed Emergency Equipment\nPoor Lighting",
    ),
    (
        "environmental_conditions",
        "Environmental Conditions",
        "Weather\nWind\nRain\nIce\nHeat Stress\nCold Stress\nPoor Visibility\nNoise",
    ),
    (
        "management_systems",
        "Management Systems",
        "Lack of Supervision\nInadequate Oversight\nAudit Finding Not Corrected\n"
        "Management of Change Deficiency\nInspection Deficiency\nRisk Assessment Deficiency\n"
        "Inadequate Staffing\nWeak Safety Culture",
    ),
    (
        "contractor_management",
        "Contractor Management",
        "Contractor Training\nContractor Supervision\nContractor Procedure\n"
        "Contractor Communication\nContractor Competency",
    ),
]

# 'Incident Data'!P12:P18 (no comments in the source).
NEAR_MISS_POTENTIALS: list[Category] = [
    ("sif", "SIF", None),
    ("lost_time_injury", "Lost Time Injury", None),
    ("exposure", "Exposure", None),
    ("fire", "Fire", None),
    ("property_damage", "Property Damage", None),
    ("environmental_release", "Environmental Release", None),
    ("business_interruption", "Business Interruption", None),
]

# 'Incident Data'!A31:A33.
LOPC_FACTORS: list[Category] = [
    ("mechanical_integrity", "Mechanical Integrity", None),
    ("human_error", "Human Error", None),
    ("other", "Other", None),
]

# 'Incident Data'!AH9:AH24 in source order; AH19 and AH23 are blank.
INJURY_CAUSES: list[Category] = [
    ("caught_between", "Caught Between", None),
    ("caught_in", "Caught In", None),
    ("caught_on", "Caught On", None),
    ("contact_by", "Contact By", None),
    ("contact_with", "Contact With", None),
    ("exposure", "Exposure", None),
    ("fall_below", "Fall Below", None),
    ("fall_same_level", "Fall Same Level", None),
    ("foreign_body", "Foreign Body", None),
    ("slip_trip_no_fall", "Slip/Trip (No Fall)", None),
    ("sprain", "Sprain", None),
    ("strain_overexertion", "Strain (Overexertion)", None),
    ("struck_against", "Struck Against", None),
    ("struck_by", "Struck By", None),
]

# 'Incident Data'!AH37:AH63 in source order.
BODY_PARTS: list[Category] = [
    ("abdomen", "Abdomen", None),
    ("ankle", "Ankle", None),
    ("arm", "Arm", None),
    ("back", "Back", None),
    ("body_general", "Body General", None),
    ("buttocks", "Buttocks", None),
    ("chest", "Chest", None),
    ("ear_auditory", "Ear/Auditory", None),
    ("eye", "Eye", None),
    ("face_nose", "Face/Nose", None),
    ("feet", "Feet", None),
    ("fingers", "Fingers", None),
    ("hand", "Hand", None),
    ("head", "Head", None),
    ("internal", "Internal", None),
    ("jaw", "Jaw", None),
    ("knee", "Knee", None),
    ("leg", "Leg", None),
    ("other", "Other", None),
    ("neck", "Neck", None),
    ("respiratory", "Respiratory", None),
    ("ribs", "Ribs", None),
    ("shoulder", "Shoulder", None),
    ("thigh", "Thigh", None),
    ("toes", "Toes", None),
    ("tooth_mouth", "Tooth/Mouth", None),
    ("wrist", "Wrist", None),
]

# (code, name, categories or None for one category per area), after the six
# sections seeded by 0003.
NEW_SECTIONS: list[tuple[str, str, list[Category] | None]] = [
    ("incidents_by_area", "Incidents by Area", None),
    ("near_misses_by_area", "Near Misses by Area", None),
    ("near_miss_potential", "Near-Miss Potential", NEAR_MISS_POTENTIALS),
    ("near_miss_cause", "Near-Miss Cause", NEAR_MISS_CAUSES),
    ("lopc_contributing_factor", "LOPC Contributing Factor", LOPC_FACTORS),
    ("injury_cause", "Injury Cause", INJURY_CAUSES),
    ("body_part", "Body Part", BODY_PARTS),
]
FIRST_NEW_SECTION_ORDER = 7

_AREA_SECTION_LIST = ", ".join(f"'{code}'" for code in AREA_SECTIONS)
_NEW_SECTION_LIST = ", ".join(f"'{code}'" for code, _, _ in NEW_SECTIONS)


def _seed_areas() -> None:
    areas = sa.table(
        AREAS,
        sa.column("code", sa.Text),
        sa.column("name", sa.Text),
        sa.column("description", sa.Text),
        sa.column("area_kind", sa.Text),
        sa.column("display_order", sa.Integer),
        schema=SAFETY,
    )
    op.bulk_insert(
        areas,
        [
            {
                "code": code,
                "name": name,
                "description": description,
                "area_kind": kind,
                "display_order": order,
            }
            for order, (code, name, description, kind) in enumerate(SEED_AREAS, start=1)
        ],
    )


def _seed_sections() -> None:
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
        sa.column("description", sa.Text),
        sa.column("display_order", sa.Integer),
        sa.column("area_id", sa.Integer),
        schema=SAFETY,
    )
    areas = sa.table(
        AREAS,
        sa.column("id", sa.Integer),
        sa.column("code", sa.Text),
        sa.column("name", sa.Text),
        sa.column("display_order", sa.Integer),
        schema=SAFETY,
    )
    op.bulk_insert(
        sections,
        [
            {"metric_set": INCIDENTS, "code": code, "name": name, "display_order": order}
            for order, (code, name, _) in enumerate(NEW_SECTIONS, start=FIRST_NEW_SECTION_ORDER)
        ],
    )
    for section_code, _, section_categories in NEW_SECTIONS:
        section_id = (
            sa.select(sections.c.id)
            .where(sections.c.metric_set == INCIDENTS, sections.c.code == section_code)
            .scalar_subquery()
        )
        if section_categories is None:
            # One category per area; its code is the area code.
            op.execute(
                categories.insert().from_select(
                    ["section_id", "code", "name", "display_order", "area_id"],
                    sa.select(
                        section_id, areas.c.code, areas.c.name, areas.c.display_order, areas.c.id
                    ),
                )
            )
            continue
        for order, (code, name, description) in enumerate(section_categories, start=1):
            op.execute(
                categories.insert().from_select(
                    ["section_id", "code", "name", "description", "display_order"],
                    sa.select(
                        section_id,
                        sa.literal(code, sa.Text),
                        sa.literal(name, sa.Text),
                        sa.literal(description, sa.Text),
                        sa.literal(order, sa.Integer),
                    ),
                )
            )


def upgrade() -> None:
    op.create_table(
        AREAS,
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("area_kind", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_areas"),
        sa.UniqueConstraint("code", name="uq_areas_code"),
        # op.f(): the name is final; the "ck" naming convention must not prefix it again.
        sa.CheckConstraint(
            "area_kind IN ('process_unit', 'support', 'organization')",
            name=op.f("ck_areas_area_kind"),
        ),
        sa.CheckConstraint("code ~ '^[a-z0-9_]{1,100}$'", name=op.f("ck_areas_code")),
        sa.CheckConstraint(
            "name = btrim(name) AND name <> '' AND char_length(name) <= 200",
            name=op.f("ck_areas_name"),
        ),
        schema=SAFETY,
    )

    op.add_column(CATEGORIES, sa.Column("description", sa.Text(), nullable=True), schema=SAFETY)
    op.add_column(CATEGORIES, sa.Column("area_id", sa.Integer(), nullable=True), schema=SAFETY)
    op.create_foreign_key(
        "fk_metric_categories_area",
        CATEGORIES,
        AREAS,
        ["area_id"],
        ["id"],
        source_schema=SAFETY,
        referent_schema=SAFETY,
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_metric_categories_section_area",
        CATEGORIES,
        ["section_id", "area_id"],
        unique=True,
        schema=SAFETY,
        postgresql_where=sa.text("area_id IS NOT NULL"),
    )

    # A category is area-linked exactly when its section is an area section.
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {SAFETY}.metric_category_area_rule() RETURNS trigger
            LANGUAGE plpgsql AS $$
            DECLARE
                area_section boolean;
            BEGIN
                SELECT s.metric_set = '{INCIDENTS}' AND s.code IN ({_AREA_SECTION_LIST})
                  INTO area_section
                  FROM {SAFETY}.{SECTIONS} s WHERE s.id = NEW.section_id;
                IF NEW.area_id IS NOT NULL AND NOT coalesce(area_section, false) THEN
                    RAISE EXCEPTION 'area-linked categories belong only to the area sections'
                        USING ERRCODE = 'check_violation',
                              CONSTRAINT = 'ck_metric_categories_area_section';
                END IF;
                IF NEW.area_id IS NULL AND coalesce(area_section, false) THEN
                    RAISE EXCEPTION 'categories of an area section must be linked to an area'
                        USING ERRCODE = 'check_violation',
                              CONSTRAINT = 'ck_metric_categories_area_section';
                END IF;
                RETURN NEW;
            END
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER trg_metric_categories_area_rule
            BEFORE INSERT OR UPDATE OF section_id, area_id ON {SAFETY}.{CATEGORIES}
            FOR EACH ROW EXECUTE FUNCTION {SAFETY}.metric_category_area_rule()
            """
        )
    )
    # Renaming a section must not break the rule for the categories it holds.
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {SAFETY}.metric_section_area_rule() RETURNS trigger
            LANGUAGE plpgsql AS $$
            DECLARE
                area_section boolean := NEW.metric_set = '{INCIDENTS}'
                    AND NEW.code IN ({_AREA_SECTION_LIST});
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM {SAFETY}.{CATEGORIES} c
                    WHERE c.section_id = NEW.id AND (c.area_id IS NOT NULL) <> area_section
                ) THEN
                    RAISE EXCEPTION 'area-linked categories belong only to the area sections'
                        USING ERRCODE = 'check_violation',
                              CONSTRAINT = 'ck_metric_categories_area_section';
                END IF;
                RETURN NEW;
            END
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER trg_metric_sections_area_rule
            BEFORE UPDATE OF metric_set, code ON {SAFETY}.{SECTIONS}
            FOR EACH ROW EXECUTE FUNCTION {SAFETY}.metric_section_area_rule()
            """
        )
    )

    _seed_areas()
    _seed_sections()


# Entered or imported breakdown values would be lost by a downgrade.
DOWNGRADE_GUARD = f"""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM {SAFETY}.{VALUES} v
            JOIN {SAFETY}.{CATEGORIES} c ON c.id = v.category_id
            JOIN {SAFETY}.{SECTIONS} s ON s.id = c.section_id
            WHERE s.metric_set = '{INCIDENTS}' AND s.code IN ({_NEW_SECTION_LIST})
        ) THEN
            RAISE EXCEPTION 'Cannot downgrade: incident dimension values exist';
        END IF;
        IF EXISTS (
            SELECT 1 FROM {SAFETY}.{VALUES} v
            JOIN {SAFETY}.{CATEGORIES} c ON c.id = v.category_id
            WHERE c.area_id IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'Cannot downgrade: area-linked values exist';
        END IF;
    END
    $$
"""


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_GUARD))
    op.execute(
        sa.text(
            f"""
            DELETE FROM {SAFETY}.{CATEGORIES}
            WHERE section_id IN (
                SELECT id FROM {SAFETY}.{SECTIONS}
                WHERE metric_set = '{INCIDENTS}' AND code IN ({_NEW_SECTION_LIST})
            )
            """
        )
    )
    op.execute(
        sa.text(
            f"DELETE FROM {SAFETY}.{SECTIONS} "
            f"WHERE metric_set = '{INCIDENTS}' AND code IN ({_NEW_SECTION_LIST})"
        )
    )
    op.execute(sa.text(f"DROP TRIGGER trg_metric_sections_area_rule ON {SAFETY}.{SECTIONS}"))
    op.execute(sa.text(f"DROP FUNCTION {SAFETY}.metric_section_area_rule()"))
    op.execute(sa.text(f"DROP TRIGGER trg_metric_categories_area_rule ON {SAFETY}.{CATEGORIES}"))
    op.execute(sa.text(f"DROP FUNCTION {SAFETY}.metric_category_area_rule()"))
    op.drop_index("uq_metric_categories_section_area", table_name=CATEGORIES, schema=SAFETY)
    op.drop_constraint("fk_metric_categories_area", CATEGORIES, schema=SAFETY, type_="foreignkey")
    op.drop_column(CATEGORIES, "area_id", schema=SAFETY)
    op.drop_column(CATEGORIES, "description", schema=SAFETY)
    op.drop_table(AREAS, schema=SAFETY)
