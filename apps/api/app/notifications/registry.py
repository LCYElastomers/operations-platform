"""Stable event-type and template-variable registry.

Codes are immutable. Modules publish only codes listed here; templates may only
use the variables registered for the event (plus the common set).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EventTypeDef:
    code: str
    display_name: str
    module_code: str
    description: str
    variables: tuple[str, ...]


COMMON_VARIABLES = (
    "recipient.name",
    "recipient.email",
    "app.base_url",
    "event.occurred_at",
    "entity.reference",
    "entity.url",
)

PSM_ACTION_VARIABLES = COMMON_VARIABLES + (
    "action.reference",
    "action.title",
    "action.owner_name",
    "action.due_date",
    "action.status",
    "action.url",
    "recommendation.reference",
)

INCIDENT_VARIABLES = COMMON_VARIABLES + (
    "incident.reference",
    "incident.occurrence_date",
    "incident.area",
    "incident.classifications",
    "incident.description",
    "incident.url",
)

OBSERVATION_VARIABLES = COMMON_VARIABLES + (
    "observation.reference",
    "observation.url",
)

PERMIT_VARIABLES = COMMON_VARIABLES + (
    "permit.number",
    "permit.type",
    "permit.area",
    "permit.location",
    "permit.issued_at",
    "permit.expires_at",
    "permit.url",
)

EVENT_TYPES: tuple[EventTypeDef, ...] = (
    EventTypeDef(
        "psm.action.assigned",
        "PSM action assigned",
        "psm",
        "A PSM action was created or first assigned to an owner.",
        PSM_ACTION_VARIABLES,
    ),
    EventTypeDef(
        "psm.action.owner_changed",
        "PSM action owner changed",
        "psm",
        "The owner of a PSM action changed.",
        PSM_ACTION_VARIABLES,
    ),
    EventTypeDef(
        "psm.action.due_date_changed",
        "PSM action due date changed",
        "psm",
        "The due date of a PSM action changed.",
        PSM_ACTION_VARIABLES,
    ),
    EventTypeDef(
        "psm.action.due_soon",
        "PSM action due soon",
        "psm",
        "A PSM action is due within the reminder window.",
        PSM_ACTION_VARIABLES,
    ),
    EventTypeDef(
        "psm.action.overdue",
        "PSM action overdue",
        "psm",
        "A PSM action is past its due date.",
        PSM_ACTION_VARIABLES,
    ),
    EventTypeDef(
        "psm.closure.requested",
        "PSM closure requested",
        "psm",
        "Closure of a PSM action was requested.",
        PSM_ACTION_VARIABLES,
    ),
    EventTypeDef(
        "psm.closure.approved",
        "PSM closure approved",
        "psm",
        "Closure of a PSM action was approved.",
        PSM_ACTION_VARIABLES,
    ),
    EventTypeDef(
        "psm.closure.returned",
        "PSM closure returned",
        "psm",
        "A PSM closure request was returned.",
        PSM_ACTION_VARIABLES,
    ),
    EventTypeDef(
        "psm.action.reopened",
        "PSM action reopened",
        "psm",
        "A closed PSM action was reopened.",
        PSM_ACTION_VARIABLES,
    ),
    EventTypeDef(
        "incident.created",
        "Incident created",
        "incident",
        "An incident record was created.",
        INCIDENT_VARIABLES,
    ),
    EventTypeDef(
        "incident.psif_identified",
        "Incident PSIF identified",
        "incident",
        "An incident was designated as a PSIF.",
        INCIDENT_VARIABLES,
    ),
    EventTypeDef(
        "observation.action.assigned",
        "Observation action assigned",
        "safetyObservation",
        "An observation follow-up action was assigned.",
        OBSERVATION_VARIABLES,
    ),
    EventTypeDef(
        "observation.action.overdue",
        "Observation action overdue",
        "safetyObservation",
        "An observation follow-up action is overdue.",
        OBSERVATION_VARIABLES,
    ),
    EventTypeDef(
        "permit.created",
        "Permit created",
        "permit",
        "A permit was created (registered for future use).",
        PERMIT_VARIABLES,
    ),
    EventTypeDef(
        "permit.issued",
        "Permit issued",
        "permit",
        "A permit was issued (registered for future use).",
        PERMIT_VARIABLES,
    ),
    EventTypeDef(
        "permit.amended",
        "Permit amended",
        "permit",
        "A permit was amended (registered for future use).",
        PERMIT_VARIABLES,
    ),
    EventTypeDef(
        "permit.expiring",
        "Permit expiring",
        "permit",
        "A permit is nearing expiry (registered for future use).",
        PERMIT_VARIABLES,
    ),
    EventTypeDef(
        "permit.expired",
        "Permit expired",
        "permit",
        "A permit expired (registered for future use).",
        PERMIT_VARIABLES,
    ),
    EventTypeDef(
        "permit.closed",
        "Permit closed",
        "permit",
        "A permit was closed (registered for future use).",
        PERMIT_VARIABLES,
    ),
    EventTypeDef(
        "permit.cancelled",
        "Permit cancelled",
        "permit",
        "A permit was cancelled (registered for future use).",
        PERMIT_VARIABLES,
    ),
    EventTypeDef(
        "notifications.test",
        "Notification test",
        "notifications",
        "Administration Test Center send; never a production business event.",
        COMMON_VARIABLES + ("test.note",),
    ),
)

BY_CODE = {event.code: event for event in EVENT_TYPES}

# Legacy PSM outbox event name -> shared platform code.
PSM_LEGACY_TO_CODE = {
    "action_assigned": "psm.action.assigned",
    "owner_changed": "psm.action.owner_changed",
    "due_date_changed": "psm.action.due_date_changed",
    "due_soon": "psm.action.due_soon",
    "overdue": "psm.action.overdue",
    "closure_requested": "psm.closure.requested",
    "closure_approved": "psm.closure.approved",
    "closure_returned": "psm.closure.returned",
    "reopened": "psm.action.reopened",
}


def context_schema(event: EventTypeDef) -> dict[str, Any]:
    return {"variables": list(event.variables)}


def allowed_variables(event_type_code: str) -> frozenset[str]:
    event = BY_CODE.get(event_type_code)
    if event is None:
        return frozenset(COMMON_VARIABLES)
    return frozenset(event.variables)
