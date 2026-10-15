"""Process Safety Management API models (camelCase on the wire).

Text is kept as entered apart from leading and trailing whitespace; nothing is
reworded. Optional values left blank are null, never zero or an empty string.
"""

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field, model_validator

from app.core.schemas import CamelModel
from app.safety.psm.reference import MAX_SHORT, MAX_TEXT, MIN_REASON_LENGTH, MIN_REJECTION_LENGTH


def _strip(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def _blank_is_none(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


Required = Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=MAX_TEXT)]
Short = Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=MAX_SHORT)]
OptionalText = Annotated[
    str | None, BeforeValidator(_blank_is_none), Field(default=None, max_length=MAX_TEXT)
]
OptionalShort = Annotated[
    str | None, BeforeValidator(_blank_is_none), Field(default=None, max_length=MAX_SHORT)
]
Reason = Annotated[
    str, BeforeValidator(_strip), Field(min_length=MIN_REASON_LENGTH, max_length=MAX_TEXT)
]


def _email(value: object) -> object:
    value = _blank_is_none(value)
    return value.lower() if isinstance(value, str) else value


OptionalEmail = Annotated[
    str | None,
    BeforeValidator(_email),
    Field(default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
]
Risk = Literal["high", "medium", "low"]
EvidenceType = Literal[
    "engineering_calculation",
    "moc",
    "work_order",
    "photo",
    "pid",
    "procedure",
    "training_record",
    "inspection",
    "other",
]


# Requests ---------------------------------------------------------------------------


class StudyWrite(CamelModel):
    study_code: Annotated[
        str, BeforeValidator(_strip), Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,59}$")
    ]
    title: Short
    year: Annotated[int, Field(ge=1990, le=2100)]
    study_type_id: int
    description: OptionalText
    recommendation_prefix: Annotated[
        str, BeforeValidator(_strip), Field(pattern=r"^[A-Z0-9][A-Z0-9-]{0,29}$")
    ]
    status: Literal["active", "complete", "archived"] = "active"
    study_date: dt.date | None = None
    area_ids: Annotated[list[int], Field(max_length=50)] = []
    version: int | None = None


class ScenarioWrite(CamelModel):
    event: Required
    cause: Required
    consequence: Required
    risk: Risk
    area_equipment: OptionalShort
    process_node_id: int | None = None


class ScenarioUpdate(ScenarioWrite):
    version: int


class RecommendationCreate(CamelModel):
    study_id: int
    area_equipment: Short
    recommendation_text: Required
    process_node_id: int | None = None
    notes: OptionalText
    # A draft may be saved without scenarios; it is labelled and left out of figures.
    is_draft: bool = False
    scenarios: Annotated[list[ScenarioWrite], Field(max_length=100)] = []

    @model_validator(mode="after")
    def _needs_a_scenario(self) -> "RecommendationCreate":
        if not self.is_draft and not self.scenarios:
            raise ValueError(
                "Add at least one hazard scenario, or save the recommendation as a draft."
            )
        return self


class RecommendationUpdate(CamelModel):
    version: int
    area_equipment: Short
    recommendation_text: Required
    process_node_id: int | None = None
    notes: OptionalText
    is_draft: bool


class ScenarioOrder(CamelModel):
    version: int
    scenario_ids: Annotated[list[int], Field(min_length=1, max_length=100)]


class Assignment(CamelModel):
    """Who does the action. An owner is a platform user (by ID) or a person
    recorded by name and email, who needs no account."""

    department_id: int | None = None
    owner_user_id: uuid.UUID | None = None
    owner_name: OptionalShort
    owner_email: OptionalEmail
    due_date: dt.date | None = None
    task: OptionalText


class AcceptRequest(Assignment):
    version: int
    confirm: Literal[True]


class RejectRequest(CamelModel):
    version: int
    justification: Annotated[
        str,
        BeforeValidator(_strip),
        Field(min_length=MIN_REJECTION_LENGTH, max_length=MAX_TEXT),
    ]


