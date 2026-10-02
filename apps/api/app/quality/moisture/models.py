import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Identity,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

QUALITY_SCHEMA = "quality"
# Persistence identity of a source row (named by the metadata naming convention).
SOURCE_IDENTITY_CONSTRAINT = "uq_finishing_measurements_source_system_source_row_hash"


class FinishingMeasurement(Base):
    """One row of the Access finishing/moisture query, stored as received.

    Measurements are unconstrained NUMERIC so source values keep their exact
    decimal representation; NULL means the source value was missing and is
    distinct from 0. Identifiers are text. No specification limits or quality
    classifications are stored here.
    """

    __tablename__ = "finishing_measurements"
    __table_args__ = (
        # Idempotent ingestion: a source row is stored at most once per source system.
        UniqueConstraint("source_system", "source_row_hash"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    campaign_no: Mapped[str | None] = mapped_column(Text)
    lot: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    product: Mapped[str | None] = mapped_column(Text)
    avg_moisture: Mapped[Decimal | None] = mapped_column(Numeric)
    avg_color: Mapped[Decimal | None] = mapped_column(Numeric)
    avg_combined_bd: Mapped[Decimal | None] = mapped_column(Numeric)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_row_hash: Mapped[str] = mapped_column(Text, nullable=False)
    synced_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# Recent records (newest first; id breaks ties within a day).
Index(
    "ix_finishing_measurements_source_date_desc",
    FinishingMeasurement.source_date.desc(),
    FinishingMeasurement.id.desc(),
)
Index(
    "ix_finishing_measurements_product_source_date",
    FinishingMeasurement.product,
    FinishingMeasurement.source_date.desc(),
)
Index(
    "ix_finishing_measurements_product_lot",
    FinishingMeasurement.product,
    FinishingMeasurement.lot,
)
