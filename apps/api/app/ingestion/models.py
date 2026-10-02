import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Identity,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CORE_SCHEMA = "core"

BATCH_STATUSES = ("received", "accepted", "accepted_with_rejections", "rejected", "failed")
COMPLETED_STATUSES = frozenset({"accepted", "accepted_with_rejections", "rejected"})


class IngestionBatch(Base):
    """Audit record of one ingestion batch: who sent it, when, and the outcome.

    Holds metadata and counts only. Request payloads, row values, and
    credentials are never stored here. ``request_digest`` is a SHA-256 of the
    canonical request, used to recognise an exact resubmission of a batch ID.

    Count columns are NULL when unknown (for example duplicates in a failed
    attempt) and 0 only when the count is known to be zero.
    """

    __tablename__ = "ingestion_batches"
    __table_args__ = (
        UniqueConstraint("source_system", "batch_id"),
        CheckConstraint(
            "status IN ('received', 'accepted', 'accepted_with_rejections', 'rejected', 'failed')",
            name="status",
        ),
        CheckConstraint(
            "(window_start IS NULL) = (window_end IS NULL)"
            " AND (window_start IS NULL OR window_start <= window_end)",
            name="window",
        ),
        {"schema": CORE_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    batch_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    connector_id: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    received_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    inserted_rows: Mapped[int | None] = mapped_column(Integer)
    duplicate_rows: Mapped[int | None] = mapped_column(Integer)
    rejected_rows: Mapped[int | None] = mapped_column(Integer)
    restored_rows: Mapped[int | None] = mapped_column(Integer)
    superseded_rows: Mapped[int | None] = mapped_column(Integer)
    # Authoritative source-date window declared by the batch, if any.
    window_start: Mapped[dt.date | None] = mapped_column(Date)
    window_end: Mapped[dt.date | None] = mapped_column(Date)
    window_applied: Mapped[bool | None] = mapped_column(Boolean)
    request_digest: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
