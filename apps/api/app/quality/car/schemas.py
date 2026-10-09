"""Corrective Action Report API models.

Amounts are full-precision decimals sent as plain strings. Null is "not
recorded", distinct from No, 0 or an empty list. No response carries a source
file location or workbook cell.
"""

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from app.core.schemas import CamelModel
from app.quality.car.reference import ActionStatus, CarStatus, EffectivenessResult
from app.quality.cost.classification import CoqClass, FinancialStatus
from app.quality.cost.schemas import DecimalStr, HistoryEventOut, Money

ShortText = Annotated[str, Field(max_length=200)]
LongText = Annotated[str, Field(max_length=8000)]
Code = Annotated[str, Field(pattern=r"^[a-z_]+$", max_length=50)]
ApprovalFunction = Literal[
    "quality",
    "department_supervisor",
    "safety_environmental",
    "operations_maintenance",
    "engineering",
    "process_manager",
]
StepState = Literal["not_started", "in_progress", "complete"]


class _Input(CamelModel):
    model_config = ConfigDict(extra="forbid")


class WhyStepIn(_Input):
    what: LongText | None = None
    why: LongText | None = None
    root_cause: LongText | None = None
    countermeasure: LongText | None = None
    who: ShortText | None = None
    target_date: dt.date | None = None


class ApprovalRecord(_Input):
    """Record your own approval for a function. Who and when come from the session."""

    version: Annotated[int, Field(ge=1)]
    function_code: ApprovalFunction


class CarReferenceIn(_Input):
    type: Code
    key: ShortText
    label: ShortText | None = None


class CarFields(_Input):
    """Everything on the report except its corrective actions, which have their
    own endpoints. Only the subject and request date are required, so a report
    can be saved incomplete.

    People are platform users chosen by ``*_user_id``; the server records their
    names. A name field may only repeat a name recorded before users existed.
    The effectiveness reviewer and the closure approver are not fields: they
    are the signed-in user who records the review or closes the report.
    Approvals have their own endpoint."""

    subject: ShortText
    requested_by_user_id: uuid.UUID | None = None
    requested_by: ShortText | None = None
    request_date: dt.date
    assigned_to_user_id: uuid.UUID | None = None
    assigned_to: ShortText | None = None
    due_date: dt.date | None = None
    # 1 Nonconformity identification
    source_code: Code | None = None
    department_code: Code | None = None
    started_on: dt.date | None = None
    started_time: dt.time | None = None
    ended_on: dt.date | None = None
    ended_time: dt.time | None = None
    previous_occurrence: bool | None = None
    previous_car: ShortText | None = None
    nonconformity_description: LongText | None = None
    objective_evidence: LongText | None = None
    # 2 Immediate correction and containment
    immediate_actions: LongText | None = None
    containment_owner_user_id: uuid.UUID | None = None
    containment_owner: ShortText | None = None
    containment_completed_on: dt.date | None = None
    disposition_codes: Annotated[list[Code], Field(max_length=10)] = []
    disposition_other: ShortText | None = None
    safety_hazard: bool | None = None
    environmental_hazard: bool | None = None
    customer_impact: bool | None = None
    # 3 Investigation and root cause
    incident_type: ShortText | None = None
    root_cause_code: Code | None = None
    equipment_involved: ShortText | None = None
    work_order_number: ShortText | None = None
    investigation_summary: LongText | None = None
    true_root_cause: LongText | None = None
    why_steps: Annotated[list[WhyStepIn], Field(max_length=20)] = []
    complaint_number: ShortText | None = None
    date_reported: dt.date | None = None
    dr_number: ShortText | None = None
    material_name: ShortText | None = None
    po_number: ShortText | None = None
    supplier: ShortText | None = None
    date_delivered: dt.date | None = None
    production_lot: ShortText | None = None
    quantity_affected: ShortText | None = None
    # 4 Systemic evaluation
    similar_nonconformities: LongText | None = None
    similar_issue_found: bool | None = None
    additional_action_required: bool | None = None
    # 5 Corrective action plan (as a whole)
    procedures_revised: LongText | None = None
    training_completed: bool | None = None
    supporting_documents: LongText | None = None
    plan_completed_on: dt.date | None = None
    # 6 Effectiveness review
    success_criteria: LongText | None = None
    effectiveness_evidence: LongText | None = None
    review_date: dt.date | None = None
    effectiveness_result: EffectivenessResult | None = None
    follow_up_reference: ShortText | None = None
    # 7 Cost impact
    material_loss: Money | None = None
    production_time_loss: Money | None = None
    other_costs: Money | None = None
    # 8 Closure. Status is null only on imported reports that recorded none.
    status: CarStatus | None = "open"
    date_closed: dt.date | None = None
    # Related production data and records
    product: ShortText | None = None
    campaign: ShortText | None = None
    lot: ShortText | None = None
    location: ShortText | None = None
    counterparty: ShortText | None = None
    references: Annotated[list[CarReferenceIn], Field(max_length=30)] = []


class CarCreate(CarFields):
    pass


class CarUpdate(CarFields):
    version: Annotated[int, Field(ge=1)]


