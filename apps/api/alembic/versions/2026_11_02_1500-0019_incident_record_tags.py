"""incident record tags

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-02 15:00:00

Individual Incident and Near Miss records become the source of truth for the
derived monthly totals. A record carries record-level tags, one junction table
each (like ``safety.incident_record_classifications``):

- ``safety.incident_record_injury_causes``: Injury Cause categories
  (section ``injury_cause``); recorded only while the record is First Aid.
- ``safety.incident_record_body_parts``: Body Part categories (section
  ``body_part``); recorded only while the record is First Aid.
- ``safety.incident_record_event_causes``: Near-Miss Cause categories (section
  ``near_miss_cause``), for Incidents and Near Misses alike.

Every tag links to an existing ``safety.metric_categories`` row; no category
codes are created. A trigger checks the category belongs to the table's
section. Records are never deleted (they are voided), so every link is
ON DELETE RESTRICT. Creates tables only; no data is seeded or backfilled.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFETY = "safety"
RECORDS = "incident_records"
INCIDENTS = "incidents"

# (table, category column, section code of the category).
TAG_TABLES: list[tuple[str, str, str]] = [
    ("incident_record_injury_causes", "injury_cause_category_id", "injury_cause"),
    ("incident_record_body_parts", "body_part_category_id", "body_part"),
    ("incident_record_event_causes", "event_cause_category_id", "near_miss_cause"),
]


def upgrade() -> None:
    # Arguments: (category column, section code).
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {SAFETY}.incident_record_tag_rule() RETURNS trigger
            LANGUAGE plpgsql AS $$
            DECLARE
                v_category integer := (to_jsonb(NEW) ->> TG_ARGV[0])::integer;
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM {SAFETY}.metric_categories c
                    JOIN {SAFETY}.metric_sections s ON s.id = c.section_id
                    WHERE c.id = v_category
                      AND s.metric_set = '{INCIDENTS}'
                      AND s.code = TG_ARGV[1]
                ) THEN
                    RAISE EXCEPTION 'a record tag must be a % category', TG_ARGV[1]
                        USING ERRCODE = 'check_violation',
                              CONSTRAINT = 'ck_' || TG_TABLE_NAME || '_' || TG_ARGV[0];
                END IF;
                RETURN NEW;
            END
            $$
            """
        )
    )
    for table, column, section in TAG_TABLES:
        op.create_table(
            table,
            sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
            sa.Column("incident_record_id", sa.BigInteger(), nullable=False),
            sa.Column(column, sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("created_by", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
            sa.UniqueConstraint(
                "incident_record_id", column, name=f"uq_{table}_record_category"
            ),
            sa.ForeignKeyConstraint(
                ["incident_record_id"],
                [f"{SAFETY}.{RECORDS}.id"],
                name=f"fk_{table}_incident_record",
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                [column],
                [f"{SAFETY}.metric_categories.id"],
                name=f"fk_{table}_category",
                ondelete="RESTRICT",
            ),
            schema=SAFETY,
        )
        op.create_index(f"ix_{table}_category_id", table, [column], schema=SAFETY)
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_{table}_rule
                BEFORE INSERT OR UPDATE OF {column} ON {SAFETY}.{table}
                FOR EACH ROW
                EXECUTE FUNCTION {SAFETY}.incident_record_tag_rule('{column}', '{section}')
                """
            )
        )


# Record tags would be lost by a downgrade.
DOWNGRADE_GUARD = f"""
    DO $$
    BEGIN
        IF {" OR ".join(f"EXISTS (SELECT 1 FROM {SAFETY}.{table})" for table, _, _ in TAG_TABLES)}
        THEN
            RAISE EXCEPTION 'Cannot downgrade: incident record tags exist';
        END IF;
    END
    $$
"""


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_GUARD))
    for table, _, _ in TAG_TABLES:
        op.drop_table(table, schema=SAFETY)
    op.execute(sa.text(f"DROP FUNCTION {SAFETY}.incident_record_tag_rule()"))
