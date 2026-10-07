"""Safety Observations: one row per observation.

Every total (safe, unsafe, act, condition, per category, per month) is counted
from these rows and never stored, so the figures always agree with each other.
Historical workbook tallies are not observations; they are kept as legacy
aggregate metrics (metric set ``observations_legacy``) and never mixed in.
"""

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.safety.models import SAFETY_SCHEMA

OUTCOMES = ("safe", "unsafe")
KINDS = ("act", "condition")
EARLIEST_OBSERVED_ON = dt.date(2000, 1, 1)
MAX_AREA_LOCATION_LENGTH = 200
MAX_NOTE_LENGTH = 2000


def _optional_text_check(column: str, max_length: int) -> CheckConstraint:
    # Optional text is NULL or non-blank, never an empty string.
    return CheckConstraint(
        f"{column} IS NULL OR (btrim({column}) <> '' AND char_length({column}) <= {max_length})",
        name=column,
    )


class ObservationCategory(Base):
    __tablename__ = "observation_categories"
    __table_args__ = (UniqueConstraint("code"), {"schema": SAFETY_SCHEMA})

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        CheckConstraint("outcome IN ('safe', 'unsafe')", name="outcome"),
        CheckConstraint("kind IN ('act', 'condition')", name="kind"),
        CheckConstraint(
            f"observed_on >= DATE '{EARLIEST_OBSERVED_ON.isoformat()}'", name="observed_on"
        ),
        _optional_text_check("area_location", MAX_AREA_LOCATION_LENGTH),
        _optional_text_check("description", MAX_NOTE_LENGTH),
        _optional_text_check("corrective_action", MAX_NOTE_LENGTH),
        {"schema": SAFETY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    observed_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(ObservationCategory.id, name="fk_observations_category"),
        nullable=False,
    )
    area_location: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    corrective_action: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)


Index("ix_observations_observed_on", Observation.observed_on)
Index("ix_observations_category_id", Observation.category_id)
