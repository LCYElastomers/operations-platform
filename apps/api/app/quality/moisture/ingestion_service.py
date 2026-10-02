"""Batch ingestion of finishing measurements.

Processing a batch:

1. Validate rows (no database). Invalid rows are rejected individually.
2. Claim: record the batch in core.ingestion_batches in its own short
   transaction, so even attempts that later fail leave an audit record.
3. Apply: in one transaction, lock the batch record, write measurement rows,
   and complete the audit record. Data and audit outcome commit together.
4. On a database failure, mark the batch failed in a separate transaction
   (best effort; impossible if the database itself is unreachable).

Identity versus content: ``source_row_hash`` identifies a content version.
Corrections are recognised only through an explicit identity:

- rows carrying ``sourceRecordId``: the new version of a record supersedes
  its current version (strategy A);
- batches declaring ``reconciliationWindow``: the batch is the complete set of
  rows for that source-date range, so current rows in the range that are not
  in the batch are superseded (strategy B).

Without either, rows are appended idempotently and never supersede anything.
Nothing is deleted; superseded versions remain for history.
"""

import datetime as dt
import hashlib
import json
import logging
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import DatabaseNotConfiguredError
from app.ingestion.audit import BatchAuditRepository
from app.ingestion.models import COMPLETED_STATUSES, IngestionBatch
from app.quality.moisture.ingestion import to_measurement_values
from app.quality.moisture.ingestion_schemas import (
    ROW_FIELD_ALIASES,
    FieldIssue,
    FinishingBatchIn,
    FinishingRowIn,
    IngestionResult,
    ReconciliationWindow,
    RowRejection,
)
from app.quality.moisture.repository import FinishingMeasurementWriter

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]

MAX_REPORTED_REJECTIONS = 100
_MAX_FIELD_NAME_LENGTH = 64
_DATABASE_ERRORS = (SQLAlchemyError, DatabaseNotConfiguredError)


class IngestionDatabaseError(RuntimeError):
    """The batch could not be stored. Nothing from the batch was committed."""


class BatchConflictError(RuntimeError):
    """The batch ID was already used with different content or by another connector."""


class StaleBatchError(RuntimeError):
    """Data from a later extraction has already been applied for this batch's scope."""


@dataclass(frozen=True)
class _Outcome:
    inserted: int
    duplicates: int
    restored: int
    superseded: int
    window_applied: bool | None


# Validation ---------------------------------------------------------------------


def _field_issue(error: Any) -> FieldIssue:
    location = error.get("loc") or ()
    field = str(location[0])[:_MAX_FIELD_NAME_LENGTH] if location else None
    # Only the message is returned; pydantic's "input" would echo submitted values.
    return FieldIssue(field=field, message=error["msg"])


def validate_rows(
    rows: Sequence[Any],
    *,
    source_system: str,
    synced_at: dt.datetime,
    window: ReconciliationWindow | None = None,
) -> tuple[list[dict[str, Any]], list[RowRejection]]:
    """Split rows into insertable values and rejections (by zero-based row index)."""
    accepted: dict[int, dict[str, Any]] = {}
    rejections: dict[int, RowRejection] = {}
    for index, raw in enumerate(rows):
        try:
            row = FinishingRowIn.model_validate(raw)
        except ValidationError as error:
            issues = [_field_issue(e) for e in error.errors(include_input=False)]
            rejections[index] = RowRejection(row_index=index, errors=issues)
            continue

        if window is not None and not window.contains(row.source_date):
            issue = FieldIssue(field="sourceDate", message="is outside the reconciliation window")
            rejections[index] = RowRejection(row_index=index, errors=[issue])
            continue

        values = to_measurement_values(
            row.to_source_row(),
            source_system=source_system,
            synced_at=synced_at,
            record_key=row.source_record_id,
        )
        if row.source_row_hash is not None and row.source_row_hash != values["source_row_hash"]:
            issue = FieldIssue(field="sourceRowHash", message="does not match the row values")
            rejections[index] = RowRejection(row_index=index, errors=[issue])
            continue
        accepted[index] = values

    # A record cannot have two different versions in one batch.
    hashes_by_key: dict[str, set[str]] = defaultdict(set)
    for values in accepted.values():
        if values["source_record_key"] is not None:
            hashes_by_key[values["source_record_key"]].add(values["source_row_hash"])
    conflicting = {key for key, hashes in hashes_by_key.items() if len(hashes) > 1}
    for index in [i for i, v in accepted.items() if v["source_record_key"] in conflicting]:
        del accepted[index]
        issue = FieldIssue(
            field="sourceRecordId", message="appears more than once with different values"
        )
        rejections[index] = RowRejection(row_index=index, errors=[issue])

    return list(accepted.values()), [rejections[i] for i in sorted(rejections)]


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal | dt.date):
        return str(value)
    raise TypeError(f"Unsupported value in request: {type(value).__name__}")


