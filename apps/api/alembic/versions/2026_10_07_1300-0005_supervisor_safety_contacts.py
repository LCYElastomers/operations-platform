"""supervisor safety contacts

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07 13:00:00

Creates the Supervisor Safety Contacts program list and contact records. Seeds
nothing: no supervisor names, no contacts and no targets. Legacy workbook
counts are not contact records and are not imported here.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFETY = "safety"
SUPERVISORS = "contact_supervisors"
CONTACTS = "supervisor_safety_contacts"


def _audit_columns() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        SUPERVISORS,
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("participation_eligible", sa.Boolean(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_contact_supervisors"),
        # op.f(): the name is final; the "ck" naming convention must not prefix it again.
        sa.CheckConstraint(
            "display_name = btrim(display_name) AND display_name <> '' "
            "AND char_length(display_name) <= 100",
            name=op.f("ck_contact_supervisors_display_name"),
        ),
        sa.CheckConstraint(
            "effective_from >= DATE '2000-01-01'",
            name=op.f("ck_contact_supervisors_effective_from"),
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name=op.f("ck_contact_supervisors_effective_period"),
        ),
        sa.CheckConstraint(
            "active OR effective_to IS NOT NULL",
            name=op.f("ck_contact_supervisors_inactive_has_end"),
        ),
        schema=SAFETY,
    )
    op.create_index(
        "uq_contact_supervisors_display_name",
        SUPERVISORS,
        [sa.text("lower(display_name)")],
        unique=True,
        schema=SAFETY,
    )

    op.create_table(
        CONTACTS,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("contact_date", sa.Date(), nullable=False),
        sa.Column("supervisor_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_supervisor_safety_contacts"),
        sa.ForeignKeyConstraint(
            ["supervisor_id"],
            [f"{SAFETY}.{SUPERVISORS}.id"],
            name="fk_supervisor_safety_contacts_supervisor",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("request_id", name="uq_supervisor_safety_contacts_request_id"),
        sa.CheckConstraint(
            "contact_date >= DATE '2000-01-01'",
            name=op.f("ck_supervisor_safety_contacts_contact_date"),
        ),
        schema=SAFETY,
    )
    op.create_index(
        "ix_supervisor_safety_contacts_contact_date", CONTACTS, ["contact_date"], schema=SAFETY
    )
    op.create_index(
        "ix_supervisor_safety_contacts_supervisor_id", CONTACTS, ["supervisor_id"], schema=SAFETY
    )


def downgrade() -> None:
    # Entered contacts and the supervisor list would be lost.
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM {SAFETY}.{CONTACTS}) THEN
                    RAISE EXCEPTION 'Cannot downgrade: supervisor safety contacts exist';
                END IF;
                IF EXISTS (SELECT 1 FROM {SAFETY}.{SUPERVISORS}) THEN
                    RAISE EXCEPTION 'Cannot downgrade: contact supervisors exist';
                END IF;
            END
            $$
            """
        )
    )
    op.drop_index("ix_supervisor_safety_contacts_supervisor_id", table_name=CONTACTS, schema=SAFETY)
    op.drop_index("ix_supervisor_safety_contacts_contact_date", table_name=CONTACTS, schema=SAFETY)
    op.drop_table(CONTACTS, schema=SAFETY)
    op.drop_index("uq_contact_supervisors_display_name", table_name=SUPERVISORS, schema=SAFETY)
    op.drop_table(SUPERVISORS, schema=SAFETY)
