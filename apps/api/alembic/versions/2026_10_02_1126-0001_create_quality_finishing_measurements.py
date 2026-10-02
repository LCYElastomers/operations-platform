"""create quality finishing_measurements

Revision ID: 0001
Revises:
Create Date: 2026-10-02 11:26:39.197409

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "quality"
TABLE = "finishing_measurements"


def upgrade() -> None:
    # Only create the schema when missing, so a DBA can pre-create it for a
    # role that lacks CREATE on the database.
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = '{SCHEMA}') THEN
                    CREATE SCHEMA {SCHEMA};
                END IF;
            END
            $$
            """
        )
    )

    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source_date", sa.Date(), nullable=False),
        sa.Column("campaign_no", sa.Text(), nullable=True),
        sa.Column("lot", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("product", sa.Text(), nullable=True),
        sa.Column("avg_moisture", sa.Numeric(), nullable=True),
        sa.Column("avg_color", sa.Numeric(), nullable=True),
        sa.Column("avg_combined_bd", sa.Numeric(), nullable=True),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("source_row_hash", sa.Text(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_finishing_measurements"),
        sa.UniqueConstraint(
            "source_system",
            "source_row_hash",
            name="uq_finishing_measurements_source_system_source_row_hash",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_finishing_measurements_source_date_desc",
        TABLE,
        [sa.text("source_date DESC"), sa.text("id DESC")],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_finishing_measurements_product_source_date",
        TABLE,
        ["product", sa.text("source_date DESC")],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_finishing_measurements_product_lot",
        TABLE,
        ["product", "lot"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_finishing_measurements_product_lot", table_name=TABLE, schema=SCHEMA)
    op.drop_index(
        "ix_finishing_measurements_product_source_date", table_name=TABLE, schema=SCHEMA
    )
    op.drop_index("ix_finishing_measurements_source_date_desc", table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)

    # Drop the schema only if this role owns it and nothing else lives in it.
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_namespace n
                    WHERE n.nspname = '{SCHEMA}'
                      AND pg_get_userbyid(n.nspowner) = current_user
                ) AND NOT EXISTS (
                    SELECT 1 FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = '{SCHEMA}'
                ) THEN
                    DROP SCHEMA {SCHEMA};
                END IF;
            END
            $$
            """
        )
    )