def request_digest(batch: FinishingBatchIn) -> str:
    """SHA-256 of the canonical request, to recognise an exact resubmission."""
    window = batch.reconciliation_window
    document = {
        "extractedAt": batch.extracted_at.isoformat(),
        "window": [window.source_date_from, window.source_date_to] if window else None,
        "rows": batch.rows,
    }
    payload = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_default
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Logging ------------------------------------------------------------------------


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


# Processing --------------------------------------------------------------------


def _apply(
    session: Session,
    batch: FinishingBatchIn,
    values: list[dict[str, Any]],
    rejections: list[RowRejection],
    record: IngestionBatch,
    at: dt.datetime,
) -> _Outcome:
    writer = FinishingMeasurementWriter(session)
    source_system = batch.source_system
    window = batch.reconciliation_window
    writer.lock_source_system(source_system)

    if window is not None and BatchAuditRepository(session).newer_window_applied(
        source_system=source_system,
        window_start=window.source_date_from,
        window_end=window.source_date_to,
        extracted_at=batch.extracted_at,
    ):
        raise StaleBatchError
    keyed = {
        v["source_record_key"]: v["source_row_hash"]
        for v in values
        if v["source_record_key"] is not None
    }
    if writer.newer_key_versions_exist(source_system, list(keyed), batch.extracted_at):
        raise StaleBatchError

    # A window is authoritative only if every row in it was accepted.
    window_applied = None if window is None else not rejections

    unique: dict[str, dict[str, Any]] = {}
    for v in values:
        unique.setdefault(v["source_row_hash"], {**v, "ingestion_batch_id": record.id})
    stored = writer.versions_by_hash(source_system, list(unique))

    to_supersede: set[int] = set()
    if window is not None and window_applied:
        to_supersede.update(
            version.id
            for version in writer.current_in_window(
                source_system, window.source_date_from, window.source_date_to
            )
            if version.source_row_hash not in unique
        )
    to_supersede.update(
        version.id
        for version in writer.current_by_keys(source_system, list(keyed))
        if version.source_row_hash != keyed[version.source_record_key]
    )
    superseded = writer.supersede(sorted(to_supersede), batch_pk=record.id, at=at)

    # Earlier versions become current again only under an explicit identity.
    to_restore = [
        stored[h].id
        for h, v in unique.items()
        if h in stored
        and not stored[h].is_current
        and (window_applied or v["source_record_key"] is not None)
    ]
    restored = writer.restore(to_restore, batch_pk=record.id)
    inserted = writer.insert_new([v for h, v in unique.items() if h not in stored])

    return _Outcome(
        inserted=inserted,
        duplicates=len(values) - inserted - restored,
        restored=restored,
        superseded=superseded,
        window_applied=window_applied,
    )


def _status(valid_rows: int, rejected_rows: int) -> str:
    if not rejected_rows:
        return "accepted"
    return "accepted_with_rejections" if valid_rows else "rejected"


def _result(
    batch: FinishingBatchIn,
    record: IngestionBatch,
    rejections: list[RowRejection],
    *,
    replayed: bool,
) -> IngestionResult:
    return IngestionResult(
        batch_id=batch.batch_id,
        source_system=batch.source_system,
        status=record.status,
        received_rows=record.received_rows,
        inserted_rows=record.inserted_rows or 0,
        duplicate_rows=record.duplicate_rows or 0,
        rejected_rows=record.rejected_rows or 0,
        restored_rows=record.restored_rows or 0,
        superseded_rows=record.superseded_rows or 0,
        window_applied=record.window_applied,
        replayed=replayed,
        rejections=rejections[:MAX_REPORTED_REJECTIONS],
        rejections_truncated=len(rejections) > MAX_REPORTED_REJECTIONS,
    )