class ActionFields(_Input):
    action: LongText
    owner_user_id: uuid.UUID | None = None
    owner: ShortText | None = None
    target_date: dt.date | None = None
    status: ActionStatus = "open"
    completed_on: dt.date | None = None
    procedures_revised: LongText | None = None
    training_completed: bool | None = None
    supporting_documents: LongText | None = None


class ActionCreate(ActionFields):
    pass


class ActionUpdate(ActionFields):
    # The action's version (each action is versioned on its own).
    version: Annotated[int, Field(ge=1)]


class ActionComplete(_Input):
    version: Annotated[int, Field(ge=1)]
    completed_on: dt.date


class QualityCostCreate(_Input):
    """Create a Quality Cost record from the report's cost impact and link it.

    The cost lines are taken from the report (material loss -> material,
    production time loss -> production, other -> other)."""

    version: Annotated[int, Field(ge=1)]
    area_id: Annotated[int, Field(ge=1)]
    coq_class: CoqClass
    category_code: Annotated[str, Field(max_length=100)]
    financial_status: FinancialStatus


class QualityCostLink(_Input):
    version: Annotated[int, Field(ge=1)]
    # The Quality Cost record id; null removes the link.
    record_id: Annotated[int, Field(ge=1)] | None


# --- Responses ---


class CodeLabelOut(CamelModel):
    code: str
    label: str


class ChoiceOut(CamelModel):
    code: str
    label: str
    # False for older-form values: shown on imported reports, not offered.
    active: bool


class StepOut(CamelModel):
    code: str
    label: str
    state: StepState


class CarActionOut(CamelModel):
    id: int
    position: int
    action: str
    owner: str | None
    # Null for a name recorded before users existed.
    owner_user_id: uuid.UUID | None
    target_date: dt.date | None
    # Null when an imported action recorded no status.
    status: ActionStatus | None
    status_label: str
    completed_on: dt.date | None
    procedures_revised: str | None
    training_completed: bool | None
    supporting_documents: str | None
    # Not complete and past its target date.
    overdue: bool
    version: int
    created_at: dt.datetime
    created_by: str
    created_by_name: str
    updated_at: dt.datetime
    updated_by: str
    updated_by_name: str


class WhyStepOut(CamelModel):
    position: int
    what: str | None
    why: str | None
    root_cause: str | None
    countermeasure: str | None
    who: str | None
    target_date: dt.date | None


class ApprovalOut(CamelModel):
    function_code: ApprovalFunction
    function_label: str
    name: str
    # The approving user; null on imported approvals.
    user_id: uuid.UUID | None
    approved_on: dt.date | None
    # The platform user who recorded the approval (not a signature).
    recorded_by: str
    recorded_by_name: str
    recorded_at: dt.datetime


class CarReferenceOut(CamelModel):
    type: str
    type_label: str
    key: str
    label: str | None


class LegacyFieldOut(CamelModel):
    label: str
    value: str


class LinkedCostOut(CamelModel):
    id: int
    record_number: str
    title: str
    coq_class_label: str
    total_cost: DecimalStr | None
    financial_status_label: str
    status_label: str


class ActionProgressOut(CamelModel):
    total: int
    complete: int
    outstanding: int
    overdue: int


class CarSummaryFields(CamelModel):
    """What the register shows for a report."""

    id: int
    car_number: str
    subject: str
    requested_by: str | None
    requested_by_user_id: uuid.UUID | None
    request_date: dt.date
    assigned_to: str | None
    assigned_to_user_id: uuid.UUID | None
    due_date: dt.date | None
    status: CarStatus | None
    status_label: str
    date_closed: dt.date | None
    source_code: str | None
    source_label: str | None
    department_code: str | None
    department_label: str | None
    root_cause_code: str | None
    root_cause_label: str | None
    effectiveness_result: EffectivenessResult | None
    effectiveness_label: str | None
    previous_occurrence: bool | None
    days_open: int
    past_due: bool
    due_soon: bool
    awaiting_effectiveness: bool
    # Sum of the entered cost lines; null when none is entered.
    total_cost: DecimalStr | None
    quality_cost_record_id: int | None
    actions: ActionProgressOut
    source: Literal["manual", "legacy_import"]


class CarListItemOut(CarSummaryFields):
    pass


