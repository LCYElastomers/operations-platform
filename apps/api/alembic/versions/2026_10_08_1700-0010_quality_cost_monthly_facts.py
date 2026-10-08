"""quality cost monthly facts

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-08 17:00:00

Schema only; seeds nothing and changes no existing table.

- ``quality.cost_monthly_facts``: the monthly Cost of Quality inputs (scrap and
  off-spec quantities and loss rates, customer complaint cost lines, sales
  revenue), one row per reporting month. Costs, totals and percentages are
  calculated by the API, never stored. Rows are loaded with
  ``python -m app.quality.cost.legacy_import`` from a reviewed mapping, never by
  this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUALITY = "quality"
FACTS = "cost_monthly_facts"
AMOUNT_COLUMNS = (
    "total_production_lbs",
    "scrap_produced_lbs",
    "offspec_produced_lbs",
    "scrap_loss_per_lb",
    "offspec_loss_per_lb",
    "returned_product_lbs",
    "outbound_freight",
    "return_freight",
    "warehousing_handling",
    "lab_investigation",
    "customer_credit_penalty",
    "complaint_rework_cost",
    "sales_revenue",
)


def upgrade() -> None:
    op.create_table(
        FACTS,
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("reporting_year", sa.SmallInteger(), nullable=False),
        sa.Column("reporting_month", sa.SmallInteger(), nullable=False),
        sa.Column("total_production_lbs", sa.Numeric(), nullable=True),
        sa.Column("scrap_produced_lbs", sa.Numeric(), nullable=True),
        sa.Column("offspec_produced_lbs", sa.Numeric(), nullable=True),
        sa.Column("scrap_loss_per_lb", sa.Numeric(), nullable=True),
        sa.Column("offspec_loss_per_lb", sa.Numeric(), nullable=True),
        sa.Column("complaint_count", sa.Integer(), nullable=True),
        sa.Column("returned_product_lbs", sa.Numeric(), nullable=True),
        sa.Column("outbound_freight", sa.Numeric(), nullable=True),
        sa.Column("return_freight", sa.Numeric(), nullable=True),
        sa.Column("warehousing_handling", sa.Numeric(), nullable=True),
        sa.Column("lab_investigation", sa.Numeric(), nullable=True),
        sa.Column("customer_credit_penalty", sa.Numeric(), nullable=True),
        sa.Column("complaint_rework_cost", sa.Numeric(), nullable=True),
        sa.Column("sales_revenue", sa.Numeric(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_cost_monthly_facts"),
        sa.UniqueConstraint(
            "reporting_year",
            "reporting_month",
            name="uq_cost_monthly_facts_reporting_year_reporting_month",
        ),
        # op.f(): the names are final; the "ck" naming convention must not prefix them again.
        sa.CheckConstraint(
            "reporting_year BETWEEN 2000 AND 2100",
            name=op.f("ck_cost_monthly_facts_reporting_year"),
        ),
        sa.CheckConstraint(
            "reporting_month BETWEEN 1 AND 12", name=op.f("ck_cost_monthly_facts_reporting_month")
        ),
        sa.CheckConstraint(
            "complaint_count >= 0", name=op.f("ck_cost_monthly_facts_complaint_count")
        ),
        *(
            sa.CheckConstraint(f"{column} >= 0", name=op.f(f"ck_cost_monthly_facts_{column}"))
            for column in AMOUNT_COLUMNS
        ),
        sa.CheckConstraint("btrim(source) <> ''", name=op.f("ck_cost_monthly_facts_source")),
        schema=QUALITY,
    )


# Imported Cost of Quality figures would be lost by a downgrade.
DOWNGRADE_GUARD = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM {QUALITY}.{FACTS}) THEN
            RAISE EXCEPTION 'Cannot downgrade: Cost of Quality figures exist';
        END IF;
    END
    $$
"""


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_GUARD))
    op.drop_table(FACTS, schema=QUALITY)
