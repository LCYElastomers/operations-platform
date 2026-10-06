"""Safety monthly metrics.

Values are stored one row per (category, year, month). The Jan-Dec grid shown
to users is presentation only; YTD and section totals are calculated from
these rows and never stored.

A missing row means the month is unreported, which is distinct from a stored
0. Clearing a cell deletes its row; the platform audit trail
(core.audit_events) keeps the previous value.

Sections group categories into the blocks of a Safety function
(``metric_set``, e.g. "incidents" for Incident & Near Miss). Codes are stable
identifiers; names and display order may change.
"""

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SAFETY_SCHEMA = "safety"

MIN_REPORTING_YEAR = 2000
MAX_REPORTING_YEAR = 2100
# Unique identity of a monthly value (explicit name: the generated one exceeds 63 chars).
MONTHLY_VALUE_IDENTITY_CONSTRAINT = "uq_monthly_metric_values_category_year_month"


class MetricSection(Base):
    __tablename__ = "metric_sections"
    __table_args__ = (
        UniqueConstraint("metric_set", "code"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    metric_set: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MetricCategory(Base):
    __tablename__ = "metric_categories"
    __table_args__ = (
        UniqueConstraint("section_id", "code"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    section_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(MetricSection.id, name="fk_metric_categories_section"), nullable=False
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MonthlyMetricValue(Base):
    __tablename__ = "monthly_metric_values"
    __table_args__ = (
        UniqueConstraint(
            "category_id",
            "reporting_year",
            "reporting_month",
            name=MONTHLY_VALUE_IDENTITY_CONSTRAINT,
        ),
        CheckConstraint("reporting_month BETWEEN 1 AND 12", name="reporting_month"),
        CheckConstraint(
            f"reporting_year BETWEEN {MIN_REPORTING_YEAR} AND {MAX_REPORTING_YEAR}",
            name="reporting_year",
        ),
        CheckConstraint("value >= 0", name="value_non_negative"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    category_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(MetricCategory.id, name="fk_monthly_metric_values_category"),
        nullable=False,
    )
    reporting_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reporting_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
