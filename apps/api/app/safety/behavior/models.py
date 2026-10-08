"""Incident & Near Miss Behavior: annual tag counts per Behavior category.

The source records Behavior only as annual category totals, so a count has a
reporting year and no month. A missing row is unreported, distinct from a
stored 0. Behavior values are tags (one incident may carry several), so they
are never required to add up to the Incident total. The Incident total used
as the denominator is read from the monthly metrics, never stored here.
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
from app.safety.models import MAX_REPORTING_YEAR, MIN_REPORTING_YEAR, SAFETY_SCHEMA

COUNT_IDENTITY_CONSTRAINT = "uq_annual_behavior_counts_category_year"


class BehaviorCategory(Base):
    __tablename__ = "behavior_categories"
    __table_args__ = (
        UniqueConstraint("code"),
        CheckConstraint("code ~ '^[a-z0-9_]{1,100}$'", name="code"),
        CheckConstraint(
            "name = btrim(name) AND name <> '' AND char_length(name) <= 200", name="name"
        ),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AnnualBehaviorCount(Base):
    __tablename__ = "annual_behavior_counts"
    __table_args__ = (
        UniqueConstraint("category_id", "reporting_year", name=COUNT_IDENTITY_CONSTRAINT),
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
        ForeignKey(
            BehaviorCategory.id, name="fk_annual_behavior_counts_category", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    reporting_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
