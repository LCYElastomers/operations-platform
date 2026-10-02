"""Batch IDs, request payloads, and deterministic JSON serialization.

A request is serialized exactly once. Every retry sends the same bytes, so the
server recognises a resubmission (same batchId, same request digest) and
replays its stored result instead of applying the batch twice.
"""

import datetime as dt
import hashlib
import json
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from access_finishing_sync.errors import ExtractionError
from access_finishing_sync.window import DateWindow

MAX_BODY_BYTES = 5 * 1024 * 1024  # the API's limit
_JSON_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")


def new_batch_id(
    source_system: str,
    connector_id: str,
    now_utc: dt.datetime,
    uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
) -> str:
    """<source>:<connector>:<UTC timestamp>:<random UUID>, unique per extraction."""
    stamp = now_utc.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{source_system}:{connector_id}:{stamp}:{uuid_factory().hex}"


def build_payload(
    *,
    source_system: str,
    batch_id: str,
    extracted_at: dt.datetime,
    window: DateWindow,
    rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    if extracted_at.tzinfo is None:
        raise ValueError("extracted_at must include a time zone")
    return {
        "sourceSystem": source_system,
        "batchId": batch_id,
        "extractedAt": extracted_at.isoformat(),
        "reconciliationWindow": {
            "sourceDateFrom": window.start.isoformat(),
            "sourceDateTo": window.end.isoformat(),
        },
        "rows": list(rows),
    }


def _encode(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite numbers cannot be serialized")
        text = str(value)
        if not _JSON_NUMBER.fullmatch(text):
            raise ValueError("number has no exact JSON representation")
        return text
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, dict):
        items = (f"{json.dumps(str(k), ensure_ascii=True)}:{_encode(v)}" for k, v in value.items())
        return "{" + ",".join(items) + "}"
    if isinstance(value, list | tuple):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    raise TypeError(f"cannot serialize {type(value).__name__}")


def serialize(payload: dict[str, Any]) -> bytes:
    """Compact, ASCII-only JSON in a fixed key order. Decimals are written as
    exact JSON numbers (never via float); floats are refused."""
    return _encode(payload).encode("ascii")


@dataclass(frozen=True)
class PreparedRequest:
    batch_id: str
    body: bytes
    row_count: int
    window: DateWindow
    extracted_at: str

    @property
    def body_sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


def prepare_request(
    *,
    source_system: str,
    batch_id: str,
    extracted_at: dt.datetime,
    window: DateWindow,
    rows: Sequence[dict[str, Any]],
) -> PreparedRequest:
    payload = build_payload(
        source_system=source_system,
        batch_id=batch_id,
        extracted_at=extracted_at,
        window=window,
        rows=rows,
    )
    body = serialize(payload)
    if len(body) > MAX_BODY_BYTES:
        raise ExtractionError(
            f"The serialized window is {len(body)} bytes, above the API limit of "
            f"{MAX_BODY_BYTES}. Reduce RECONCILIATION_DAYS.",
            reason="window_too_large",
            body_bytes=len(body),
        )
    return PreparedRequest(
        batch_id=batch_id,
        body=body,
        row_count=len(rows),
        window=window,
        extracted_at=payload["extractedAt"],
    )
