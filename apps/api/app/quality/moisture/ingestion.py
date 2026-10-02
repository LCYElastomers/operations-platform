"""Storage of source rows in quality.finishing_measurements.

This is the write path a future synchronization job will call. It does not
read from Access. Values are stored as received: no trimming, case changes,
rounding, or substitution of zero for missing values.
"""

import datetime as dt
import hashlib
import json
import logging
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.quality.moisture.repository import FinishingMeasurementWriter
from app.quality.moisture.source import SOURCE_FIELD_MAP

logger = logging.getLogger(__name__)

HASH_VERSION = 1

IDENTIFIER_FIELDS = ("CAMPNO", "LOT", "Location", "PRODUCT")
MEASUREMENT_FIELDS = ("AvgOfMOISTURE", "AvgOfCOLOR", "AvgOfCombined_BD")


def source_date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        # Access returns dates as midnight datetimes; refuse to drop a real time.
        if value.time() != dt.time(0, 0):
            raise ValueError(f"DATE has an unexpected time component: {value!r}")
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value)
    raise TypeError(f"Unsupported DATE value: {value!r}")


def identifier(value: Any) -> str | None:
    """Identifiers are text. Numbers are converted to their exact text form."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    raise TypeError(f"Unsupported identifier value: {value!r}")


def measurement(value: Any) -> Decimal | None:
    """Exact decimal for a source measurement. None stays None; 0 stays 0."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"Unsupported measurement value: {value!r}")
    try:
        if isinstance(value, float):
            # repr() is the shortest text that round-trips to the same double.
            number = Decimal(repr(value))
        elif isinstance(value, int | Decimal | str):
            number = Decimal(value)
        else:
            raise TypeError(f"Unsupported measurement value: {value!r}")
    except InvalidOperation as error:
        raise ValueError(f"Invalid measurement value: {value!r}") from error
    if not number.is_finite():
        raise ValueError(f"Non-finite measurement value: {value!r}")
    return number


def _canonical_decimal(number: Decimal | None) -> str | None:
    if number is None:
        return None
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def compute_source_row_hash(row: Mapping[str, Any]) -> str:
    """Stable SHA-256 of a source row's values, used for idempotent ingestion.

    Equal source values hash equally regardless of Python type (e.g. 0.5 and
    Decimal("0.50"), 26101 and "26101"). NULL and 0 hash differently, and text
    is hashed exactly as received.
    """
    missing = set(SOURCE_FIELD_MAP) - set(row)
    if missing:
        raise ValueError(f"Source row is missing fields: {sorted(missing)}")

    canonical: dict[str, str | None] = {"DATE": source_date(row["DATE"]).isoformat()}
    for field in IDENTIFIER_FIELDS:
        canonical[field] = identifier(row[field])
    for field in MEASUREMENT_FIELDS:
        canonical[field] = _canonical_decimal(measurement(row[field]))

    payload = json.dumps(
        {"v": HASH_VERSION, "row": canonical},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def to_measurement_values(
    row: Mapping[str, Any], *, source_system: str, synced_at: dt.datetime
) -> dict[str, Any]:
    if not source_system:
        raise ValueError("source_system is required")
    if synced_at.tzinfo is None:
        raise ValueError("synced_at must be timezone-aware")
    return {
        "source_date": source_date(row["DATE"]),
        "campaign_no": identifier(row["CAMPNO"]),
        "lot": identifier(row["LOT"]),
        "location": identifier(row["Location"]),
        "product": identifier(row["PRODUCT"]),
        "avg_moisture": measurement(row["AvgOfMOISTURE"]),
        "avg_color": measurement(row["AvgOfCOLOR"]),
        "avg_combined_bd": measurement(row["AvgOfCombined_BD"]),
        "source_system": source_system,
        "source_row_hash": compute_source_row_hash(row),
        "synced_at": synced_at,
    }


def insert_source_rows(
    session: Session,
    rows: Iterable[Mapping[str, Any]],
    *,
    source_system: str,
    synced_at: dt.datetime,
) -> int:
    """Insert rows not already stored for this source system.

    Returns the number of newly inserted rows. Rows whose hash already exists
    for the source system are skipped. The caller owns the transaction.
    """
    values = [
        to_measurement_values(row, source_system=source_system, synced_at=synced_at) for row in rows
    ]
    if not values:
        return 0
    inserted = FinishingMeasurementWriter(session).insert_new(values)
    logger.info(
        "Finishing measurements ingested: source_system=%s received=%d inserted=%d skipped=%d",
        source_system,
        len(values),
        inserted,
        len(values) - inserted,
    )
    return inserted
