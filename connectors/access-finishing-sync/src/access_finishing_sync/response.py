"""Validation of ingestion API responses.

The server's result must be internally consistent and match the request that
was sent; anything else is treated as an unexpected response. Error bodies are
reduced to their machine-readable error code: server messages are never logged.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from access_finishing_sync.errors import (
    ApiRejectedError,
    AuthenticationError,
    ConnectorError,
    UnexpectedResponseError,
)
from access_finishing_sync.payload import PreparedRequest

STATUSES = frozenset({"accepted", "accepted_with_rejections", "rejected"})
MAX_LOGGED_MESSAGE = 200
_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_FIELD_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.]{0,63}")
_ATTENTION_CONFLICTS = frozenset({"stale_batch", "batch_id_conflict"})


@dataclass(frozen=True)
class Rejection:
    row_index: int
    errors: tuple[tuple[str | None, str], ...]


@dataclass(frozen=True)
class IngestionOutcome:
    batch_id: str
    status: str
    replayed: bool
    received_rows: int
    inserted_rows: int
    duplicate_rows: int
    rejected_rows: int
    superseded_rows: int
    restored_rows: int
    window_applied: bool | None
    rejections: tuple[Rejection, ...]
    rejections_truncated: bool


def _unexpected(reason: str) -> UnexpectedResponseError:
    return UnexpectedResponseError(
        f"The ingestion API returned an unexpected response ({reason}).",
        reason="unexpected_response",
        detail=reason,
    )


def _count(document: dict[str, Any], key: str) -> int:
    value = document.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _unexpected(f"{key} is not a non-negative integer")
    return value


def _flag(document: dict[str, Any], key: str, nullable: bool = False) -> bool | None:
    value = document.get(key)
    if isinstance(value, bool) or (nullable and value is None):
        return value
    raise _unexpected(f"{key} is not a boolean")


def _rejections(value: Any, row_count: int) -> tuple[Rejection, ...]:
    if not isinstance(value, list):
        raise _unexpected("rejections is not a list")
    seen: set[int] = set()
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise _unexpected("rejection is not an object")
        index = item.get("rowIndex")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < row_count:
            raise _unexpected("rejection rowIndex is out of range")
        if index in seen:
            raise _unexpected("rejection rowIndex is repeated")
        seen.add(index)
        errors = item.get("errors")
        if not isinstance(errors, list):
            raise _unexpected("rejection errors is not a list")
        issues = []
        for error in errors:
            if not isinstance(error, dict):
                raise _unexpected("rejection error is not an object")
            field = error.get("field")
            message = error.get("message")
            field_name = field if isinstance(field, str) and _FIELD_NAME.fullmatch(field) else None
            text = message if isinstance(message, str) else ""
            issues.append((field_name, text[:MAX_LOGGED_MESSAGE]))
        result.append(Rejection(row_index=index, errors=tuple(issues)))
    return tuple(result)


def parse_ingestion_result(
    body: bytes, request: PreparedRequest, source_system: str
) -> IngestionOutcome:
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        raise _unexpected("body is not JSON") from None
    if not isinstance(document, dict):
        raise _unexpected("body is not an object")

    if document.get("batchId") != request.batch_id:
        raise _unexpected("batchId does not match the request")
    if document.get("sourceSystem") != source_system:
        raise _unexpected("sourceSystem does not match the request")
    status = document.get("status")
    if status not in STATUSES:
        raise _unexpected("status is not recognised")

    outcome = IngestionOutcome(
        batch_id=request.batch_id,
        status=status,
        replayed=bool(_flag(document, "replayed")),
        received_rows=_count(document, "receivedRows"),
        inserted_rows=_count(document, "insertedRows"),
        duplicate_rows=_count(document, "duplicateRows"),
        rejected_rows=_count(document, "rejectedRows"),
        superseded_rows=_count(document, "supersededRows"),
        restored_rows=_count(document, "restoredRows"),
        window_applied=_flag(document, "windowApplied", nullable=True),
        rejections=_rejections(document.get("rejections"), request.row_count),
        rejections_truncated=bool(_flag(document, "rejectionsTruncated")),
    )
    _check_consistency(outcome, request)
    return outcome


def _check_consistency(outcome: IngestionOutcome, request: PreparedRequest) -> None:
    if outcome.received_rows != request.row_count:
        raise _unexpected("receivedRows does not match the rows sent")
    accounted = (
        outcome.inserted_rows
        + outcome.restored_rows
        + outcome.duplicate_rows
        + outcome.rejected_rows
    )
    if accounted != outcome.received_rows:
        raise _unexpected("row counts do not add up to receivedRows")

    valid = outcome.received_rows - outcome.rejected_rows
    expected_status = (
        "accepted"
        if outcome.rejected_rows == 0
        else ("accepted_with_rejections" if valid else "rejected")
    )
    if outcome.status != expected_status:
        raise _unexpected("status does not match the row counts")

    # Every request declares a window; the server applies it only without rejections.
    if outcome.window_applied is not (outcome.rejected_rows == 0):
        raise _unexpected("windowApplied does not match the rejected row count")
    if outcome.rejected_rows == 0 and outcome.rejections:
        raise _unexpected("rejections listed for a batch without rejected rows")

    listed = len(outcome.rejections)
    if outcome.rejections_truncated:
        if listed >= outcome.rejected_rows:
            raise _unexpected("rejectionsTruncated is set but all rejections are listed")
    elif listed != outcome.rejected_rows:
        raise _unexpected("rejections do not match rejectedRows")


def _error_code(body: bytes) -> str | None:
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return None
    detail = document.get("detail") if isinstance(document, dict) else None
    code = detail.get("error") if isinstance(detail, dict) else None
    return code if isinstance(code, str) and _ERROR_CODE.fullmatch(code) else None


def _validation_fields(body: bytes) -> list[str]:
    try:
        errors = json.loads(body)["detail"]["errors"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        return []
    if not isinstance(errors, list):
        return []
    fields = {
        e.get("field") for e in errors if isinstance(e, dict) and isinstance(e.get("field"), str)
    }
    return sorted(f for f in fields if _FIELD_NAME.fullmatch(f))[:20]


def classify_failure(status: int, body: bytes) -> ConnectorError:
    """A non-retryable, non-success response mapped to a connector error."""
    code = _error_code(body)
    if status == 401:
        return AuthenticationError(
            "The API rejected the connector credentials.",
            reason=code or "invalid_credentials",
            http_status=status,
        )
    if status == 403:
        return AuthenticationError(
            "The connector is not allowed to write this source system.",
            reason=code or "forbidden",
            http_status=status,
        )
    if status == 409:
        reason = code if code in _ATTENTION_CONFLICTS else (code or "conflict")
        message = {
            "stale_batch": "The API refused the batch as stale: newer data for this window "
            "was already applied.",
            "batch_id_conflict": "The API refused the batch ID as already used with "
            "different content.",
        }.get(reason, "The API refused the batch with a conflict.")
        return ApiRejectedError(message, reason=reason, http_status=status)
    if 400 <= status < 500:
        fields: dict[str, Any] = {"http_status": status}
        if status == 422:
            fields["invalid_fields"] = _validation_fields(body)
        return ApiRejectedError(
            f"The API permanently rejected the request (HTTP {status}).",
            reason=code or f"http_{status}",
            **fields,
        )
    return UnexpectedResponseError(
        f"The API returned an unexpected HTTP status ({status}).",
        reason=code or f"http_{status}",
        http_status=status,
    )