def _mark_failed(session_factory: SessionFactory, batch: FinishingBatchIn, error_code: str) -> None:
    try:
        with session_factory() as session, session.begin():
            BatchAuditRepository(session).mark_failed(
                source_system=batch.source_system,
                batch_id=batch.batch_id,
                error_code=error_code,
                at=dt.datetime.now(dt.UTC),
            )
    except _DATABASE_ERRORS as error:
        _log(
            logging.ERROR,
            result="audit_write_failed",
            batch_id=batch.batch_id,
            source_system=batch.source_system,
            error_type=type(error).__name__,
        )


def ingest_batch(
    batch: FinishingBatchIn,
    session_factory: SessionFactory,
    *,
    connector_id: str,
    received_at: dt.datetime | None = None,
) -> IngestionResult:
    received_at = received_at or dt.datetime.now(dt.UTC)
    window = batch.reconciliation_window
    values, rejections = validate_rows(
        batch.rows, source_system=batch.source_system, synced_at=received_at, window=window
    )
    received = len(batch.rows)
    context = {
        "batch_id": batch.batch_id,
        "source_system": batch.source_system,
        "connector": connector_id,
    }

    def database_failure(stage: str, error: Exception) -> IngestionDatabaseError:
        # The exception text can contain SQL parameters, so only its type is logged.
        _log(
            logging.ERROR,
            result="database_error",
            stage=stage,
            **context,
            received=received,
            error_type=type(error).__name__,
        )
        return IngestionDatabaseError("The batch was not stored")

    digest = request_digest(batch)
    try:
        with session_factory() as session, session.begin():
            first_attempt = BatchAuditRepository(session).claim(
                batch_id=batch.batch_id,
                source_system=batch.source_system,
                connector_id=connector_id,
                extracted_at=batch.extracted_at,
                received_at=received_at,
                received_rows=received,
                rejected_rows=len(rejections),
                window_start=window.source_date_from if window else None,
                window_end=window.source_date_to if window else None,
                request_digest=digest,
            )
    except _DATABASE_ERRORS as error:
        raise database_failure("claim", error) from error

    try:
        with session_factory() as session, session.begin():
            record = BatchAuditRepository(session).lock(batch.source_system, batch.batch_id)
            if record.request_digest != digest or record.connector_id != connector_id:
                raise BatchConflictError
            if record.status in COMPLETED_STATUSES:
                result = _result(batch, record, rejections, replayed=True)
                _log(logging.INFO, result="replayed", status=record.status, **context)
                return result
            if not first_attempt:
                record.attempt_count += 1

            outcome = _apply(session, batch, values, rejections, record, received_at)
            record.status = _status(len(values), len(rejections))
            record.inserted_rows = outcome.inserted
            record.duplicate_rows = outcome.duplicates
            record.rejected_rows = len(rejections)
            record.restored_rows = outcome.restored
            record.superseded_rows = outcome.superseded
            record.window_applied = outcome.window_applied
            record.error_code = None
            record.completed_at = dt.datetime.now(dt.UTC)
            result = _result(batch, record, rejections, replayed=False)
            attempt = record.attempt_count
    except BatchConflictError:
        _log(logging.WARNING, result="batch_id_conflict", **context)
        raise
    except StaleBatchError:
        _mark_failed(session_factory, batch, "stale_batch")
        _log(logging.WARNING, result="stale_batch", **context, received=received)
        raise
    except _DATABASE_ERRORS as error:
        _mark_failed(session_factory, batch, "database_error")
        raise database_failure("apply", error) from error

    _log(
        logging.WARNING if rejections else logging.INFO,
        result=result.status,
        **context,
        attempt=attempt,
        extracted_at=batch.extracted_at.isoformat(),
        window=f"{window.source_date_from}..{window.source_date_to}" if window else "-",
        window_applied=result.window_applied,
        received=received,
        inserted=result.inserted_rows,
        duplicates=result.duplicate_rows,
        restored=result.restored_rows,
        superseded=result.superseded_rows,
        rejected=result.rejected_rows,
        rejected_fields=_rejected_fields(rejections),
    )
    return result
