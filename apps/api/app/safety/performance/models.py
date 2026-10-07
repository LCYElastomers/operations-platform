"""Safety Performance: monthly worked hours and pre-platform annual history.

Rates (TRIR, First Aid, LOPC, Property & Equipment Damage) are calculated on
request from these hours and the monthly Safety metric counts. No rate, YTD
total or rolling total is stored.

A month without a ``performance_hours`` row is not reported. Closing a month
confirms that its event counts are complete, so an absent count in a closed
month is a zero; an open month never contributes to a rate.
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Identity,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.safety.models import MAX_REPORTING_YEAR, MIN_REPORTING_YEAR, SAFETY_SCHEMA

HOURS_PRECISION = 10
HOURS_SCALE = 2
MAX_SOURCE_LENGTH = 500
HOURS_IDENTITY_CONSTRAINT = "uq_performance_hours_year_month"


class PerformanceHours(Base):
    """Worked hours for one calendar month.

    ``hourly_hours`` and ``salary_hours`` are an optional breakdown; when both
    are given they add up to ``total_hours``.
    """

    __tablename__ = "performance_hours"
    __table_args__ = (
        UniqueConstraint("reporting_year", "reporting_month", name=HOURS_IDENTITY_CONSTRAINT),
        CheckConstraint(
            f"reporting_year BETWEEN {MIN_REPORTING_YEAR} AND {MAX_REPORTING_YEAR}",
            name="reporting_year",
        ),
        CheckConstraint("reporting_month BETWEEN 1 AND 12", name="reporting_month"),
        CheckConstraint("total_hours >= 0", name="total_hours"),
        CheckConstraint("hourly_hours IS NULL OR hourly_hours >= 0", name="hourly_hours"),
        CheckConstraint("salary_hours IS NULL OR salary_hours >= 0", name="salary_hours"),
        CheckConstraint(
            "hourly_hours IS NULL OR salary_hours IS NULL "
            "OR hourly_hours + salary_hours = total_hours",
            name="breakdown_total",
        ),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    reporting_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reporting_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    total_hours: Mapped[Decimal] = mapped_column(
        Numeric(HOURS_PRECISION, HOURS_SCALE), nullable=False
    )
    hourly_hours: Mapped[Decimal | None] = mapped_column(Numeric(HOURS_PRECISION, HOURS_SCALE))
    salary_hours: Mapped[Decimal | None] = mapped_column(Numeric(HOURS_PRECISION, HOURS_SCALE))
    month_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)


class PerformanceAnnualLegacy(Base):
    """Annual recordables and worked hours for a year before monthly records.

    Used for the annual TRIR history only, and only for a year that has no
    ``performance_hours`` rows. ``source`` cites the workbook cells.
    """

    __tablename__ = "performance_annual_legacy"
    __table_args__ = (
        UniqueConstraint("reporting_year"),
        CheckConstraint(
            f"reporting_year BETWEEN {MIN_REPORTING_YEAR} AND {MAX_REPORTING_YEAR}",
            name="reporting_year",
        ),
        CheckConstraint("recordables >= 0", name="recordables"),
        CheckConstraint("total_hours > 0", name="total_hours"),
        CheckConstraint(
            "source = btrim(source) AND source <> '' "
            f"AND char_length(source) <= {MAX_SOURCE_LENGTH}",
            name="source",
        ),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    reporting_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    recordables: Mapped[int] = mapped_column(Integer, nullable=False)
    total_hours: Mapped[Decimal] = mapped_column(
        Numeric(HOURS_PRECISION, HOURS_SCALE), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