class ReasonRequest(CamelModel):
    version: int
    reason: Reason


class ActionUpdate(Assignment):
    version: int
    title: Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=500)]
    # Required when the due date moves after work has begun.
    due_date_reason: OptionalText


class StatusChange(CamelModel):
    version: int
    status: Literal["not_started", "in_progress"]
    note: OptionalText


class ClosureRequest(CamelModel):
    version: int
    summary: Annotated[str, BeforeValidator(_strip), Field(min_length=10, max_length=MAX_TEXT)]
    # Closure without evidence: an administrator documents why.
    exception_reason: OptionalText
    # Going straight from Not Started to Pending Verification needs a reason.
    skip_reason: OptionalText


class VerificationApprove(CamelModel):
    version: int
    note: OptionalText


class CommentRequest(CamelModel):
    body: Required


class ResolutionRequest(CamelModel):
    version: int
    resolution: Literal["keep", "archive"]
    reason: Reason


class ReferenceWrite(CamelModel):
    name: Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=1000)]
    active: bool = True


class NotificationSettingsWrite(CamelModel):
    notify_on_assignment: bool
    notify_on_due_date_change: bool
    notify_on_status_change: bool
    notify_on_comment: bool
    due_soon_reminders: bool
    overdue_reminders: bool
    due_soon_days: Annotated[int, Field(ge=1, le=90)]


# Responses --------------------------------------------------------------------------


class Option(CamelModel):
    id: int
    name: str
    active: bool = True


class CodeLabel(CamelModel):
    code: str
    label: str


class StudyOut(CamelModel):
    id: int
    study_code: str
    title: str
    year: int
    study_type_id: int
    study_type: str
    description: str | None
    recommendation_prefix: str
    status: str
    study_date: dt.date | None
    areas: list[Option]
    source_file_name: str | None
    source_sheet_name: str | None
    source_reference: str | None
    imported: bool
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime
    counts: dict[str, Any]


class ScenarioOut(CamelModel):
    id: int
    sequence_number: int
    event: str
    cause: str
    consequence: str
    risk: str
    risk_source: str | None
    area_equipment: str | None
    process_node_id: int | None
    process_node: str | None
    source_row: int | None
    version: int


class ActionOut(CamelModel):
    id: int
    action_number: str
    recommendation_id: int
    recommendation_display_id: str
    study_id: int
    title: str
    description: str | None
    recommendation_text: str
    area_equipment: str
    governing_risk: str | None
    department_id: int | None
    department: str | None
    owner_user_id: uuid.UUID | None
    owner_name: str | None
    owner_email: str | None
    due_date: dt.date | None
    status: str
    due_state: str | None
    overdue: bool
    age_days: int
    attention: list[str]
    closure_summary: str | None
    closure_exception_reason: str | None
    closure_requested_at: dt.datetime | None
    closure_requested_by_name: str | None
    verified_at: dt.datetime | None
    verified_by_name: str | None
    closed_at: dt.datetime | None
    returned_at: dt.datetime | None
    return_reason: str | None
    reopened_at: dt.datetime | None
    reopen_reason: str | None
    requires_resolution: bool
    archived: bool
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime


class RecommendationRow(CamelModel):
    id: int
    display_id: str
    study_id: int
    recommendation_number: int
    area_equipment: str
    recommendation_text: str
    governing_risk: str | None
    scenario_count: int
    scenario_risks: dict[str, int]
    process_node_id: int | None
    process_node: str | None
    disposition: str
    department: str | None
    owner: str | None
    due_date: dt.date | None
    action_id: int | None
    action_number: str | None
    action_status: str | None
    due_state: str | None
    overdue: bool
    is_draft: bool
    archived: bool
    updated_at: dt.datetime


class RecommendationPage(CamelModel):
    rows: list[RecommendationRow]
    total: int
    page: int
    page_size: int


