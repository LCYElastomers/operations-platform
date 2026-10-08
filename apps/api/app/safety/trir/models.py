"""TRIR Experience historical facts (migration 0009).

One row per year from the approved TRIR history: the annual recordable and
Incident counts, the annual man-hours used as that year's denominator, the
industry benchmark, and the TRIR (and legacy TIR) the source displayed.

These are historical inputs and comparison values only. A year with monthly
hours in Safety Performance is calculated live from those hours and the
Incident & Near Miss recordables; its row here is kept only to reconcile the
legacy snapshot. Monthly hours are never stored here, and nothing here is
edited through the application: rows come from a reviewed import mapping.

Null is unknown, distinct from a recorded 0.
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
from app.safety.models import MAX_REPORTING_YEAR, MIN_REPORTING_YEAR, SAFETY_SCHEMA


class TrirAnnualFact(Base):
    __tablename__ = "trir_annual_facts"
    __table_args__ = (
        UniqueConstraint("reporting_year"),
        CheckConstraint(
            f"reporting_year BETWEEN {MIN_REPORTING_YEAR} AND {MAX_REPORTING_YEAR}",
            name="reporting_year",
        ),
        CheckConstraint("recordable_count >= 0", name="recordable_count"),
        CheckConstraint("incident_count >= 0", name="incident_count"),
        CheckConstraint("annual_man_hours > 0", name="annual_man_hours"),
        CheckConstraint("industry_benchmark >= 0", name="industry_benchmark"),
        CheckConstraint("legacy_displayed_trir >= 0", name="legacy_displayed_trir"),
        CheckConstraint("legacy_tir >= 0", name="legacy_tir"),
        CheckConstraint("btrim(source) <> ''", name="source"),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    reporting_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    recordable_count: Mapped[int | None] = mapped_column(Integer)
    incident_count: Mapped[int | None] = mapped_column(Integer)
    annual_man_hours: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    industry_benchmark: Mapped[Decimal | None] = mapped_column(Numeric)
    benchmark_source: Mapped[str | None] = mapped_column(Text)
    # Full precision as the source holds it; rounding is for display only.
    legacy_displayed_trir: Mapped[Decimal | None] = mapped_column(Numeric)
    legacy_tir: Mapped[Decimal | None] = mapped_column(Numeric)
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
