"""API schemas for Incident and Near Miss records.

``source_reference`` (the import location of a legacy record) is never part
of a response.

Record detail (LOPC, damage, PIT, serious risk) and further classifications
are optional. In a create or update, an omitted detail is left as stored, a
null detail is removed, and an object replaces the stored detail; an omitted
or null ``additionalClassificationIds`` is left as stored. A null detail field
is not recorded (unknown), never "no" or zero.
"""

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, PlainSerializer, model_validator

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


# Record detail ---------------------------------------------------------------------

DecimalStr = Annotated[
    Decimal,
    PlainSerializer(
        lambda value: format(value.normalize(), "f"), return_type=str, when_used="json"
    ),
]
Code = Annotated[str, Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_]+$")]
# Blank text is stored as not recorded.
Text100 = Annotated[str, Field(max_length=100)]
Text200 = Annotated[str, Field(max_length=200)]
Text2000 = Annotated[str, Field(max_length=2000)]


class _Detail(CamelModel):
    model_config = ConfigDict(extra="forbid")


class LopcDetails(_Detail):
    is_lopc: bool | None = None
    material_name: Text200 | None = None
    estimated_quantity: (
        Annotated[DecimalStr, Field(ge=0, max_digits=14, decimal_places=3)] | None
    ) = None
    quantity_unit_code: Code | None = None
    equipment_tag: Text100 | None = None
    failure_mechanism_code: Code | None = None
    contributing_factor_code: Code | None = None
    secondary_containment_status_code: Code | None = None
    process_safety_incident: bool | None = None
    notes: Text2000 | None = None


class DamageDetails(_Detail):
    damage_kind_code: Code | None = None
    asset_or_property_name: Text200 | None = None
    equipment_tag: Text100 | None = None
    asset_type: Text100 | None = None
    damage_description: Text2000 | None = None
    operational_impact: Text2000 | None = None
    estimated_cost: Annotated[DecimalStr, Field(ge=0, max_digits=14, decimal_places=2)] | None = (
        None
    )
    currency_code: Code | None = None
    work_order_reference: Text100 | None = None
    out_of_service: bool | None = None
    repair_required: bool | None = None
    notes: Text2000 | None = None


class PitDetails(_Detail):
    vehicle_identifier: Text100 | None = None
    vehicle_type: Text100 | None = None
    ownership_type_code: Code | None = None
    operating_company: Text200 | None = None
    impacted_asset_or_property: Text200 | None = None
    damage_occurred: bool | None = None
    notes: Text2000 | None = None


class SeriousRiskDetails(_Detail):
    is_psif: bool
    potential_severity_code: Code | None = None
    serious_risk_category_code: Code | None = None
    rationale: Text2000 | None = None


class RecordDetailFields(CamelModel):
    additional_classification_ids: list[Annotated[int, Field(ge=1)]] | None = Field(
        default=None, max_length=20
    )
    lopc_details: LopcDetails | None = None
    damage_details: DamageDetails | None = None
    pit_details: PitDetails | None = None
    serious_risk_details: SeriousRiskDetails | None = None


class DetailStamp(CamelModel):
    updated_at: dt.datetime
    updated_by: str


class LopcDetailsOut(LopcDetails, DetailStamp):
    pass


class DamageDetailsOut(DamageDetails, DetailStamp):
    pass


class PitDetailsOut(PitDetails, DetailStamp):
    pass


class SeriousRiskDetailsOut(SeriousRiskDetails, DetailStamp):
    pass


class ClassificationRef(CamelModel):
    id: int
    code: str
    name: str


class MonthContext(CamelModel):
    """The month a record is entered from; its date must fall in that month."""

    reporting_year: int | None = Field(default=None, ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)
    reporting_month: int | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="after")
    def _both_or_neither(self) -> "MonthContext":
        if (self.reporting_year is None) != (self.reporting_month is None):
            raise ValueError("reportingYear and reportingMonth are given together")
        return self


class RecordCreate(RecordFields, MonthContext, RecordDetailFields):
    event_type: EventType


