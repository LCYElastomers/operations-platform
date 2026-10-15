"""safety import runs

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-15 12:00:00

Adds ``safety.import_runs``: a durable record of every Safety import ``plan``
and ``apply`` (importer, reviewed file name and SHA-256, initiator, start and
end, outcome, counts, messages, and the audit change set of an applied run).

Schema only; seeds nothing and changes no existing table. Imported records
stay in their own permanent tables; this table is their run history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFETY = "safety"
TABLE = "import_runs"

IMPORTERS = (
    "monthly_metrics",
    "behavior",
    "performance",
    "trir_history",
    "incident_records",
    "psm_pha",
)
STATUSES = ("running", "planned", "blocked", "applied", "nothing_to_apply", "failed")


def _in(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("importer", sa.Text(), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("source_file_name", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.Text(), nullable=False),
        sa.Column("initiated_by", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("inserted_count", sa.Integer(), nullable=True),
        sa.Column("updated_count", sa.Integer(), nullable=True),
        sa.Column("skipped_count", sa.Integer(), nullable=True),
        sa.Column("conflict_count", sa.Integer(), nullable=True),
        sa.Column("failed_count", sa.Integer(), nullable=True),
        sa.Column(
            "messages",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("change_set_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_import_runs"),
        sa.UniqueConstraint("run_id", name="uq_import_runs_run_id"),
        # op.f(): the names are final; the "ck" naming convention must not prefix them again.
        sa.CheckConstraint(f"importer IN ({_in(IMPORTERS)})", name=op.f("ck_import_runs_importer")),
        sa.CheckConstraint("command IN ('plan', 'apply')", name=op.f("ck_import_runs_command")),
        sa.CheckConstraint(f"status IN ({_in(STATUSES)})", name=op.f("ck_import_runs_status")),
        sa.CheckConstraint(
            "status IN ('running', 'planned', 'blocked', 'failed') OR command = 'apply'",
            name=op.f("ck_import_runs_apply_outcome"),
        ),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)", name=op.f("ck_import_runs_finished")
        ),
        sa.CheckConstraint(
            "status = 'applied' OR change_set_id IS NULL", name=op.f("ck_import_runs_change_set")
        ),
        sa.CheckConstraint(
            "inserted_count >= 0 AND updated_count >= 0 AND skipped_count >= 0 "
            "AND conflict_count >= 0 AND failed_count >= 0",
            name=op.f("ck_import_runs_counts"),
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_import_runs_source_sha256")
        ),
        sa.CheckConstraint(
            "btrim(source_file_name) <> ''", name=op.f("ck_import_runs_source_file_name")
        ),
        schema=SAFETY,
    )


# Import history would be lost by a downgrade.
DOWNGRADE_GUARD = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM {SAFETY}.{TABLE}) THEN
            RAISE EXCEPTION 'Cannot downgrade: Safety import runs exist';
        END IF;
    END
    $$
"""


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_GUARD))
    op.drop_table(TABLE, schema=SAFETY)
