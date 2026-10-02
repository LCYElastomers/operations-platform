"""Maps qryFINISHING-AVG rows to API rows without altering values.

Identifiers stay strings exactly as returned (no trimming, case or punctuation
changes, no location normalization). Measurements become exact Decimals and
null stays distinct from zero. No thresholds, classifications, or outlier
rules are applied. Validation issues name the field and reason, never the value.
"""

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from access_finishing_sync.odbc import EXPECTED_COLUMNS
from access_finishing_sync.window import DateWindow

MAX_IDENTIFIER_LENGTH = 200  # the API's limit

IDENTIFIER_FIELDS = ("CAMPNO", "LOT", "Location", "PRODUCT")
MEASUREMENT_FIELDS = ("AvgOfMOISTURE", "AvgOfCOLOR", "AvgOfCombined_BD")
API_FIELDS = {
    "DATE": "sourceDate",
    "CAMPNO": "campaignNo",
    "LOT": "lot",
    "Location": "location",
    "PRODUCT": "product",
    "AvgOfMOISTURE": "avgMoisture",
    "AvgOfCOLOR": "avgColor",
    "AvgOfCombined_BD": "avgCombinedBd",
}


class FieldValueError(ValueError):
    pass


@dataclass(frozen=True)
class FieldIssue:
    row_index: int
    field: str
    reason: str


@dataclass(frozen=True)
class MappingResult:
    rows: list[dict[str, Any]]
    issues: list[FieldIssue]
    rows_with_time_of_day: int


def map_date(value: Any, window: DateWindow) -> tuple[dt.date, bool]:
    """Returns the calendar date and whether a time of day was dropped."""
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            raise FieldValueError("has an unsupported time zone")
        day, has_time = value.date(), value.time() != dt.time.min
    elif isinstance(value, dt.date):
        day, has_time = value, False
    elif value is None:
        raise FieldValueError("is missing")
    else:
        raise FieldValueError(f"has unsupported type {type(value).__name__}")
    if not window.contains(day):
        raise FieldValueError("is outside the reconciliation window")
    return day, has_time


def map_identifier(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    elif isinstance(value, bool):
        raise FieldValueError("has unsupported type bool")
    elif isinstance(value, int):
        text = str(value)
    elif isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value():
        try:
            text = str(value.quantize(Decimal(1)))
        except InvalidOperation:
            raise FieldValueError("is too large for an identifier") from None
    elif isinstance(value, float) and math.isfinite(value) and value.is_integer():
        text = str(int(value))
    else:
        raise FieldValueError(f"has unsupported type {type(value).__name__}")
    if len(text) > MAX_IDENTIFIER_LENGTH:
        raise FieldValueError(f"is longer than {MAX_IDENTIFIER_LENGTH} characters")
    if "\x00" in text:
        raise FieldValueError("contains a NUL character")
    return text


def map_measurement(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise FieldValueError("has unsupported type bool")
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        # str() gives the shortest repr that round-trips, i.e. the value as the
        # driver returned it, without exposing binary float noise.
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            raise FieldValueError("is not a number") from None
    else:
        raise FieldValueError(f"has unsupported type {type(value).__name__}")
    if number.is_nan():
        raise FieldValueError("is NaN")
    if number.is_infinite():
        raise FieldValueError("is infinite")
    return number


def map_rows(rows: Sequence[Sequence[Any]], window: DateWindow) -> MappingResult:
    mapped: list[dict[str, Any]] = []
    issues: list[FieldIssue] = []
    with_time = 0
    for index, values in enumerate(rows):
        if len(values) != len(EXPECTED_COLUMNS):
            issues.append(FieldIssue(index, "*", "has an unexpected number of columns"))
            continue
        source = dict(zip(EXPECTED_COLUMNS, values, strict=True))
        row: dict[str, Any] = {}
        row_issues: list[FieldIssue] = []

        try:
            day, has_time = map_date(source["DATE"], window)
            row["sourceDate"] = day.isoformat()
            with_time += has_time
        except FieldValueError as error:
            row_issues.append(FieldIssue(index, "DATE", str(error)))
        for field in IDENTIFIER_FIELDS:
            try:
                row[API_FIELDS[field]] = map_identifier(source[field])
            except FieldValueError as error:
                row_issues.append(FieldIssue(index, field, str(error)))
        for field in MEASUREMENT_FIELDS:
            try:
                row[API_FIELDS[field]] = map_measurement(source[field])
            except FieldValueError as error:
                row_issues.append(FieldIssue(index, field, str(error)))

        if row_issues:
            issues.extend(row_issues)
        else:
            mapped.append({API_FIELDS[name]: row[API_FIELDS[name]] for name in EXPECTED_COLUMNS})
    return MappingResult(rows=mapped, issues=issues, rows_with_time_of_day=with_time)