class RecordUpdate(RecordFields, MonthContext, RecordDetailFields):
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
    created_by_name: str | None = None
    updated_by_name: str | None = None
    additional_classifications: list[ClassificationRef] = []
    lopc_details: LopcDetailsOut | None = None
    damage_details: DamageDetailsOut | None = None
    pit_details: PitDetailsOut | None = None
    serious_risk_details: SeriousRiskDetailsOut | None = None


class RecordPermissions(CamelModel):
    """What the signed-in user may do. ``*_types`` list the record types each
    action is allowed for; the server enforces the same rules on every write."""

    can_edit: bool
    can_manage: bool
    can_view_history: bool
    can_classify: bool = False
    viewable_types: list[EventType] = []
    creatable_types: list[EventType] = []
    editable_types: list[EventType] = []
    voidable_types: list[EventType] = []


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


class DetailCodeOut(CamelModel):
    code: str
    name: str
    active: bool


class RecordOptionsResponse(CamelModel):
    areas: list[OptionOut]
    classifications: list[OptionOut]
    # Taxonomy -> codes in display order (record detail choices).
    detail_codes: dict[str, list[DetailCodeOut]] = {}


DetailKind = Literal["classifications", "lopc", "damage", "pit", "serious_risk"]


class HistoryEventOut(CamelModel):
    occurred_at: dt.datetime
    actor_id: str
    actor_name: str
    action: Literal["create", "update", "delete"]
    change_set_id: str
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    # Set for a change to the record's detail rather than the record itself.
    detail: DetailKind | None = None


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


# Record-derived analytics (insights) -----------------------------------------------

CompletenessStatus = Literal[
    "complete", "no_event_in_scope", "insufficient_classification_data", "source_unavailable"
]


class EventSummaryOut(CamelModel):
    id: int
    incident_number: str | None
    event_type: EventType
    incident_date: dt.date
    area_id: int | None
    area_name: str | None
    classifications: list[str]
    # Shortened to a few lines; the record holds the full text.
    description: str


class ExperienceCategoryOut(CamelModel):
    code: str
    name: str
    year: int
    as_of: dt.date
    status: CompletenessStatus
    latest_event_date: dt.date | None
    # as_of - latest_event_date in calendar days; None when no event is known.
    days_since_latest_event: int | None
    latest_in_selected_year: bool
    # Classified records dated Jan 1..as_of. A minimum when not complete.
    ytd_events: int
    ytd_events_complete: bool
    latest_event: EventSummaryOut | None
    # The stored monthly count Jan..as_of month; None when unreported.
    monthly_count: int | None
    warnings: list[str]


class EventExperienceResponse(CamelModel):
    year: int
    as_of: dt.date
    site_time_zone: str
    # PSIF counts near misses too when the user may view them.
    includes_near_misses: bool
    categories: list[ExperienceCategoryOut]


class CountOut(CamelModel):
    # The drill-through value: a code, "unknown", or for areas and
    # classifications the id as text; None when it cannot be filtered.
    key: str | None
    name: str
    count: int


class QuantityOut(CamelModel):
    unit_code: str
    unit_name: str
    total: DecimalStr
    records: int


class LopcRecordsResponse(CamelModel):
    year: int
    through_month: int | None
    records: int
    with_details: int
    monthly_count: int | None
    monthly_count_complete: bool
    by_failure_mechanism: list[CountOut]
    by_material: list[CountOut]
    by_equipment: list[CountOut]
    by_containment: list[CountOut]
    by_process_safety: list[CountOut]
    quantities: list[QuantityOut]
    records_without_quantity: int
    recent: list[EventSummaryOut]
    warnings: list[str]


class MonthCountOut(CamelModel):
    month: int
    records: int
    monthly_count: int | None


class SeriousRiskResponse(CamelModel):
    year: int
    through_month: int | None
    includes_near_misses: bool
    psif_records: int
    monthly_count: int | None
    monthly_count_complete: bool
    monthly: list[MonthCountOut]
    by_classification: list[CountOut]
    by_area: list[CountOut]
    by_contributing_factor: list[CountOut]
    by_severity: list[CountOut]
    recent: list[EventSummaryOut]
    warnings: list[str]
