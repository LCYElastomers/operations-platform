"""Persistence of ingestion batch audit records (core.ingestion_batches)."""

import datetime as dt

from sqlalchemy import case, exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ingestion.models import COMPLETED_STATUSES, IngestionBatch

BATCH_IDENTITY_CONSTRAINT = "uq_ingestion_batches_source_system_batch_id"


class BatchAuditRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def claim(
        self,
        *,
        batch_id: str,
        source_system: str,
        connector_id: str,
        extracted_at: dt.datetime,
        received_at: dt.datetime,
        received_rows: int,
        rejected_rows: int,
        window_start: dt.date | None,
        window_end: dt.date | None,
        request_digest: str,
    ) -> bool:
        """Record that a batch arrived. Returns False if the batch ID already exists."""
        statement = (
            insert(IngestionBatch)
            .values(
                batch_id=batch_id,
                source_system=source_system,
                connector_id=connector_id,
                extracted_at=extracted_at,
                received_at=received_at,
                status="received",
                received_rows=received_rows,
                rejected_rows=rejected_rows,
                window_start=window_start,
                window_end=window_end,
                request_digest=request_digest,
            )
            .on_conflict_do_nothing(constraint=BATCH_IDENTITY_CONSTRAINT)
            .returning(IngestionBatch.id)
        )
        return self._session.execute(statement).first() is not None

    def lock(self, source_system: str, batch_id: str) -> IngestionBatch:
        """Load a batch record, holding a row lock until the transaction ends."""
        return self._session.scalars(
            select(IngestionBatch)
            .where(
                IngestionBatch.source_system == source_system,
                IngestionBatch.batch_id == batch_id,
            )
            .with_for_update()
        ).one()

    def newer_window_applied(
        self,
        *,
        source_system: str,
        window_start: dt.date,
        window_end: dt.date,
        extracted_at: dt.datetime,
    ) -> bool:
        """Whether an overlapping window from a later extraction has already been applied."""
        b = IngestionBatch
        return bool(
            self._session.scalar(
                select(
                    exists().where(
                        b.source_system == source_system,
                        b.status.in_(COMPLETED_STATUSES),
                        b.window_applied.is_(True),
                        b.window_start <= window_end,
                        b.window_end >= window_start,
                        b.extracted_at > extracted_at,
                    )
                )
            )
        )

    def mark_failed(
        self, *, source_system: str, batch_id: str, error_code: str, at: dt.datetime
    ) -> None:
        """Record a failed attempt. Nothing from the batch was committed, so
        written counts are 0; duplicates are unknown (NULL)."""
        b = IngestionBatch
        self._session.execute(
            update(b)
            .where(
                b.source_system == source_system,
                b.batch_id == batch_id,
                b.status.in_(("received", "failed")),
            )
            .values(
                status="failed",
                error_code=error_code,
                completed_at=at,
                inserted_rows=0,
                restored_rows=0,
                superseded_rows=0,
                duplicate_rows=None,
                window_applied=case((b.window_start.is_not(None), False), else_=None),
            )
        )