class CarOut(CarSummaryFields):
    started_on: dt.date | None
    started_time: dt.time | None
    ended_on: dt.date | None
    ended_time: dt.time | None
    previous_car: str | None
    nonconformity_description: str | None
    objective_evidence: str | None
    immediate_actions: str | None
    containment_owner: str | None
    containment_owner_user_id: uuid.UUID | None
    containment_completed_on: dt.date | None
    disposition_codes: list[str]
    disposition_labels: list[str]
    disposition_other: str | None
    safety_hazard: bool | None
    environmental_hazard: bool | None
    customer_impact: bool | None
    incident_type: str | None
    equipment_involved: str | None
    work_order_number: str | None
    investigation_summary: str | None
    true_root_cause: str | None
    why_steps: list[WhyStepOut]
    complaint_number: str | None
    date_reported: dt.date | None
    dr_number: str | None
    material_name: str | None
    po_number: str | None
    supplier: str | None
    date_delivered: dt.date | None
    production_lot: str | None
    quantity_affected: str | None
    similar_nonconformities: str | None
    similar_issue_found: bool | None
    additional_action_required: bool | None
    procedures_revised: str | None
    training_completed: bool | None
    supporting_documents: str | None
    plan_completed_on: dt.date | None
    success_criteria: str | None
    effectiveness_evidence: str | None
    reviewer: str | None
    reviewer_user_id: uuid.UUID | None
    review_date: dt.date | None
    follow_up_reference: str | None
    material_loss: DecimalStr | None
    production_time_loss: DecimalStr | None
    other_costs: DecimalStr | None
    quality_cost: LinkedCostOut | None
    closure_approved_by: str | None
    closure_approved_by_user_id: uuid.UUID | None
    approvals: list[ApprovalOut]
    product: str | None
    campaign: str | None
    lot: str | None
    location: str | None
    counterparty: str | None
    references: list[CarReferenceOut]
    action_items: list[CarActionOut]
    steps: list[StepOut]
    legacy_fields: list[LegacyFieldOut]
    migration_notes: str | None
    version: int
    created_at: dt.datetime
    created_by: str
    created_by_name: str
    updated_at: dt.datetime
    updated_by: str
    updated_by_name: str


class CarAbilitiesOut(CamelModel):
    """What the signed-in user may do (for the interface; the server enforces it,
    including the record rules such as "only the owner completes an action")."""

    create: bool
    edit: bool
    assign: bool
    manage_actions: bool
    complete_action: bool
    review_effectiveness: bool
    approve: bool
    close: bool
    reopen: bool
    admin: bool
    # car.edit with qualityCost.create / qualityCost.view.
    create_quality_cost: bool
    link_quality_cost: bool


class CarListResponse(CamelModel):
    cars: list[CarListItemOut]
    total: int
    can_edit: bool
    abilities: CarAbilitiesOut


class CarResponse(CamelModel):
    car: CarOut
    can_edit: bool
    # Creating a Quality Cost record from the report also needs qualityCost.create.
    can_edit_cost: bool
    abilities: CarAbilitiesOut
    # The signed-in user, so the form can tell which actions are theirs.
    current_user_id: uuid.UUID | None


class CarOptionsResponse(CamelModel):
    sources: list[ChoiceOut]
    departments: list[ChoiceOut]
    root_causes: list[ChoiceOut]
    dispositions: list[ChoiceOut]
    action_statuses: list[CodeLabelOut]
    effectiveness_results: list[CodeLabelOut]
    car_statuses: list[CodeLabelOut]
    approval_functions: list[CodeLabelOut]
    reference_types: list[CodeLabelOut]
    steps: list[CodeLabelOut]
    # Names already used on reports, for filters and entry suggestions.
    people: list[str]
    assignees: list[str]
    due_soon_days: int
    can_edit: bool
    can_edit_cost: bool
    abilities: CarAbilitiesOut


class CarHistoryEventOut(HistoryEventOut):
    # "car" or "action"; ``action_id`` names the action.
    entity: Literal["car", "action"]
    action_id: int | None


class CarHistoryResponse(CamelModel):
    car_id: int
    events: list[CarHistoryEventOut]


class CarLinkOut(CamelModel):
    """A report linked to a Quality Cost record."""

    id: int
    car_number: str
    subject: str


# --- Dashboard ---


class CountOut(CamelModel):
    # Null code: not recorded.
    code: str | None
    label: str
    count: int


class CostByOut(CamelModel):
    code: str | None
    label: str
    total: DecimalStr
    count: int


class TrendMonthOut(CamelModel):
    year: int
    month: int
    opened: int
    closed: int


class AgingBucketOut(CamelModel):
    label: str
    min_days: int
    max_days: int | None
    count: int


class CarKpisOut(CamelModel):
    total: int
    open: int
    past_due: int
    due_soon: int
    awaiting_effectiveness: int
    closed_ytd: int
    # Imported reports whose form records no status (counted as not closed).
    status_not_recorded: int
    actions_overdue: int


class CarCostOut(CamelModel):
    # Sum of the reports' cost impact; null when no report has a cost entered.
    total: DecimalStr | None
    with_cost: int
    without_cost: int
    linked_to_quality_cost: int
    by_department: list[CostByOut]


class RepeatCarOut(CamelModel):
    id: int
    car_number: str
    subject: str
    previous_car: str | None


class CarDashboardResponse(CamelModel):
    today: dt.date
    year: int
    due_soon_days: int
    kpis: CarKpisOut
    by_status: list[CountOut]
    by_department: list[CountOut]
    by_source: list[CountOut]
    by_root_cause: list[CountOut]
    effectiveness: list[CountOut]
    repeat: list[CountOut]
    repeat_cars: list[RepeatCarOut]
    trend: list[TrendMonthOut]
    aging: list[AgingBucketOut]
    cost: CarCostOut
