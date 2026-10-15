"""incident record details

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-15 14:00:00

Record-level detail for Incident and Near Miss records (``safety.incident_records``):

- ``safety.incident_detail_codes``: stable codes of the record-detail taxonomies
  (LOPC failure mechanism, secondary containment, quantity unit, damage kind,
  currency, PIT ownership, potential severity, serious-risk category). Codes
  never change or disappear (deactivate instead); names may.
- ``safety.incident_record_classifications``: further Incident Classifications
  of a record beyond its ``classification_category_id``, so one event (a PIT
  accident that damaged property) can carry both.
- ``safety.incident_lopc_details``, ``incident_damage_details``,
  ``incident_pit_details``, ``incident_serious_risk_details``: at most one row
  per record each. Records are never deleted (they are voided), so every link
  is ON DELETE RESTRICT.

Coded columns are checked by a trigger against ``incident_detail_codes``; the
LOPC contributing factor reuses the existing ``lopc_contributing_factor``
Incident & Near Miss categories. Seeds only the taxonomy codes; no record data.
Detail is loaded from a reviewed mapping with
``python -m app.safety.records.detail_import``, never by this migration.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFETY = "safety"
RECORDS = "incident_records"
CODES = "incident_detail_codes"
CLASSIFICATIONS = "incident_record_classifications"
LOPC = "incident_lopc_details"
DAMAGE = "incident_damage_details"
PIT = "incident_pit_details"
SERIOUS_RISK = "incident_serious_risk_details"
DETAIL_TABLES = (LOPC, DAMAGE, PIT, SERIOUS_RISK)

# (taxonomy, [(code, name), ...]) in display order.
TAXONOMIES: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "lopc_failure_mechanism",
        [
            ("pipe", "Pipe"),
            ("pump_seal", "Pump Seal"),
            ("pump_bowl", "Pump Bowl"),
            ("gasket_fitting_valve", "Gasket / Fitting / Valve"),
            ("tank_weld", "Tank Weld"),
            ("process_hose", "Process Hose"),
            ("agitator_seal", "Agitator Seal"),
            ("pressure_relief_device", "Pressure Relief Device"),
            ("other", "Other"),
        ],
    ),
    (
        "secondary_containment_status",
        [
            ("contained", "Contained"),
            ("not_contained", "Not Contained"),
            ("not_applicable", "Not Applicable"),
            ("unknown", "Unknown"),
        ],
    ),
    (
        "quantity_unit",
        [
            ("gallons", "Gallons"),
            ("barrels", "Barrels"),
            ("liters", "Liters"),
            ("cubic_feet", "Cubic Feet"),
            ("cubic_meters", "Cubic Meters"),
            ("pounds", "Pounds"),
            ("kilograms", "Kilograms"),
        ],
    ),
    (
        "damage_kind",
        [
            ("equipment_damage", "Equipment Damage"),
            ("equipment_failure", "Equipment Failure"),
            ("property_damage", "Property Damage"),
        ],
    ),
    ("currency", [("USD", "US Dollar")]),
    (
        "pit_ownership",
        [
            ("company", "Company"),
            ("contractor", "Contractor"),
            ("third_party", "Third Party"),
            ("personal", "Personal"),
            ("unknown", "Unknown"),
        ],
    ),
    (
        "potential_severity",
        [
            ("fatality", "Potential Fatality"),
            ("life_threatening", "Potential Life-Threatening Injury"),
            ("life_altering", "Potential Life-Altering Injury"),
            ("serious_process_safety", "Potential Serious Process Safety Event"),
        ],
    ),
    (
        "serious_risk_category",
        [
            ("line_of_fire", "Line of Fire"),
            ("working_at_height", "Working at Height"),
            ("confined_space", "Confined Space"),
            ("hazardous_energy", "Hazardous Energy / Isolation"),
            ("electrical_arc_flash", "Electrical / Arc Flash"),
            ("mobile_equipment", "Mobile Equipment / PIT"),
            ("lifting_operations", "Lifting Operations"),
            ("hazardous_material_release", "Hazardous Material Release"),
            ("fire_explosion", "Fire / Explosion"),
            ("excavation", "Excavation"),
            ("other", "Other"),
        ],
    ),
]

# Coded columns per detail table: (column, taxonomy). "metric:<section>" is an
# existing Incident & Near Miss category section.
CODED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    LOPC: [
        ("quantity_unit_code", "quantity_unit"),
        ("failure_mechanism_code", "lopc_failure_mechanism"),
        ("contributing_factor_code", "metric:lopc_contributing_factor"),
        ("secondary_containment_status_code", "secondary_containment_status"),
    ],
    DAMAGE: [("damage_kind_code", "damage_kind"), ("currency_code", "currency")],
    PIT: [("ownership_type_code", "pit_ownership")],
    SERIOUS_RISK: [
        ("potential_severity_code", "potential_severity"),
        ("serious_risk_category_code", "serious_risk_category"),
    ],
}


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("updated_by", sa.Text(), nullable=False),
    ]


def _record_link(table: str) -> list[Any]:
    return [
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("incident_record_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        sa.UniqueConstraint("incident_record_id", name=f"uq_{table}_incident_record_id"),
        sa.ForeignKeyConstraint(
            ["incident_record_id"],
            [f"{SAFETY}.{RECORDS}.id"],
            name=f"fk_{table}_incident_record",
            ondelete="RESTRICT",
        ),
    ]


def _text(table: str, column: str, limit: int) -> sa.CheckConstraint:
    return sa.CheckConstraint(
        f"{column} IS NULL OR (btrim({column}) <> '' AND char_length({column}) <= {limit})",
        name=op.f(f"ck_{table}_{column}"),
    )


def upgrade() -> None:
    op.create_table(
        CODES,
        sa.Column("taxonomy", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("taxonomy", "code", name="pk_incident_detail_codes"),
        sa.CheckConstraint(
            "taxonomy ~ '^[a-z_]{1,60}$'", name=op.f("ck_incident_detail_codes_taxonomy")
        ),
        sa.CheckConstraint(
            "code ~ '^[A-Za-z0-9_]{1,60}$'", name=op.f("ck_incident_detail_codes_code")
        ),
        sa.CheckConstraint(
            "name = btrim(name) AND name <> '' AND char_length(name) <= 200",
            name=op.f("ck_incident_detail_codes_name"),
        ),
        schema=SAFETY,
    )
    codes = sa.table(
        CODES,
        sa.column("taxonomy", sa.Text),
        sa.column("code", sa.Text),
        sa.column("name", sa.Text),
        sa.column("display_order", sa.Integer),
        schema=SAFETY,
    )
    op.bulk_insert(
        codes,
        [
            {"taxonomy": taxonomy, "code": code, "name": name, "display_order": order}
            for taxonomy, entries in TAXONOMIES
            for order, (code, name) in enumerate(entries, start=1)
        ],
    )
    # Stored codes are analytical keys: a code is never renamed or removed.
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {SAFETY}.incident_detail_codes_are_stable() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF TG_OP = 'DELETE' OR NEW.taxonomy <> OLD.taxonomy OR NEW.code <> OLD.code THEN
                    RAISE EXCEPTION 'detail codes are stable: deactivate a code instead'
                        USING ERRCODE = 'check_violation',
                              CONSTRAINT = 'ck_incident_detail_codes_stable';
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
            CREATE TRIGGER trg_incident_detail_codes_stable
            BEFORE UPDATE OR DELETE ON {SAFETY}.{CODES}
            FOR EACH ROW EXECUTE FUNCTION {SAFETY}.incident_detail_codes_are_stable()
            """
        )
    )
    # Arguments: (column, taxonomy) pairs. A null code is "not recorded".
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {SAFETY}.incident_detail_code_rule() RETURNS trigger
            LANGUAGE plpgsql AS $$
            DECLARE
                fields jsonb := to_jsonb(NEW);
                i integer := 0;
                v_code text;
                v_taxonomy text;
                known boolean;
            BEGIN
                WHILE i < TG_NARGS LOOP
                    v_code := fields ->> TG_ARGV[i];
                    v_taxonomy := TG_ARGV[i + 1];
                    IF v_code IS NOT NULL THEN
                        IF v_taxonomy LIKE 'metric:%' THEN
                            SELECT EXISTS (
                                SELECT 1
                                FROM {SAFETY}.metric_categories c
                                JOIN {SAFETY}.metric_sections s ON s.id = c.section_id
                                WHERE s.metric_set = 'incidents'
                                  AND s.code = substr(v_taxonomy, 8)
                                  AND c.code = v_code
                            ) INTO known;
                        ELSE
                            SELECT EXISTS (
                                SELECT 1 FROM {SAFETY}.{CODES} d
                                WHERE d.taxonomy = v_taxonomy AND d.code = v_code
                            ) INTO known;
                        END IF;
                        IF NOT known THEN
                            RAISE EXCEPTION 'unknown % code', v_taxonomy
                                USING ERRCODE = 'check_violation',
                                      CONSTRAINT = 'ck_' || TG_TABLE_NAME || '_' || TG_ARGV[i];
                        END IF;
                    END IF;
                    i := i + 2;
                END LOOP;
                RETURN NEW;
            END
            $$
            """
        )
    )

    op.create_table(
        CLASSIFICATIONS,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("incident_record_id", sa.BigInteger(), nullable=False),
        sa.Column("classification_category_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{CLASSIFICATIONS}"),
        sa.UniqueConstraint(
            "incident_record_id",
            "classification_category_id",
            name=f"uq_{CLASSIFICATIONS}_record_category",
        ),
        sa.ForeignKeyConstraint(
            ["incident_record_id"],
            [f"{SAFETY}.{RECORDS}.id"],
            name=f"fk_{CLASSIFICATIONS}_incident_record",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["classification_category_id"],
            [f"{SAFETY}.metric_categories.id"],
            name=f"fk_{CLASSIFICATIONS}_classification",
            ondelete="RESTRICT",
        ),
        schema=SAFETY,
    )
    op.create_index(
        f"ix_{CLASSIFICATIONS}_classification_category_id",
        CLASSIFICATIONS,
        ["classification_category_id"],
        schema=SAFETY,
    )
    # The same rule as the record's own classification (migration 0009).
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER trg_{CLASSIFICATIONS}_rule
            BEFORE INSERT OR UPDATE OF classification_category_id ON {SAFETY}.{CLASSIFICATIONS}
            FOR EACH ROW EXECUTE FUNCTION {SAFETY}.incident_record_classification_rule()
            """
        )
    )

    op.create_table(
        LOPC,
        *_record_link(LOPC),
        sa.Column("is_lopc", sa.Boolean(), nullable=True),
        sa.Column("material_name", sa.Text(), nullable=True),
        sa.Column("estimated_quantity", sa.Numeric(14, 3), nullable=True),
        sa.Column("quantity_unit_code", sa.Text(), nullable=True),
        sa.Column("equipment_tag", sa.Text(), nullable=True),
        sa.Column("failure_mechanism_code", sa.Text(), nullable=True),
        sa.Column("contributing_factor_code", sa.Text(), nullable=True),
        sa.Column("secondary_containment_status_code", sa.Text(), nullable=True),
        sa.Column("process_safety_incident", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "estimated_quantity IS NULL OR estimated_quantity >= 0",
            name=op.f(f"ck_{LOPC}_estimated_quantity"),
        ),
        sa.CheckConstraint(
            "(estimated_quantity IS NULL) = (quantity_unit_code IS NULL)",
            name=op.f(f"ck_{LOPC}_quantity_with_unit"),
        ),
        _text(LOPC, "material_name", 200),
        _text(LOPC, "equipment_tag", 100),
        _text(LOPC, "notes", 2000),
        schema=SAFETY,
    )
    op.create_table(
        DAMAGE,
        *_record_link(DAMAGE),
        sa.Column("damage_kind_code", sa.Text(), nullable=True),
        sa.Column("asset_or_property_name", sa.Text(), nullable=True),
        sa.Column("equipment_tag", sa.Text(), nullable=True),
        sa.Column("asset_type", sa.Text(), nullable=True),
        sa.Column("damage_description", sa.Text(), nullable=True),
        sa.Column("operational_impact", sa.Text(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency_code", sa.Text(), nullable=True),
        sa.Column("work_order_reference", sa.Text(), nullable=True),
        sa.Column("out_of_service", sa.Boolean(), nullable=True),
        sa.Column("repair_required", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0",
            name=op.f(f"ck_{DAMAGE}_estimated_cost"),
        ),
        sa.CheckConstraint(
            "(estimated_cost IS NULL) = (currency_code IS NULL)",
            name=op.f(f"ck_{DAMAGE}_cost_with_currency"),
        ),
        _text(DAMAGE, "asset_or_property_name", 200),
        _text(DAMAGE, "equipment_tag", 100),
        _text(DAMAGE, "asset_type", 100),
        _text(DAMAGE, "damage_description", 2000),
        _text(DAMAGE, "operational_impact", 2000),
        _text(DAMAGE, "work_order_reference", 100),
        _text(DAMAGE, "notes", 2000),
        schema=SAFETY,
    )
    op.create_table(
        PIT,
        *_record_link(PIT),
        sa.Column("vehicle_identifier", sa.Text(), nullable=True),
        sa.Column("vehicle_type", sa.Text(), nullable=True),
        sa.Column("ownership_type_code", sa.Text(), nullable=True),
        sa.Column("operating_company", sa.Text(), nullable=True),
        sa.Column("impacted_asset_or_property", sa.Text(), nullable=True),
        sa.Column("damage_occurred", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit_columns(),
        _text(PIT, "vehicle_identifier", 100),
        _text(PIT, "vehicle_type", 100),
        _text(PIT, "operating_company", 200),
        _text(PIT, "impacted_asset_or_property", 200),
        _text(PIT, "notes", 2000),
        schema=SAFETY,
    )
    op.create_table(
        SERIOUS_RISK,
        *_record_link(SERIOUS_RISK),
        sa.Column("is_psif", sa.Boolean(), nullable=False),
        sa.Column("potential_severity_code", sa.Text(), nullable=True),
        sa.Column("serious_risk_category_code", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "is_psif OR (potential_severity_code IS NULL AND serious_risk_category_code IS NULL)",
            name=op.f(f"ck_{SERIOUS_RISK}_severity_needs_psif"),
        ),
        _text(SERIOUS_RISK, "rationale", 2000),
        schema=SAFETY,
    )
    for table, columns in CODED_COLUMNS.items():
        arguments = ", ".join(f"'{part}'" for pair in columns for part in pair)
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_{table}_codes
                BEFORE INSERT OR UPDATE ON {SAFETY}.{table}
                FOR EACH ROW EXECUTE FUNCTION {SAFETY}.incident_detail_code_rule({arguments})
                """
            )
        )

    op.drop_constraint(op.f("ck_import_runs_importer"), "import_runs", schema=SAFETY, type_="check")
    op.create_check_constraint(
        op.f("ck_import_runs_importer"),
        "import_runs",
        "importer IN ('monthly_metrics', 'behavior', 'performance', 'trir_history', "
        "'incident_records', 'psm_pha', 'incident_details')",
        schema=SAFETY,
    )


# Record detail would be lost by a downgrade.
DOWNGRADE_GUARD = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM {SAFETY}.{CLASSIFICATIONS})
            OR EXISTS (SELECT 1 FROM {SAFETY}.{LOPC})
            OR EXISTS (SELECT 1 FROM {SAFETY}.{DAMAGE})
            OR EXISTS (SELECT 1 FROM {SAFETY}.{PIT})
            OR EXISTS (SELECT 1 FROM {SAFETY}.{SERIOUS_RISK}) THEN
            RAISE EXCEPTION 'Cannot downgrade: incident record details exist';
        END IF;
        IF EXISTS (SELECT 1 FROM {SAFETY}.import_runs WHERE importer = 'incident_details') THEN
            RAISE EXCEPTION 'Cannot downgrade: incident detail import runs exist';
        END IF;
    END
    $$
"""


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_GUARD))
    op.drop_constraint(op.f("ck_import_runs_importer"), "import_runs", schema=SAFETY, type_="check")
    op.create_check_constraint(
        op.f("ck_import_runs_importer"),
        "import_runs",
        "importer IN ('monthly_metrics', 'behavior', 'performance', 'trir_history', "
        "'incident_records', 'psm_pha')",
        schema=SAFETY,
    )
    for table in DETAIL_TABLES:
        op.drop_table(table, schema=SAFETY)
    op.drop_table(CLASSIFICATIONS, schema=SAFETY)
    op.execute(sa.text(f"DROP FUNCTION {SAFETY}.incident_detail_code_rule()"))
    op.drop_table(CODES, schema=SAFETY)
    op.execute(sa.text(f"DROP FUNCTION {SAFETY}.incident_detail_codes_are_stable()"))
