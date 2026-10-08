"""incident records and trir history

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-08 15:00:00

Schema only; seeds nothing and changes no existing table.

- ``safety.incident_records``: individual Incident and Near Miss records.
  The reporting month is derived from ``incident_date``. Records never change
  the monthly totals (they stay authoritative); voided and reclassified
  records are kept, never deleted. ``incident_number`` is optional, stored in
  normalized form and unique when present. A classification must be a
  category of the Incident Classification section (trigger).
- ``safety.trir_annual_facts``: the approved TRIR history, one row per year
  (annual recordables, Incident count, annual man-hours, industry benchmark
  and the legacy displayed TRIR/TIR). No monthly hours: those stay in Safety
  Performance and are read from there.

Records are loaded with ``python -m app.safety.records.legacy_import`` and
TRIR history with ``python -m app.safety.trir.legacy_import``, each from a
reviewed mapping, never by this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFETY = "safety"
RECORDS = "incident_records"
FACTS = "trir_annual_facts"


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


def upgrade() -> None:
    op.create_table(
        RECORDS,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("incident_number", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("incident_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("area_id", sa.Integer(), nullable=True),
        sa.Column("classification_category_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("related_incident_id", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.Text(), server_default=sa.text("'manual'"), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_incident_records"),
        sa.ForeignKeyConstraint(
            ["area_id"], [f"{SAFETY}.areas.id"], name="fk_incident_records_area", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["classification_category_id"],
            [f"{SAFETY}.metric_categories.id"],
            name="fk_incident_records_classification",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["related_incident_id"],
            [f"{SAFETY}.{RECORDS}.id"],
            name="fk_incident_records_related",
            ondelete="RESTRICT",
        ),
        # op.f(): the names are final; the "ck" naming convention must not prefix them again.
        sa.CheckConstraint(
            "event_type IN ('incident', 'near_miss')", name=op.f("ck_incident_records_event_type")
        ),
        sa.CheckConstraint(
            "status IN ('active', 'voided', 'reclassified')",
            name=op.f("ck_incident_records_status"),
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'legacy_import')", name=op.f("ck_incident_records_source")
        ),
        sa.CheckConstraint(
            "incident_date BETWEEN DATE '2000-01-01' AND DATE '2100-12-31'",
            name=op.f("ck_incident_records_incident_date"),
        ),
        sa.CheckConstraint(
            "btrim(description) <> '' AND char_length(description) <= 4000",
            name=op.f("ck_incident_records_description"),
        ),
        sa.CheckConstraint(
            "incident_number IS NULL OR incident_number ~ '^[A-Z]{2,10}-[0-9]{4}-[0-9]{3,6}$'",
            name=op.f("ck_incident_records_incident_number"),
        ),
        sa.CheckConstraint(
            "status_reason IS NULL OR (btrim(status_reason) <> '' "
            "AND char_length(status_reason) <= 1000)",
            name=op.f("ck_incident_records_status_reason"),
        ),
        sa.CheckConstraint(
            "status = 'active' OR status_reason IS NOT NULL",
            name=op.f("ck_incident_records_inactive_has_reason"),
        ),
        sa.CheckConstraint(
            "status <> 'reclassified' OR related_incident_id IS NOT NULL",
            name=op.f("ck_incident_records_reclassified_has_replacement"),
        ),
        sa.CheckConstraint(
            "related_incident_id IS NULL OR related_incident_id <> id",
            name=op.f("ck_incident_records_related_not_self"),
        ),
        sa.CheckConstraint(
            "source_reference IS NULL OR char_length(source_reference) <= 500",
            name=op.f("ck_incident_records_source_reference"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_incident_records_version")),
        schema=SAFETY,
    )
    op.create_index(
        "uq_incident_records_incident_number",
        RECORDS,
        ["incident_number"],
        unique=True,
        schema=SAFETY,
        postgresql_where=sa.text("incident_number IS NOT NULL"),
    )
    op.create_index(
        "ix_incident_records_incident_date", RECORDS, ["incident_date"], schema=SAFETY
    )
    op.create_index(
        "ix_incident_records_event_type_date",
        RECORDS,
        ["event_type", "incident_date"],
        schema=SAFETY,
    )
    op.create_index(
        "ix_incident_records_area_date", RECORDS, ["area_id", "incident_date"], schema=SAFETY
    )
    op.create_index(
        "ix_incident_records_active_type_date",
        RECORDS,
        ["event_type", "incident_date"],
        schema=SAFETY,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_incident_records_related_incident_id",
        RECORDS,
        ["related_incident_id"],
        schema=SAFETY,
    )
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {SAFETY}.incident_record_classification_rule() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.classification_category_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1
                    FROM {SAFETY}.metric_categories c
                    JOIN {SAFETY}.metric_sections s ON s.id = c.section_id
                    WHERE c.id = NEW.classification_category_id
                      AND s.metric_set = 'incidents'
                      AND s.code = 'incident_classification'
                ) THEN
                    RAISE EXCEPTION 'a record classification must be an Incident Classification'
                        USING ERRCODE = 'check_violation',
                              CONSTRAINT = 'ck_incident_records_classification';
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
            CREATE TRIGGER trg_incident_records_classification_rule
            BEFORE INSERT OR UPDATE OF classification_category_id ON {SAFETY}.{RECORDS}
            FOR EACH ROW EXECUTE FUNCTION {SAFETY}.incident_record_classification_rule()
            """
        )
    )

    op.create_table(
        FACTS,
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("reporting_year", sa.SmallInteger(), nullable=False),
        sa.Column("recordable_count", sa.Integer(), nullable=True),
        sa.Column("incident_count", sa.Integer(), nullable=True),
        sa.Column("annual_man_hours", sa.Numeric(12, 2), nullable=True),
        sa.Column("industry_benchmark", sa.Numeric(), nullable=True),
        sa.Column("benchmark_source", sa.Text(), nullable=True),
        sa.Column("legacy_displayed_trir", sa.Numeric(), nullable=True),
        sa.Column("legacy_tir", sa.Numeric(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_trir_annual_facts"),
        sa.UniqueConstraint("reporting_year", name="uq_trir_annual_facts_reporting_year"),
        sa.CheckConstraint(
            "reporting_year BETWEEN 2000 AND 2100",
            name=op.f("ck_trir_annual_facts_reporting_year"),
        ),
        sa.CheckConstraint(
            "recordable_count >= 0", name=op.f("ck_trir_annual_facts_recordable_count")
        ),
        sa.CheckConstraint("incident_count >= 0", name=op.f("ck_trir_annual_facts_incident_count")),
        sa.CheckConstraint(
            "annual_man_hours > 0", name=op.f("ck_trir_annual_facts_annual_man_hours")
        ),
        sa.CheckConstraint(
            "industry_benchmark >= 0", name=op.f("ck_trir_annual_facts_industry_benchmark")
        ),
        sa.CheckConstraint(
            "legacy_displayed_trir >= 0", name=op.f("ck_trir_annual_facts_legacy_displayed_trir")
        ),
        sa.CheckConstraint("legacy_tir >= 0", name=op.f("ck_trir_annual_facts_legacy_tir")),
        sa.CheckConstraint("btrim(source) <> ''", name=op.f("ck_trir_annual_facts_source")),
        schema=SAFETY,
    )


# Records and TRIR history would be lost by a downgrade.
DOWNGRADE_GUARD = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM {SAFETY}.{RECORDS}) THEN
            RAISE EXCEPTION 'Cannot downgrade: incident records exist';
        END IF;
        IF EXISTS (SELECT 1 FROM {SAFETY}.{FACTS}) THEN
            RAISE EXCEPTION 'Cannot downgrade: TRIR history exists';
        END IF;
    END
    $$
"""


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_GUARD))
    op.drop_table(FACTS, schema=SAFETY)
    op.execute(sa.text(f"DROP TRIGGER trg_incident_records_classification_rule ON {SAFETY}.{RECORDS}"))
    op.execute(sa.text(f"DROP FUNCTION {SAFETY}.incident_record_classification_rule()"))
    op.drop_table(RECORDS, schema=SAFETY)