class AttachmentOut(CamelModel):
    id: int
    recommendation_id: int | None
    action_id: int | None
    evidence_type: str
    description: str | None
    original_file_name: str
    content_type: str
    size_bytes: int
    uploaded_by_name: str
    uploaded_at: dt.datetime
    removed_at: dt.datetime | None
    removed_by_name: str | None
    removal_reason: str | None


class UpdateOut(CamelModel):
    id: int
    update_type: str
    body: str
    previous_status: str | None
    new_status: str | None
    created_by_name: str
    created_at: dt.datetime


class NotificationOut(CamelModel):
    id: int
    event_type: str
    recipient_name: str | None
    recipient_email: str | None
    subject: str
    status: str
    status_detail: str | None
    attempts: int
    created_at: dt.datetime
    last_attempt_at: dt.datetime | None
    sent_at: dt.datetime | None


class TimelineEvent(CamelModel):
    occurred_at: dt.datetime
    actor_name: str
    event: str
    entity: str
    entity_key: str
    action: str
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None


class Abilities(CamelModel):
    edit_recommendation: bool
    decide_disposition: bool
    manage_actions: bool
    request_closure: bool
    verify_closure: bool
    reopen: bool
    admin: bool
    manage_studies: bool
    import_data: bool
    export: bool


class RecommendationDetail(CamelModel):
    id: int
    display_id: str
    study: StudyOut
    recommendation_number: int
    area_equipment: str
    recommendation_text: str
    process_node_id: int | None
    process_node: str | None
    governing_risk: str | None
    disposition: str
    disposition_justification: str | None
    disposition_by_name: str | None
    disposition_at: dt.datetime | None
    notes: str | None
    is_draft: bool
    archived_at: dt.datetime | None
    archive_reason: str | None
    source_row_start: int | None
    source_row_end: int | None
    source_key: str | None
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime
    scenarios: list[ScenarioOut]
    action: ActionOut | None
    attachments: list[AttachmentOut]
    abilities: Abilities


class ActionDetail(CamelModel):
    action: ActionOut
    updates: list[UpdateOut]
    attachments: list[AttachmentOut]
    notifications: list[NotificationOut]
    mail_enabled: bool
    abilities: Abilities


class ActionPage(CamelModel):
    rows: list[ActionOut]
    total: int
    page: int
    page_size: int
    tab_counts: dict[str, int]


class Timeline(CamelModel):
    events: list[TimelineEvent]


class OptionsOut(CamelModel):
    studies: list[Option]
    study_types: list[Option]
    areas: list[Option]
    departments: list[Option]
    process_nodes: list[Option]
    equipment: list[str]
    owners: list[CodeLabel]
    elements: list[CodeLabel]
    dispositions: list[CodeLabel]
    action_statuses: list[CodeLabel]
    risks: list[CodeLabel]
    evidence_types: list[CodeLabel]
    abilities: Abilities


class DashboardList(CamelModel):
    recommendation_id: int
    display_id: str
    action_id: int
    action_number: str
    title: str
    owner: str | None
    department: str | None
    due_date: dt.date | None
    status: str
    governing_risk: str | None


class OwnerLoadOut(CamelModel):
    owner: str
    owner_key: str | None
    not_started: int
    in_progress: int
    pending_verification: int
    overdue: int
    total_active: int


class DepartmentLoadOut(CamelModel):
    department: str
    department_id: int | None
    counts: dict[str, int]


class StageOut(CamelModel):
    code: str
    label: str
    definition: str
    count: int


class DashboardOut(CamelModel):
    scope_study_id: int | None
    today: dt.date
    kpis: dict[str, Any]
    lifecycle: list[StageOut]
    rejected: StageOut
    scenario_risks: dict[str, int]
    governing_risks: dict[str, int]
    matrix: dict[str, dict[str, int]]
    matrix_columns: list[CodeLabel]
    departments: list[DepartmentLoadOut]
    aging: list[dict[str, Any]]
    due_7: list[DashboardList]
    due_30: list[DashboardList]
    overdue: list[DashboardList]
    needs_scheduling: int
    distribution: list[OwnerLoadOut]
    drafts: int
