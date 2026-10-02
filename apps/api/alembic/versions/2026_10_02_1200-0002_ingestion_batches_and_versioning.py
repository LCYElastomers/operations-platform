"""ingestion batch audit and finishing measurement versioning

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-02 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CORE = "core"
QUALITY = "quality"
BATCHES = "ingestion_batches"
MEASUREMENTS = "finishing_measurements"


def upgrade() -> None:
    op.create_table(
        BATCHES,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("batch_id", sa.Text(), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("connector_id", sa.Text(), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("received_rows", sa.Integer(), nullable=False),
        sa.Column("inserted_rows", sa.Integer(), nullable=True),
        sa.Column("duplicate_rows", sa.Integer(), nullable=True),
        sa.Column("rejected_rows", sa.Integer(), nullable=True),
        sa.Column("restored_rows", sa.Integer(), nullable=True),
        sa.Column("superseded_rows", sa.Integer(), nullable=True),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column("window_applied", sa.Boolean(), nullable=True),
        sa.Column("request_digest", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_batches"),
        sa.UniqueConstraint(
            "source_system", "batch_id", name="uq_ingestion_batches_source_system_batch_id"
        ),
        sa.CheckConstraint(
            "status IN ('received', 'accepted', 'accepted_with_rejections', 'rejected', 'failed')",
            name="ck_ingestion_batches_status",
        ),
        sa.CheckConstraint(
            "(window_start IS NULL) = (window_end IS NULL)"
            " AND (window_start IS NULL OR window_start <= window_end)",
            name="ck_ingestion_batches_window",
        ),
        schema=CORE,
    )

    op.add_column(MEASUREMENTS, sa.Column("source_record_key", sa.Text()), schema=QUALITY)
    op.add_column(MEASUREMENTS, sa.Column("ingestion_batch_id", sa.BigInteger()), schema=QUALITY)
    op.add_column(
        MEASUREMENTS, sa.Column("superseded_at", sa.DateTime(timezone=True)), schema=QUALITY
    )
    op.add_column(
        MEASUREMENTS, sa.Column("superseded_by_batch_id", sa.BigInteger()), schema=QUALITY
    )
    op.create_foreign_key(
        "fk_finishing_measurements_ingestion_batch",
        MEASUREMENTS,
        BATCHES,
        ["ingestion_batch_id"],
        ["id"],
        source_schema=QUALITY,
        referent_schema=CORE,
    )
    op.create_foreign_key(
        "fk_finishing_measurements_superseded_by_batch",
        MEASUREMENTS,
        BATCHES,
        ["superseded_by_batch_id"],
        ["id"],
        source_schema=QUALITY,
        referent_schema=CORE,
    )
    op.create_index(
        "ix_finishing_measurements_current_record_key",
        MEASUREMENTS,
        ["source_system", "source_record_key"],
        unique=True,
        schema=QUALITY,
        postgresql_where=sa.text("source_record_key IS NOT NULL AND superseded_at IS NULL"),
    )
    op.create_index(
        "ix_finishing_measurements_current_source_date",
        MEASUREMENTS,
        ["source_system", "source_date"],
        schema=QUALITY,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    # Superseded versions would become indistinguishable from current rows.
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM {QUALITY}.{MEASUREMENTS} WHERE superseded_at IS NOT NULL
                ) THEN
                    RAISE EXCEPTION 'Cannot downgrade: superseded measurement versions exist';
                END IF;
            END
            $$
            """
        )
    )
    op.drop_index(
        "ix_finishing_measurements_current_source_date", table_name=MEASUREMENTS, schema=QUALITY
    )
    op.drop_index(
        "ix_finishing_measurements_current_record_key", table_name=MEASUREMENTS, schema=QUALITY
    )
    op.drop_constraint(
        "fk_finishing_measurements_superseded_by_batch",
        MEASUREMENTS,
        type_="foreignkey",
        schema=QUALITY,
    )
    op.drop_constraint(
        "fk_finishing_measurements_ingestion_batch",
        MEASUREMENTS,
        type_="foreignkey",
        schema=QUALITY,
    )
    op.drop_column(MEASUREMENTS, "superseded_by_batch_id", schema=QUALITY)
    op.drop_column(MEASUREMENTS, "superseded_at", schema=QUALITY)
    op.drop_column(MEASUREMENTS, "ingestion_batch_id", schema=QUALITY)
    op.drop_column(MEASUREMENTS, "source_record_key", schema=QUALITY)
    op.drop_table(BATCHES, schema=CORE)
