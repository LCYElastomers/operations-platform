"""Administration API models for the shared Notifications domain."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field

from app.core.schemas import CamelModel

DeliveryMode = Literal["disabled", "redirect", "live", "test"]
RevisionStatus = Literal["draft", "published", "retired"]
RecipientType = Literal["to", "cc", "bcc"]
DeliveryTiming = Literal["immediate", "scheduled"]


class _Input(CamelModel):
    model_config = ConfigDict(extra="forbid")


class RecentDeliverySummary(CamelModel):
    id: uuid.UUID
    status: str
    rendered_subject: str
    queued_at: dt.datetime
    is_test: bool
    workflow_code: str | None = None


class OverviewOut(CamelModel):
    provider: str
    api_key_configured: bool
    delivery_mode: str
    email_enabled: bool
    emergency_pause: bool
    pending_outbox: int
    accepted_count: int
    failed_count: int
    warnings: list[str]
    recent_deliveries: list[RecentDeliverySummary]


class EventTypeOut(CamelModel):
    code: str
    display_name: str
    module_code: str
    description: str
    active: bool
    variables: list[str]


class TemplateRevisionOut(CamelModel):
    id: int
    template_id: int
    revision_number: int
    status: RevisionStatus
    subject_template: str
    html_template: str
    text_template: str
    variable_schema_json: dict[str, Any]
    created_at: dt.datetime
    created_by: str
    published_at: dt.datetime | None
    published_by: str | None


class TemplateOut(CamelModel):
    id: int
    code: str
    display_name: str
    description: str
    module_code: str
    active: bool
    current_published_revision_id: int | None
    draft_revision: TemplateRevisionOut | None
    published_revision: TemplateRevisionOut | None
    created_at: dt.datetime
    updated_at: dt.datetime


class TemplateListResponse(CamelModel):
    templates: list[TemplateOut]


class TemplateDraftUpdate(_Input):
    subject_template: Annotated[str, Field(max_length=500)] | None = None
    html_template: Annotated[str, Field(max_length=100_000)] | None = None
    text_template: Annotated[str, Field(max_length=100_000)] | None = None


class ValidateOut(CamelModel):
    valid: bool
    unresolved_variables: list[str]
    unsupported_variables: list[str]
    unsafe_content_findings: list[str]
    missing_required: list[str]


class PreviewIn(_Input):
    event_type_code: str
    context: dict[str, Any] | None = None
    psm_action_id: int | None = None


class PreviewOut(CamelModel):
    subject: str
    html: str
    text: str


class PublishIn(_Input):
    event_type_code: str


class RecipientRuleIn(_Input):
    recipient_type: RecipientType
    strategy_code: str
    strategy_config_json: dict[str, Any] = Field(default_factory=dict)
    active: bool = True
    display_order: int = 0


class RecipientRuleOut(CamelModel):
    id: int
    recipient_type: RecipientType
    strategy_code: str
    strategy_config_json: dict[str, Any]
    active: bool
    display_order: int


class WorkflowOut(CamelModel):
    id: int
    code: str
    display_name: str
    event_type_code: str
    template_id: int
    template_code: str
    enabled: bool
    delivery_timing_code: DeliveryTiming
    schedule_config_json: dict[str, Any] | None
    recipient_rules: list[RecipientRuleOut]
    created_at: dt.datetime
    updated_at: dt.datetime


class WorkflowListResponse(CamelModel):
    workflows: list[WorkflowOut]


class WorkflowUpdate(_Input):
    display_name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    enabled: bool | None = None
    delivery_timing_code: DeliveryTiming | None = None
    schedule_config_json: dict[str, Any] | None = None
    recipient_rules: list[RecipientRuleIn] | None = None


class DeliveryAttemptOut(CamelModel):
    attempt_number: int
    started_at: dt.datetime
    completed_at: dt.datetime | None
    status: str
    provider_http_status: int | None
    provider_error_code: str | None
    error_message: str | None
    retryable: bool


class DeliveryListItem(CamelModel):
    id: uuid.UUID
    status: str
    delivery_mode: str
    rendered_subject: str
    queued_at: dt.datetime
    is_test: bool
    event_type_code: str | None
    workflow_code: str | None
    entity_type: str | None
    entity_id: str | None
    entity_reference: str | None


class DeliveryListResponse(CamelModel):
    deliveries: list[DeliveryListItem]
    total: int


class DeliveryDetailOut(CamelModel):
    id: uuid.UUID
    status: str
    delivery_mode: str
    rendered_subject: str
    rendered_html: str
    rendered_text: str
    queued_at: dt.datetime
    attempted_at: dt.datetime | None
    accepted_at: dt.datetime | None
    failed_at: dt.datetime | None
    is_test: bool
    outbox_id: uuid.UUID | None
    notification_event_id: uuid.UUID | None
    workflow_id: int | None
    workflow_code: str | None
    event_type_code: str | None
    entity_type: str | None
    entity_id: str | None
    entity_reference: str | None
    intended_to_json: list[Any]
    intended_cc_json: list[Any]
    intended_bcc_json: list[Any]
    actual_to_json: list[Any]
    actual_cc_json: list[Any]
    actual_bcc_json: list[Any]
    provider_code: str | None
    provider_message_id: str | None
    attempts: list[DeliveryAttemptOut]


class DeliveryFilters(CamelModel):
    status: str | None = None
    from_date: dt.date | None = None
    to_date: dt.date | None = None
    event_type_code: str | None = None
    module_code: str | None = None
    workflow_id: int | None = None
    search: str | None = None
    limit: Annotated[int, Field(ge=1, le=500)] = 50
    offset: Annotated[int, Field(ge=0)] = 0


class RetryOut(CamelModel):
    outbox_id: uuid.UUID
    status: str


class TestPreviewIn(_Input):
    template_id: int | None = None
    workflow_id: int | None = None
    template_revision_id: int | None = None
    event_type_code: str | None = None
    context: dict[str, Any] | None = None
    psm_action_id: int | None = None
    to_email: Annotated[str, Field(max_length=254)] | None = None


class TestPreviewOut(CamelModel):
    subject: str
    html: str
    text: str
    intended_to: list[str]
    delivery_mode: str


class TestSendIn(TestPreviewIn):
    to_email: Annotated[str, Field(min_length=3, max_length=254)]


class TestSendOut(CamelModel):
    delivery_id: uuid.UUID
    status: str
    delivery_mode: str
    rendered_subject: str


class SettingsOut(CamelModel):
    provider: str
    api_key_configured: bool
    email_enabled: bool
    delivery_mode: str
    email_from_address: str | None
    email_from_name: str | None
    email_reply_to: str | None
    email_redirect_to: str | None
    emergency_pause: bool


class SettingsUpdate(_Input):
    emergency_pause: bool | None = None


class PsmActionPickerItem(CamelModel):
    id: int
    reference: str
    title: str
    owner_name: str | None


class PsmActionPickerResponse(CamelModel):
    actions: list[PsmActionPickerItem]
