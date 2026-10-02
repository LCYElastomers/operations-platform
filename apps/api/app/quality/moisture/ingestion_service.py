"""Batch ingestion of finishing measurements.

Row validation happens before any database work. Valid rows are written in a
single transaction: either every new row in the batch is committed or none is.
Re-submitting rows is safe because (source_system, source_row_hash) is unique.
"""

import datetime as dt
import logging
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import DatabaseNotConfiguredError
from app.quality.moisture.ingestion import to_measurement_values
from app.quality.moisture.ingestion_schemas import (
    ROW_FIELD_ALIASES,
    FieldIssue,
    FinishingBatchIn,
    FinishingRowIn,
    IngestionResult,
    RowRejection,
)
from app.quality.moisture.repository import FinishingMeasurementWriter

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]

MAX_REPORTED_REJECTIONS = 100
_MAX_FIELD_NAME_LENGTH = 64


class IngestionDatabaseError(RuntimeError):
    """The batch could not be stored. Nothing from the batch was committed."""


def _field_issue(error: Any) -> FieldIssue:
    location = error.get("loc") or ()
    field = str(location[0])[:_MAX_FIELD_NAME_LENGTH] if location else None
    # Only the message is returned; pydantic's "input" would echo submitted values.
    return FieldIssue(field=field, message=error["msg"])


def validate_rows(
    rows: Sequence[Any], *, source_system: str, synced_at: dt.datetime
) -> tuple[list[dict[str, Any]], list[RowRejection]]:
    """Split rows into insertable values and rejections (by zero-based row index)."""
    accepted: list[dict[str, Any]] = []
    rejections: list[RowRejection] = []
    for index, raw in enumerate(rows):
        try:
            row = FinishingRowIn.model_validate(raw)
        except ValidationError as error:
            issues = [_field_issue(e) for e in error.errors(include_input=False)]
            rejections.append(RowRejection(row_index=index, errors=issues))
            continue

        values = to_measurement_values(
            row.to_source_row(), source_system=source_system, synced_at=synced_at
        )
        if row.source_row_hash is not None and row.source_row_hash != values["source_row_hash"]:
            issue = FieldIssue(field="sourceRowHash", message="does not match the row values")
            rejections.append(RowRejection(row_index=index, errors=[issue]))
            continue
        accepted.append(values)
    return accepted, rejections


def _rejected_fields(rejections: Sequence[RowRejection]) -> str:
    # Unknown field names come from the request, so they are not logged verbatim.
    counts = Counter(
        issue.field if issue.field in ROW_FIELD_ALIASES else "other"
        for rejection in rejections
        for issue in rejection.errors
    )
    return ",".join(f"{field}:{count}" for field, count in sorted(counts.items())) or "-"


def _log(level: int, **fields: Any) -> None:
    message = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.log(level, "event=finishing_ingestion %s", message, extra={"ingestion": fields})


def ingest_batch(
    batch: FinishingBatchIn,
    session_factory: SessionFactory,
    *,
    connector_id: str,
    received_at: dt.datetime | None = None,
) -> IngestionResult:
    synced_at = received_at or dt.datetime.now(dt.UTC)
    values, rejections = validate_rows(
        batch.rows, source_system=batch.source_system, synced_at=synced_at
    )
    received = len(batch.rows)

    inserted = 0
    if values:
        try:
            with session_factory() as session, session.begin():
                inserted = FinishingMeasurementWriter(session).insert_new(values)
        except (SQLAlchemyError, DatabaseNotConfiguredError) as error:
            # The exception text can contain SQL parameters, so only its type is logged.
            _log(
                logging.ERROR,
                result="database_error",
                batch_id=batch.batch_id,
                source_system=batch.source_system,
                connector=connector_id,
                received=received,
                valid=len(values),
                rejected=len(rejections),
                error_type=type(error).__name__,
            )
            raise IngestionDatabaseError("The batch was not stored") from error

    duplicates = len(values) - inserted
    if not rejections:
        status = "accepted"
    elif values:
        status = "accepted_with_rejections"
    else:
        status = "rejected"

    _log(
        logging.WARNING if rejections else logging.INFO,
        result=status,
        batch_id=batch.batch_id,
        source_system=batch.source_system,
        connector=connector_id,
        extracted_at=batch.extracted_at.isoformat(),
        received=received,
        inserted=inserted,
        duplicates=duplicates,
        rejected=len(rejections),
        rejected_fields=_rejected_fields(rejections),
    )
    return IngestionResult(
        batch_id=batch.batch_id,
        source_system=batch.source_system,
        status=status,
        received_rows=received,
        inserted_rows=inserted,
        duplicate_rows=duplicates,
        rejected_rows=len(rejections),
        rejections=rejections[:MAX_REPORTED_REJECTIONS],
        rejections_truncated=len(rejections) > MAX_REPORTED_REJECTIONS,
    )
