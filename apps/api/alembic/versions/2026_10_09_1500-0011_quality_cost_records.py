"""quality cost records

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-09 15:00:00

Schema only; seeds nothing and changes no existing table.

- ``quality.cost_records``: Quality Cost records, one per quality cost item,
  classified as Prevention, Appraisal, Internal Failure or External Failure.
  The one record set behind the Quality Cost Register, COPQ and the COQ
  Matrix. Totals and net cost are calculated by the API, never stored.
- ``quality.cost_record_references``: links from a record to other records or
  documents.

The monthly COQ workbook lines are converted into records by
``python -m app.quality.cost.legacy_import``, never by this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUALITY = "quality"
RECORDS = "cost_records"
REFERENCES = "cost_record_references"
IDENTIFICATION_COLUMNS = (
    "product",
    "campaign",
    "lot",
    "location",
    "process",
    "equipment",
    "counterparty",
    "owner",
)
COMPONENT_COLUMNS = (
    "material_cost",
    "labor_cost",
    "production_cost",
    "testing_cost",
    "maintenance_cost",
    "freight_cost",
    "disposal_cost",
    "customer_cost",
    "other_cost",
)
MONEY_COLUMNS = (*COMPONENT_COLUMNS, "recovered_cost", "avoided_cost")


def _optional_text(column: str, length: int) -> str:
    return f"{column} IS NULL OR (btrim({column}) <> '' AND char_length({column}) <= {length})"


def _check(table: str, name: str, condition: str) -> sa.CheckConstraint:
    # op.f(): the names are final; the "ck" naming convention must not prefix them again.
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _audit_columns(*, updated: bool = True) -> list[sa.Column]:
    columns = [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
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


def upgrade() -> None:
    op.create_table(
        RECORDS,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("area_id", sa.Integer(), nullable=True),
        sa.Column("coq_class", sa.Text(), nullable=False),
        sa.Column("category_code", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        *(sa.Column(column, sa.Text(), nullable=True) for column in IDENTIFICATION_COLUMNS),
        sa.Column("notes", sa.Text(), nullable=True),
        *(sa.Column(column, sa.Numeric(), nullable=True) for column in COMPONENT_COLUMNS),
        sa.Column("financial_status", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("date_closed", sa.Date(), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("recovered_cost", sa.Numeric(), nullable=True),
        sa.Column("avoided_cost", sa.Numeric(), nullable=True),
        sa.Column("source", sa.Text(), server_default=sa.text("'manual'"), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=True),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_cost_records"),
        sa.ForeignKeyConstraint(
            ["area_id"], ["safety.areas.id"], name="fk_cost_records_area", ondelete="RESTRICT"
        ),
        _check(
            RECORDS,
            "coq_class",
            "coq_class IN ('prevention', 'appraisal', 'internal_failure', 'external_failure')",
        ),
        _check(
            RECORDS,
            "category_code",
            "category_code ~ '^[a-z_]+\\.[a-z_]+$' "
            "AND split_part(category_code, '.', 1) = coq_class",
        ),
        _check(
            RECORDS,
            "financial_status",
            "financial_status IN ('potential', 'validating', 'confirmed', 'closed')",
        ),
        _check(
            RECORDS,
            "status",
            "status IN ('open', 'under_review', 'action_required', 'monitoring', 'closed')",
        ),
        _check(RECORDS, "source", "source IN ('manual', 'legacy_import')"),
        _check(
            RECORDS, "record_date", "record_date BETWEEN DATE '2000-01-01' AND DATE '2100-12-31'"
        ),
        _check(RECORDS, "title", "btrim(title) <> '' AND char_length(title) <= 200"),
        _check(
            RECORDS, "description", "btrim(description) <> '' AND char_length(description) <= 4000"
        ),
        *(_check(RECORDS, c, _optional_text(c, 200)) for c in IDENTIFICATION_COLUMNS),
        _check(RECORDS, "notes", _optional_text("notes", 4000)),
        _check(RECORDS, "resolution_notes", _optional_text("resolution_notes", 4000)),
        *(_check(RECORDS, c, f"{c} >= 0") for c in MONEY_COLUMNS),
        _check(RECORDS, "area_required", "area_id IS NOT NULL OR source = 'legacy_import'"),
        _check(RECORDS, "closed_has_date", "(status = 'closed') = (date_closed IS NOT NULL)"),
        _check(
            RECORDS, "date_closed_after_date", "date_closed IS NULL OR date_closed >= record_date"
        ),
        _check(
            RECORDS,
            "source_key",
            "source_key IS NULL OR (btrim(source_key) <> '' AND char_length(source_key) <= 200)",
        ),
        _check(RECORDS, "version", "version >= 1"),
        schema=QUALITY,
    )
    op.create_index(
        "uq_cost_records_source_key",
        RECORDS,
        ["source_key"],
        unique=True,
        schema=QUALITY,
        postgresql_where=sa.text("source_key IS NOT NULL"),
    )
    op.create_index("ix_cost_records_record_date", RECORDS, ["record_date"], schema=QUALITY)
    op.create_index(
        "ix_cost_records_class_date", RECORDS, ["coq_class", "record_date"], schema=QUALITY
    )
    op.create_index(
        "ix_cost_records_area_date", RECORDS, ["area_id", "record_date"], schema=QUALITY
    )

    op.create_table(
        REFERENCES,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("record_id", sa.BigInteger(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        *_audit_columns(updated=False),
        sa.PrimaryKeyConstraint("id", name="pk_cost_record_references"),
        sa.ForeignKeyConstraint(
            ["record_id"],
            [f"{QUALITY}.{RECORDS}.id"],
            name="fk_cost_record_references_record",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "record_id",
            "target_type",
            "target_key",
            name="uq_cost_record_references_record_id_target_type_target_key",
        ),
        _check(REFERENCES, "target_type", "target_type ~ '^[a-z_]+(\\.[a-z_]+)*$'"),
        _check(
            REFERENCES,
            "target_key",
            "btrim(target_key) <> '' AND char_length(target_key) <= 200",
        ),
        _check(REFERENCES, "label", _optional_text("label", 200)),
        schema=QUALITY,
    )
    op.create_index(
        "ix_cost_record_references_target",
        REFERENCES,
        ["target_type", "target_key"],
        schema=QUALITY,
    )


# Quality Cost records would be lost by a downgrade.
DOWNGRADE_GUARD = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM {QUALITY}.{RECORDS}) THEN
            RAISE EXCEPTION 'Cannot downgrade: Quality Cost records exist';
        END IF;
    END
    $$
"""


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_GUARD))
    op.drop_table(REFERENCES, schema=QUALITY)
    op.drop_table(RECORDS, schema=QUALITY)
