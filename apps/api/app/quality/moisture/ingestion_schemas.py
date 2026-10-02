"""Request and response models for finishing-measurement batch ingestion.

Rows carry the calculated results of the Access query qryFINISHING-AVG using
application field names. Values are validated but never altered: identifiers
and locations are kept exactly as sent, measurements stay exact decimals, and
null stays distinct from zero. No specification limits or outlier rules are
applied.
"""

import datetime as dt
import re
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainValidator,
    WithJsonSchema,
    model_validator,
)
from pydantic.alias_generators import to_camel

from app.core.config import SAFE_NAME_PATTERN
from app.quality.moisture.schemas import CamelModel

MAX_BATCH_ROWS = 5000
MAX_IDENTIFIER_LENGTH = 200
SOURCE_ROW_HASH_PATTERN = r"^[0-9a-f]{64}$"
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


def _source_date(value: object) -> dt.date:
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise ValueError("must be a date string in YYYY-MM-DD format")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError("is not a valid calendar date") from None


def _identifier(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if not isinstance(value, str):
        raise ValueError("must be a string or null")
    if len(value) > MAX_IDENTIFIER_LENGTH:
        raise ValueError(f"must be at most {MAX_IDENTIFIER_LENGTH} characters")
    if "\x00" in value:
        raise ValueError("must not contain NUL characters")
    return value


def _record_id(value: object) -> str | None:
    identifier = _identifier(value)
    if identifier == "":
        raise ValueError("must not be empty")
    return identifier


def _measurement(value: object) -> Decimal | None:
    # The router parses JSON numbers as Decimal, so no float rounding occurs.
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | Decimal):
        raise ValueError("must be a JSON number or null")
    number = Decimal(value)
    if not number.is_finite():
        raise ValueError("must be a finite number")
    return number


SourceDate = Annotated[
    dt.date,
    PlainValidator(_source_date),
    WithJsonSchema({"type": "string", "format": "date", "examples": ["2026-09-01"]}),
]
Identifier = Annotated[
    str | None,
    PlainValidator(_identifier),
    WithJsonSchema(
        {
            "anyOf": [{"type": "string", "maxLength": MAX_IDENTIFIER_LENGTH}, {"type": "null"}],
            "description": "Stored exactly as sent. Integers are stored as their text form.",
        }
    ),
]
RecordId = Annotated[
    str | None,
    PlainValidator(_record_id),
    WithJsonSchema(
        {
            "anyOf": [
                {"type": "string", "minLength": 1, "maxLength": MAX_IDENTIFIER_LENGTH},
                {"type": "null"},
            ],
            "description": "Durable upstream identity of the record, if the source has one.",
        }
    ),
]
Measurement = Annotated[
    Decimal | None,
    PlainValidator(_measurement),
    WithJsonSchema(
        {
            "anyOf": [{"type": "number"}, {"type": "null"}],
            "description": "Exact decimal value. null means missing and is never stored as 0.",
        }
    ),
]


class FinishingRowIn(BaseModel):
    """One row of qryFINISHING-AVG. Every field must be present; null is explicit."""

    model_config = ConfigDict(alias_generator=to_camel, extra="forbid", frozen=True)

    source_date: SourceDate
    campaign_no: Identifier
    lot: Identifier
    location: Identifier
    product: Identifier
    avg_moisture: Measurement
    avg_color: Measurement
    avg_combined_bd: Measurement
    source_record_id: RecordId = None
    source_row_hash: Annotated[str | None, Field(pattern=SOURCE_ROW_HASH_PATTERN)] = None

    def to_source_row(self) -> dict[str, Any]:
        """The row keyed by Access field names, as used for hashing and storage."""
        return {
            "DATE": self.source_date,
            "CAMPNO": self.campaign_no,
            "LOT": self.lot,
            "Location": self.location,
            "PRODUCT": self.product,
            "AvgOfMOISTURE": self.avg_moisture,
            "AvgOfCOLOR": self.avg_color,
            "AvgOfCombined_BD": self.avg_combined_bd,
        }


ROW_FIELD_ALIASES = frozenset(
    field.alias for field in FinishingRowIn.model_fields.values() if field.alias
)


class ReconciliationWindow(BaseModel):
    """Declares the batch to be the complete, authoritative set of source rows
    whose source date falls within this inclusive range."""

    model_config = ConfigDict(alias_generator=to_camel, extra="forbid", frozen=True)

    source_date_from: SourceDate
    source_date_to: SourceDate

    @model_validator(mode="after")
    def _ordered(self) -> "ReconciliationWindow":
        if self.source_date_from > self.source_date_to:
            raise ValueError("sourceDateFrom must be on or before sourceDateTo")
        return self

    def contains(self, day: dt.date) -> bool:
        return self.source_date_from <= day <= self.source_date_to


class FinishingBatchIn(BaseModel):
    """Batch envelope. Rows are validated individually so one bad row does not
    hide the outcome of the others."""

    model_config = ConfigDict(alias_generator=to_camel, extra="forbid", frozen=True)

    source_system: Annotated[str, Field(pattern=SAFE_NAME_PATTERN)]
    batch_id: Annotated[str, Field(pattern=SAFE_NAME_PATTERN)]
    extracted_at: AwareDatetime
    reconciliation_window: ReconciliationWindow | None = None
    rows: Annotated[list[Any], Field(min_length=1, max_length=MAX_BATCH_ROWS)]


def batch_request_json_schema() -> dict[str, Any]:
    schema = FinishingBatchIn.model_json_schema(
        by_alias=True, ref_template="#/components/schemas/{model}"
    )
    schema.pop("$defs", None)
    schema["properties"]["reconciliationWindow"] = {
        "anyOf": [ReconciliationWindow.model_json_schema(by_alias=True), {"type": "null"}]
    }
    schema["properties"]["rows"]["items"] = FinishingRowIn.model_json_schema(by_alias=True)
    return schema


class FieldIssue(CamelModel):
    field: str | None
    message: str


class RowRejection(CamelModel):
    row_index: int
    errors: list[FieldIssue]


class IngestionResult(CamelModel):
    batch_id: str
    source_system: str
    status: Literal["accepted", "accepted_with_rejections", "rejected"]
    received_rows: int
    inserted_rows: int
    duplicate_rows: int
    rejected_rows: int
    restored_rows: int
    superseded_rows: int
    # null when the batch declared no reconciliation window.
    window_applied: bool | None
    # True when this batch ID was already processed with identical content.
    replayed: bool
    rejections: list[RowRejection]
    rejections_truncated: bool
