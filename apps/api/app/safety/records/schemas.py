"""API schemas for Incident and Near Miss records.

``source_reference`` (the import location of a legacy record) is never part
of a response.
"""

import datetime as dt
from typing import Any, Literal

from pydantic import Field, model_validator

from app.core.schemas import CamelModel
from app.safety.models import MAX_REPORTING_YEAR, MIN_REPORTING_YEAR
from app.safety.records.models import (
    MAX_DESCRIPTION_LENGTH,
    MAX_INCIDENT_NUMBER_LENGTH,
    MAX_REASON_LENGTH,
)

EventType = Literal["incident", "near_miss"]
RecordStatus = Literal["active", "voided", "reclassified"]
RecordSource = Literal["manual", "legacy_import"]
ReconciliationState = Literal[
    "reconciled",
    "records_missing",
    "records_exceed_total",
    "total_unreported_with_records",
    "explicit_zero_with_records",
    "no_total_and_no_records",
]


class RecordFields(CamelModel):
    incident_number: str | None = Field(default=None, max_length=MAX_INCIDENT_NUMBER_LENGTH)
    incident_date: dt.date
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_LENGTH)
    area_id: int | None = Field(default=None, ge=1)
    classification_category_id: int | None = Field(default=None, ge=1)


class MonthContext(CamelModel):
    """The month a record is entered from; its date must fall in that month."""

    reporting_year: int | None = Field(default=None, ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)
    reporting_month: int | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="after")
    def _both_or_neither(self) -> "MonthContext":
        if (self.reporting_year is None) != (self.reporting_month is None):
            raise ValueError("reportingYear and reportingMonth are given together")
        return self


class RecordCreate(RecordFields, MonthContext):
    event_type: EventType


class RecordUpdate(RecordFields, MonthContext):
    """Event type is not editable; a record of the wrong type is reclassified."""

    version: int = Field(ge=1)


class VoidRequest(CamelModel):
    version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)


class ReclassifyRequest(CamelModel):
    """Reclassify a record as the other event type: create its replacement from
    ``replacement`` (the type is implied), or link an existing active record of the
    other type by ``replacement_id``."""

    version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)
    replacement: RecordFields | None = None
    replacement_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _one_replacement(self) -> "ReclassifyRequest":
        if (self.replacement is None) == (self.replacement_id is None):
            raise ValueError("give exactly one of replacement or replacementId")
        return self


class RecordOut(CamelModel):
    id: int
    incident_number: str | None
    event_type: EventType
    incident_date: dt.date
    reporting_year: int
    reporting_month: int
    description: str
    area_id: int | None
    area_code: str | None
    area_name: str | None
    classification_category_id: int | None
    classification_code: str | None
    classification_name: str | None
    status: RecordStatus
    status_reason: str | None
    related_incident_id: int | None
    related_incident_number: str | None
    source: RecordSource
    version: int
    created_at: dt.datetime
    created_by: str
    updated_at: dt.datetime
    updated_by: str


class RecordPermissions(CamelModel):
    can_edit: bool
    can_manage: bool
    can_view_history: bool


class RecordListResponse(RecordPermissions):
    records: list[RecordOut]
    total: int


class RecordResponse(RecordPermissions):
    record: RecordOut


class ReclassifyResponse(RecordPermissions):
    record: RecordOut
    replacement: RecordOut


class OptionOut(CamelModel):
    id: int
    code: str
    name: str
    active: bool


class RecordOptionsResponse(CamelModel):
    areas: list[OptionOut]
    classifications: list[OptionOut]


class HistoryEventOut(CamelModel):
    occurred_at: dt.datetime
    actor_id: str
    action: Literal["create", "update", "delete"]
    change_set_id: str
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None


class HistoryResponse(CamelModel):
    record_id: int
    events: list[HistoryEventOut]


class MonthReconciliationOut(CamelModel):
    month: int
    event_type: EventType
    # The stored monthly total; None when the month is unreported.
    monthly_total: int | None
    documented: int
    state: ReconciliationState


class ReconciliationResponse(RecordPermissions):
    year: int
    months: list[MonthReconciliationOut]
