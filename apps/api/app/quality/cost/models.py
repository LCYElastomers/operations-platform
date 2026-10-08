"""Monthly Cost of Quality inputs (migration 0010).

One row per reporting month from the approved COQ workbook mapping: the
production and scrap / off-spec quantities with their loss rates (internal
failure), the customer complaint cost lines (external failure), and sales
revenue. Every cost, total and percentage is calculated from these inputs by
``app.quality.cost.service`` and never stored.

Prevention and appraisal costs are not recorded by the source and have no
columns. Null is blank in the source (not reported), distinct from a recorded 0.
Rows come from a reviewed import mapping; nothing here is edited through the
application.
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Identity,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.quality.moisture.models import QUALITY_SCHEMA

MIN_REPORTING_YEAR = 2000
MAX_REPORTING_YEAR = 2100

# Non-negative numeric inputs, in column order.
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


class CostMonthlyFact(Base):
    __tablename__ = "cost_monthly_facts"
    __table_args__ = (
        UniqueConstraint("reporting_year", "reporting_month"),
        CheckConstraint(
            f"reporting_year BETWEEN {MIN_REPORTING_YEAR} AND {MAX_REPORTING_YEAR}",
            name="reporting_year",
        ),
        CheckConstraint("reporting_month BETWEEN 1 AND 12", name="reporting_month"),
        CheckConstraint("complaint_count >= 0", name="complaint_count"),
        *(CheckConstraint(f"{column} >= 0", name=column) for column in AMOUNT_COLUMNS),
        CheckConstraint("btrim(source) <> ''", name="source"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    reporting_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reporting_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Internal failure inputs.
    total_production_lbs: Mapped[Decimal | None] = mapped_column(Numeric)
    scrap_produced_lbs: Mapped[Decimal | None] = mapped_column(Numeric)
    offspec_produced_lbs: Mapped[Decimal | None] = mapped_column(Numeric)
    scrap_loss_per_lb: Mapped[Decimal | None] = mapped_column(Numeric)
    offspec_loss_per_lb: Mapped[Decimal | None] = mapped_column(Numeric)
    # External failure (customer complaint) inputs, in US dollars.
    complaint_count: Mapped[int | None] = mapped_column(Integer)
    returned_product_lbs: Mapped[Decimal | None] = mapped_column(Numeric)
    outbound_freight: Mapped[Decimal | None] = mapped_column(Numeric)
    return_freight: Mapped[Decimal | None] = mapped_column(Numeric)
    warehousing_handling: Mapped[Decimal | None] = mapped_column(Numeric)
    lab_investigation: Mapped[Decimal | None] = mapped_column(Numeric)
    customer_credit_penalty: Mapped[Decimal | None] = mapped_column(Numeric)
    complaint_rework_cost: Mapped[Decimal | None] = mapped_column(Numeric)
    sales_revenue: Mapped[Decimal | None] = mapped_column(Numeric)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    # Mapping and source location; kept for audit, not returned by the API.
    source_reference: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
