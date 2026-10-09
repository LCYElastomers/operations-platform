"""Corrective Action Reports: entry, edits, actions, closure, Quality Cost link.

Every change is audited in the same transaction: the report as
``quality.car`` with key ``cars/<id>`` (its Why-Why rows, approvals and links
included), each corrective action as ``quality.car_action`` with key
``cars/<id>/actions/<action id>``. ``version`` guards edits of the report and,
separately, of each action, so recording an action never invalidates an open
edit of the report. Reports and actions are never deleted.

Closing a report requires the date closed, an effectiveness result (with a
follow-up reference when Not Effective) and every corrective action complete,
so a closed status never hides open actions.

People are platform users chosen by ID (``app.auth.people``); names recorded
before users existed are kept as they are. Who approved closure, who reviewed
effectiveness and who gave an approval are never taken from the request: they
are the signed-in user making that change, who must hold the permission for it
(``check_permissions``).
"""

import datetime as dt
import logging
import re
import uuid
from decimal import Decimal
from typing import Any

from app.audit.recorder import AuditAction, AuditChange
from app.auth import people
from app.core.permissions import Permission
from app.quality.car import calculations
from app.quality.car.models import EARLIEST_CAR_DATE, Car, CarAction
from app.quality.car.reference import (
    ACTION_STATUSES,
    APPROVAL_FUNCTIONS,
    CAR_NUMBER_PREFIX,
    CAR_STATUSES,
    DEPARTMENTS,
    DISPOSITIONS,
    EFFECTIVENESS_RESULTS,
    REFERENCE_TYPES,
    ROOT_CAUSE_CATEGORIES,
    SOURCES,
    STATUS_NOT_RECORDED,
    department_label,
    disposition_label,
)
from app.quality.car.repository import Approval, CarRepository, CarRow, Reference, WhyStep
from app.quality.car.schemas import (
    ActionComplete,
    ActionFields,
    ActionProgressOut,
    ApprovalOut,
    ApprovalRecord,
    CarActionOut,
    CarCreate,
    CarFields,
    CarListItemOut,
    CarOut,
    CarReferenceOut,
    CarUpdate,
    LegacyFieldOut,
    LinkedCostOut,
    QualityCostCreate,
    QualityCostLink,
    StepOut,
    WhyStepOut,
)
from app.quality.cost import calculations as cost_calculations
from app.quality.cost import records as cost_records
from app.quality.cost.classification import COQ_CLASSES, FINANCIAL_STATUSES, OPERATIONAL_STATUSES
from app.quality.cost.records import (
    Actor,
    RecordForbiddenError,
    RecordNotFoundError,
    RecordRuleError,
)
from app.quality.cost.repository import CostRepository, RecordRow
from app.quality.cost.schemas import CostRecordCreate, ReferenceIn
from app.safety.site_calendar import site_today

logger = logging.getLogger(__name__)

ENTITY_TYPE = "quality.car"
ACTION_ENTITY_TYPE = "quality.car_action"
_NUMBER = re.compile(r"^([A-Z]{1,5})-([0-9]{4})-([0-9]{3,6})$")

# Edited through the form; numbering and the source fields are set on creation
# or by the import only.
EDITABLE_FIELDS = (
    "subject",
    "requested_by",
    "request_date",
    "assigned_to",
    "due_date",
    "source_code",
    "department_code",
    "started_on",
    "started_time",
    "ended_on",
    "ended_time",
    "previous_occurrence",
    "previous_car",
    "nonconformity_description",
    "objective_evidence",
    "immediate_actions",
    "containment_owner",
    "containment_completed_on",
    "disposition_codes",
    "disposition_other",
    "safety_hazard",
    "environmental_hazard",
    "customer_impact",
    "incident_type",
    "root_cause_code",
    "equipment_involved",
    "work_order_number",
    "investigation_summary",
    "true_root_cause",
    "complaint_number",
    "date_reported",
    "dr_number",
    "material_name",
    "po_number",
    "supplier",
    "date_delivered",
    "production_lot",
    "quantity_affected",
    "similar_nonconformities",
    "similar_issue_found",
    "additional_action_required",
    "procedures_revised",
    "training_completed",
    "supporting_documents",
    "plan_completed_on",
    "success_criteria",
    "effectiveness_evidence",
    "reviewer",
    "review_date",
    "effectiveness_result",
    "follow_up_reference",
    "material_loss",
    "production_time_loss",
    "other_costs",
    "status",
    "date_closed",
    "closure_approved_by",
    "product",
    "campaign",
    "lot",
    "location",
    "counterparty",
)
_TEXT_FIELDS = frozenset(
    f
    for f in EDITABLE_FIELDS
    if f
    not in {
        "request_date",
        "due_date",
        "started_on",
        "started_time",
        "ended_on",
        "ended_time",
        "previous_occurrence",
        "containment_completed_on",
        "disposition_codes",
        "safety_hazard",
        "environmental_hazard",
        "customer_impact",
        "date_reported",
        "date_delivered",
        "similar_issue_found",
        "additional_action_required",
        "training_completed",
        "plan_completed_on",
        "review_date",
        "effectiveness_result",
        "material_loss",
        "production_time_loss",
        "other_costs",
        "status",
        "date_closed",
        "source_code",
        "department_code",
        "root_cause_code",
    }
)
# Person fields chosen from platform users (name + user link).
PERSON_FIELDS = ("requested_by", "assigned_to", "containment_owner")
# Set from the signed-in user making the change, never from the request.
SESSION_PERSON_FIELDS = ("reviewer", "closure_approved_by")
USER_LINK_FIELDS = tuple(f"{f}_user_id" for f in (*PERSON_FIELDS, *SESSION_PERSON_FIELDS))
EFFECTIVENESS_FIELDS = ("effectiveness_result", "review_date")
# The audit trail is the report's provenance, so it includes the source
# reference; the public history omits it.
AUDITED_FIELDS = (
    "car_number",
    *EDITABLE_FIELDS,
    *USER_LINK_FIELDS,
    "quality_cost_record_id",
    "legacy_fields",
    "migration_notes",
    "source",
    "source_key",
    "source_reference",
    "version",
)
ACTION_FIELDS = (
    "action",
    "owner",
    "owner_user_id",
    "target_date",
    "status",
    "completed_on",
    "procedures_revised",
    "training_completed",
    "supporting_documents",
)
AUDITED_ACTION_FIELDS = ("position", *ACTION_FIELDS, "version")


def entity_key(car_id: int) -> str:
    return f"cars/{car_id}"


def action_key(car_id: int, action_id: int) -> str:
    return f"cars/{car_id}/actions/{action_id}"


class CarConflictError(RuntimeError):
    """The report (or action) changed since the client loaded it. Nothing was written."""

    def __init__(self, current: CarRow) -> None:
        super().__init__("report changed since it was loaded")
        self.current = current


# Numbering --------------------------------------------------------------------------


def parse_number(text: str) -> tuple[str, int, int] | None:
    """(prefix, year, sequence) of a number such as ``Q-2026-006``; None otherwise."""
    match = _NUMBER.match(text.strip())
    if match is None:
        return None
    return match.group(1), int(match.group(2)), int(match.group(3))


def next_number(existing: list[str], year: int, prefix: str = CAR_NUMBER_PREFIX) -> str:
    """The next number of ``year``: one after the highest used, gaps left as they are."""
    sequences = [
        parsed[2]
        for parsed in (parse_number(n) for n in existing)
        if parsed is not None and parsed[0] == prefix and parsed[1] == year
    ]
    return f"{prefix}-{year}-{max(sequences, default=0) + 1:03d}"


# Reading ----------------------------------------------------------------------------


def _status_label(status: str | None) -> str:
    return CAR_STATUSES.get(status, STATUS_NOT_RECORDED) if status else STATUS_NOT_RECORDED


def _progress_out(progress: calculations.ActionProgress) -> ActionProgressOut:
    return ActionProgressOut(
        total=progress.total,
        complete=progress.complete,
        outstanding=progress.outstanding,
        overdue=progress.overdue,
    )


def _summary_fields(row: CarRow, today: dt.date, due_soon_days: int) -> dict[str, Any]:
    c = row.car
    progress = calculations.action_progress(row.actions, today)
    return {
        "id": c.id,
        "car_number": c.car_number,
        "subject": c.subject,
        "requested_by": c.requested_by,
        "requested_by_user_id": c.requested_by_user_id,
        "request_date": c.request_date,
        "assigned_to": c.assigned_to,
        "assigned_to_user_id": c.assigned_to_user_id,
        "due_date": c.due_date,
        "status": c.status,
        "status_label": _status_label(c.status),
        "date_closed": c.date_closed,
        "source_code": c.source_code,
        "source_label": SOURCES.get(c.source_code, c.source_code) if c.source_code else None,
        "department_code": c.department_code,
        "department_label": department_label(c.department_code),
        "root_cause_code": c.root_cause_code,
        "root_cause_label": (
            ROOT_CAUSE_CATEGORIES.get(c.root_cause_code, c.root_cause_code)
            if c.root_cause_code
            else None
        ),
        "effectiveness_result": c.effectiveness_result,
        "effectiveness_label": (
            EFFECTIVENESS_RESULTS[c.effectiveness_result] if c.effectiveness_result else None
        ),
        "previous_occurrence": c.previous_occurrence,
        "days_open": calculations.days_open(c, today),
        "past_due": calculations.is_past_due(c, today),
        "due_soon": calculations.is_due_soon(c, today, due_soon_days),
        "awaiting_effectiveness": calculations.awaiting_effectiveness(c, progress),
        "total_cost": calculations.cost_total(c),
        "quality_cost_record_id": c.quality_cost_record_id,
        "actions": _progress_out(progress),
        "source": c.source,
    }


def list_item_out(row: CarRow, today: dt.date, due_soon_days: int) -> CarListItemOut:
    return CarListItemOut(**_summary_fields(row, today, due_soon_days))


def actor_ids(row: CarRow) -> list[str]:
    """created_by / updated_by of a report and its actions, for ``people.display_names``."""
    ids = [row.car.created_by, row.car.updated_by, *(a.created_by for a in row.approvals)]
    for action in row.actions:
        ids.extend((action.created_by, action.updated_by))
    return ids


def action_out(
    action: CarAction, today: dt.date, names: dict[str, str] | None = None
) -> CarActionOut:
    names = names or {}
    return CarActionOut(
        id=action.id,
        position=action.position,
        action=action.action,
        owner=action.owner,
        owner_user_id=action.owner_user_id,
        target_date=action.target_date,
        status=action.status,  # type: ignore[arg-type]
        status_label=(
            ACTION_STATUSES.get(action.status, action.status)
            if action.status
            else STATUS_NOT_RECORDED
        ),
        completed_on=action.completed_on,
        procedures_revised=action.procedures_revised,
        training_completed=action.training_completed,
        supporting_documents=action.supporting_documents,
        overdue=(
            action.status != "complete"
            and action.target_date is not None
            and action.target_date < today
        ),
        version=action.version,
        created_at=action.created_at,
        created_by=action.created_by,
        created_by_name=people.actor_label(action.created_by, names),
        updated_at=action.updated_at,
        updated_by=action.updated_by,
        updated_by_name=people.actor_label(action.updated_by, names),
    )


def linked_cost_out(row: RecordRow) -> LinkedCostOut:
    r = row.record
    return LinkedCostOut(
        id=r.id,
        record_number=cost_records.record_number(r.id),
        title=r.title,
        coq_class_label=COQ_CLASSES[r.coq_class],  # type: ignore[index]
        total_cost=cost_calculations.record_total(r),
        financial_status_label=FINANCIAL_STATUSES[r.financial_status],  # type: ignore[index]
        status_label=OPERATIONAL_STATUSES[r.status],  # type: ignore[index]
    )


def car_out(
    row: CarRow, today: dt.date, due_soon_days: int, names: dict[str, str] | None = None
) -> CarOut:
    """``names``: display names of users (``people.display_names`` of ``actor_ids``)."""
    c = row.car
    names = names or {}
    progress = calculations.action_progress(row.actions, today)
    return CarOut(
        **_summary_fields(row, today, due_soon_days),
        started_on=c.started_on,
        started_time=c.started_time,
        ended_on=c.ended_on,
        ended_time=c.ended_time,
        previous_car=c.previous_car,
        nonconformity_description=c.nonconformity_description,
        objective_evidence=c.objective_evidence,
        immediate_actions=c.immediate_actions,
        containment_owner=c.containment_owner,
        containment_owner_user_id=c.containment_owner_user_id,
        containment_completed_on=c.containment_completed_on,
        disposition_codes=list(c.disposition_codes),
        disposition_labels=[disposition_label(code) for code in c.disposition_codes],
        disposition_other=c.disposition_other,
        safety_hazard=c.safety_hazard,
        environmental_hazard=c.environmental_hazard,
        customer_impact=c.customer_impact,
        incident_type=c.incident_type,
        equipment_involved=c.equipment_involved,
        work_order_number=c.work_order_number,
        investigation_summary=c.investigation_summary,
        true_root_cause=c.true_root_cause,
        why_steps=[
            WhyStepOut(
                position=s.position,
                what=s.what,
                why=s.why,
                root_cause=s.root_cause,
                countermeasure=s.countermeasure,
                who=s.who,
                target_date=s.target_date,
            )
            for s in row.why_steps
        ],
        complaint_number=c.complaint_number,
        date_reported=c.date_reported,
        dr_number=c.dr_number,
        material_name=c.material_name,
        po_number=c.po_number,
        supplier=c.supplier,
        date_delivered=c.date_delivered,
        production_lot=c.production_lot,
        quantity_affected=c.quantity_affected,
        similar_nonconformities=c.similar_nonconformities,
        similar_issue_found=c.similar_issue_found,
        additional_action_required=c.additional_action_required,
        procedures_revised=c.procedures_revised,
        training_completed=c.training_completed,
        supporting_documents=c.supporting_documents,
        plan_completed_on=c.plan_completed_on,
        success_criteria=c.success_criteria,
        effectiveness_evidence=c.effectiveness_evidence,
        reviewer=c.reviewer,
        reviewer_user_id=c.reviewer_user_id,
        review_date=c.review_date,
        follow_up_reference=c.follow_up_reference,
        material_loss=c.material_loss,
        production_time_loss=c.production_time_loss,
        other_costs=c.other_costs,
        quality_cost=linked_cost_out(row.quality_cost) if row.quality_cost else None,
        closure_approved_by=c.closure_approved_by,
        closure_approved_by_user_id=c.closure_approved_by_user_id,
        approvals=[
            ApprovalOut(
                function_code=a.function_code,  # type: ignore[arg-type]
                function_label=APPROVAL_FUNCTIONS[a.function_code],
                name=a.name,
                user_id=a.user_id,
                approved_on=a.approved_on,
                recorded_by=a.created_by,
                recorded_by_name=people.actor_label(a.created_by, names),
                recorded_at=a.created_at,
            )
            for a in sorted(
                row.approvals, key=lambda a: list(APPROVAL_FUNCTIONS).index(a.function_code)
            )
        ],
        product=c.product,
        campaign=c.campaign,
        lot=c.lot,
        location=c.location,
        counterparty=c.counterparty,
        references=[
            CarReferenceOut(
                type=r.type,
                type_label=REFERENCE_TYPES.get(r.type, r.type),
                key=r.key,
                label=r.label,
            )
            for r in row.references
        ],
        action_items=[action_out(a, today, names) for a in row.actions],
        steps=[
            StepOut(code=code, label=label, state=state)
            for code, label, state in calculations.step_states(c, progress, len(row.approvals))
        ],
        legacy_fields=[
            LegacyFieldOut(label=item["label"], value=item["value"])
            for item in (c.legacy_fields or [])
        ],
        migration_notes=c.migration_notes,
        version=c.version,
        created_at=c.created_at,
        created_by=c.created_by,
        created_by_name=people.actor_label(c.created_by, names),
        updated_at=c.updated_at,
        updated_by=c.updated_by,
        updated_by_name=people.actor_label(c.updated_by, names),
    )


def _audit_scalar(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_audit_scalar(v) for v in value]
    return value


def _sorted_approvals(approvals: tuple[Approval, ...]) -> list[Approval]:
    order = list(APPROVAL_FUNCTIONS)
    return sorted(approvals, key=lambda a: order.index(a.function_code))


def audit_value(
    car: Car,
    why_steps: tuple[WhyStep, ...],
    approvals: tuple[Approval, ...],
    references: tuple[Reference, ...],
) -> dict[str, Any]:
    values = {field: _audit_scalar(getattr(car, field)) for field in AUDITED_FIELDS}
    values["why_steps"] = [
        {k: _audit_scalar(v) for k, v in vars(step).items()} for step in why_steps
    ]
    values["approvals"] = [
        {
            "function": a.function_code,
            "name": a.name,
            "user_id": _audit_scalar(a.user_id),
            "approved_on": _audit_scalar(a.approved_on),
        }
        for a in _sorted_approvals(approvals)
    ]
    values["references"] = [{"type": r.type, "key": r.key, "label": r.label} for r in references]
    return values


def action_audit_value(action: CarAction) -> dict[str, Any]:
    return {field: _audit_scalar(getattr(action, field)) for field in AUDITED_ACTION_FIELDS}


def public_audit_value(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """An audit value as shown through the API: without the source location."""
    if value is None:
        return None
    return {k: v for k, v in value.items() if k != "source_reference"}


# Validation -------------------------------------------------------------------------


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _code(
    value: str | None,
    allowed: dict[str, str],
    current: str | None,
    *,
    error: str,
    message: str,
    field: str,
) -> str | None:
    """A controlled value: one of ``allowed``, or the report's existing (older-form) value."""
    if value is None or value in allowed or value == current:
        return value
    raise RecordRuleError(error, message, field=field)


def _not_future(day: dt.date | None, today: dt.date, *, label: str, field: str) -> None:
    if day is not None and day > today:
        raise RecordRuleError("future_date", f"The {label} cannot be in the future.", field=field)


def _person(
    repository: CarRepository,
    current: Car | None,
    field: str,
    user_id: uuid.UUID | None,
    name: str | None,
    label: str,
) -> people.Person:
    recorded = (
        people.Person(getattr(current, field), getattr(current, f"{field}_user_id"))
        if current is not None
        else people.NOBODY
    )
    try:
        return people.resolve(
            lambda: repository.session, user_id=user_id, name=name, current=recorded
        )
    except people.PersonChoiceError:
        raise RecordRuleError(
            "invalid_person",
            f"Choose the {label} from the list of active users.",
            field=_camel(field),
        ) from None


def _camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.title() for part in rest)


def _acting_person(actor: Actor) -> people.Person:
    return people.Person(actor.name, actor.user_id)


def _validated(
    repository: CarRepository,
    fields: CarFields,
    *,
    actor: Actor,
    today: dt.date,
    actions: tuple[CarAction, ...] = (),
    current: Car | None = None,
) -> tuple[dict[str, Any], tuple[WhyStep, ...], tuple[Reference, ...]]:
    subject = _text(fields.subject)
    if subject is None:
        raise RecordRuleError("blank_subject", "Enter the subject / issue.", field="subject")

    day = fields.request_date
    unchanged_date = current is not None and current.request_date == day
    if day < EARLIEST_CAR_DATE:
        raise RecordRuleError(
            "invalid_date", "The request date is before 2000.", field="requestDate"
        )
    if day > today and not unchanged_date:
        raise RecordRuleError(
            "future_date", "The request date cannot be in the future.", field="requestDate"
        )
    if fields.due_date is not None and fields.due_date < day:
        raise RecordRuleError(
            "due_before_request",
            "The due date cannot be before the request date.",
            field="dueDate",
        )

    source_code = _code(
        fields.source_code,
        SOURCES,
        current.source_code if current else None,
        error="invalid_source",
        message="Choose a source from the list.",
        field="sourceCode",
    )
    department_code = _code(
        fields.department_code,
        DEPARTMENTS,
        current.department_code if current else None,
        error="invalid_department",
        message="Choose a department from the list.",
        field="departmentCode",
    )
    root_cause_code = _code(
        fields.root_cause_code,
        ROOT_CAUSE_CATEGORIES,
        current.root_cause_code if current else None,
        error="invalid_root_cause",
        message="Choose a root cause category from the list.",
        field="rootCauseCode",
    )
    kept = set(current.disposition_codes) if current else set()
    dispositions: list[str] = []
    for code in fields.disposition_codes:
        if code not in DISPOSITIONS and code not in kept:
            raise RecordRuleError(
                "invalid_disposition",
                "Choose dispositions from the list.",
                field="dispositionCodes",
            )
        if code not in dispositions:
            dispositions.append(code)

    for time_value, date_value, label, field in (
        (fields.started_time, fields.started_on, "start", "startedOn"),
        (fields.ended_time, fields.ended_on, "end", "endedOn"),
    ):
        if time_value is not None and date_value is None:
            raise RecordRuleError(
                "time_without_date", f"Enter the {label} date for the {label} time.", field=field
            )
    if fields.started_on and fields.ended_on:
        start = dt.datetime.combine(fields.started_on, fields.started_time or dt.time.min)
        end = dt.datetime.combine(fields.ended_on, fields.ended_time or dt.time.max)
        if end < start:
            raise RecordRuleError(
                "ended_before_started",
                "The nonconformity cannot end before it started.",
                field="endedOn",
            )

    for attribute, label, field in (
        ("containment_completed_on", "containment completion date", "containmentCompletedOn"),
        ("plan_completed_on", "actual completion date", "planCompletedOn"),
        ("review_date", "review date", "reviewDate"),
    ):
        value = getattr(fields, attribute)
        if current is None or getattr(current, attribute) != value:
            _not_future(value, today, label=label, field=field)

    status = fields.status
    if status is None and not (current is not None and current.status is None):
        raise RecordRuleError("status_required", "Choose the CAR status.", field="status")
    follow_up = _text(fields.follow_up_reference)
    # Who approved closure is whoever closes the report; it stays while closed.
    if status != "closed":
        closure = people.NOBODY
    elif current is not None and current.status == "closed":
        closure = people.Person(current.closure_approved_by, current.closure_approved_by_user_id)
    else:
        closure = _acting_person(actor)
    # The reviewer is whoever records (or changes) the effectiveness review.
    review_changed = current is None or any(
        getattr(current, f) != getattr(fields, f) for f in EFFECTIVENESS_FIELDS
    )
    if fields.effectiveness_result is None and fields.review_date is None:
        reviewer = (
            people.Person(current.reviewer, current.reviewer_user_id)
            if current is not None and not review_changed
            else people.NOBODY
        )
    elif review_changed:
        reviewer = _acting_person(actor)
    else:
        assert current is not None  # noqa: S101 - unchanged review implies a current report
        reviewer = people.Person(current.reviewer, current.reviewer_user_id)
    if status == "closed":
        if fields.date_closed is None:
            raise RecordRuleError(
                "date_closed_required", "Enter the date closed.", field="dateClosed"
            )
        if fields.date_closed < day:
            raise RecordRuleError(
                "closed_before_request",
                "The date closed cannot be before the request date.",
                field="dateClosed",
            )
        if fields.date_closed > today and not (
            current and current.date_closed == fields.date_closed
        ):
            raise RecordRuleError(
                "future_date_closed", "The date closed cannot be in the future.", field="dateClosed"
            )
        if fields.effectiveness_result is None:
            raise RecordRuleError(
                "effectiveness_required",
                "Record the effectiveness review result before closing.",
                field="effectivenessResult",
            )
        if fields.effectiveness_result == "not_effective" and follow_up is None:
            raise RecordRuleError(
                "follow_up_required",
                "A CAR found Not Effective needs a follow-up CAR or action reference.",
                field="followUpReference",
            )
        outstanding = [a for a in actions if a.status != "complete"]
        if outstanding:
            raise RecordRuleError(
                "actions_outstanding",
                f"{len(outstanding)} corrective action(s) are not complete. "
                "Complete them before closing the CAR.",
                field="status",
            )
    elif fields.date_closed is not None:
        raise RecordRuleError(
            "date_closed_not_closed",
            "Only a closed CAR has a date closed. Set the status to Closed or clear the date.",
            field="dateClosed",
        )

    why_steps = tuple(
        step
        for step in (
            WhyStep(
                _text(s.what),
                _text(s.why),
                _text(s.root_cause),
                _text(s.countermeasure),
                _text(s.who),
                s.target_date,
            )
            for s in fields.why_steps
        )
        if any(v is not None for v in vars(step).values())
    )

    persons = {
        "requested_by": _person(
            repository,
            current,
            "requested_by",
            fields.requested_by_user_id,
            fields.requested_by,
            "requester",
        ),
        "assigned_to": _person(
            repository,
            current,
            "assigned_to",
            fields.assigned_to_user_id,
            fields.assigned_to,
            "assignee",
        ),
        "containment_owner": _person(
            repository,
            current,
            "containment_owner",
            fields.containment_owner_user_id,
            fields.containment_owner,
            "containment owner",
        ),
        "reviewer": reviewer,
        "closure_approved_by": closure,
    }

    references: list[Reference] = []
    for reference in fields.references:
        if reference.type not in REFERENCE_TYPES:
            raise RecordRuleError(
                "invalid_reference", "Unknown related-record type.", field="references"
            )
        key = _text(reference.key)
        if key is None or any(r.type == reference.type and r.key == key for r in references):
            continue
        references.append(Reference(reference.type, key, _text(reference.label)))

    values: dict[str, Any] = {}
    for field in EDITABLE_FIELDS:
        if field in persons:
            continue
        value = getattr(fields, field)
        values[field] = _text(value) if field in _TEXT_FIELDS else value
    for field, person in persons.items():
        values[field] = person.name
        values[f"{field}_user_id"] = person.user_id
    values.update(
        subject=subject,
        source_code=source_code,
        department_code=department_code,
        root_cause_code=root_cause_code,
        disposition_codes=dispositions,
        follow_up_reference=follow_up,
    )
    return values, why_steps, tuple(references)


def check_permissions(values: dict[str, Any], current: Car | None, actor: Actor) -> None:
    """Report changes that need more than ``car.create`` / ``car.edit``."""

    def before(field: str) -> Any:
        return getattr(current, field) if current is not None else None

    if (values["assigned_to"], values["assigned_to_user_id"]) != (
        before("assigned_to"),
        before("assigned_to_user_id"),
    ):
        actor.require(Permission.CAR_ASSIGN, "Assigning a CAR needs car.assign.")
    if any(values[f] != before(f) for f in EFFECTIVENESS_FIELDS):
        actor.require(
            Permission.CAR_REVIEW_EFFECTIVENESS,
            "Recording the effectiveness review needs car.reviewEffectiveness.",
        )
    was_closed = before("status") == "closed"
    if values["status"] == "closed" and not was_closed:
        actor.require(Permission.CAR_CLOSE, "Closing a CAR needs car.close.")
    if was_closed and values["status"] != "closed":
        actor.require(Permission.CAR_REOPEN, "Reopening a CAR needs car.reopen.")


COMPLETE_FORBIDDEN = (
    "Only the action's owner (with car.completeAction) or a CAR administrator "
    "can record an action as complete."
)


def can_complete_action(owner_user_id: uuid.UUID | None, actor: Actor) -> bool:
    """Completing an action needs car.completeAction and being its owner, or car.admin."""
    if actor.permissions is None:
        return True
    if Permission.CAR_ADMIN in actor.permissions:
        return True
    return (
        Permission.CAR_COMPLETE_ACTION in actor.permissions
        and owner_user_id is not None
        and owner_user_id == actor.user_id
    )


def _validated_action(
    repository: CarRepository,
    fields: ActionFields,
    *,
    today: dt.date,
    current: CarAction | None = None,
) -> dict[str, Any]:
    action = _text(fields.action)
    if action is None:
        raise RecordRuleError("blank_action", "Describe the action.", field="action")
    if fields.status == "complete":
        # An imported action recorded as Complete may have no completion date.
        recorded_without_date = (
            current is not None and current.status == "complete" and current.completed_on is None
        )
        if fields.completed_on is None and not recorded_without_date:
            raise RecordRuleError(
                "completed_on_required",
                "Enter the date the action was completed.",
                field="completedOn",
            )
        if (
            fields.completed_on is not None
            and fields.completed_on > today
            and not (current is not None and current.completed_on == fields.completed_on)
        ):
            raise RecordRuleError(
                "future_date", "The completion date cannot be in the future.", field="completedOn"
            )
    elif fields.completed_on is not None:
        raise RecordRuleError(
            "completed_on_not_complete",
            "Only a complete action has a completion date. "
            "Set the status to Complete or clear the date.",
            field="completedOn",
        )
    recorded = people.Person(current.owner, current.owner_user_id) if current else people.NOBODY
    try:
        owner = people.resolve(
            lambda: repository.session,
            user_id=fields.owner_user_id,
            name=fields.owner,
            current=recorded,
        )
    except people.PersonChoiceError:
        raise RecordRuleError(
            "invalid_person", "Choose the owner from the list of active users.", field="owner"
        ) from None
    return {
        "action": action,
        "owner": owner.name,
        "owner_user_id": owner.user_id,
        "target_date": fields.target_date,
        "status": fields.status,
        "completed_on": fields.completed_on,
        "procedures_revised": _text(fields.procedures_revised),
        "training_completed": fields.training_completed,
        "supporting_documents": _text(fields.supporting_documents),
    }


# Writing ----------------------------------------------------------------------------


def _comparable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return value.normalize()
    if isinstance(value, tuple):
        return list(value)
    return value


def _change(
    action: AuditAction,
    key: str,
    old: dict[str, Any] | None,
    new: dict[str, Any] | None,
    *,
    entity_type: str = ENTITY_TYPE,
) -> AuditChange:
    return AuditChange(
        action=action, entity_type=entity_type, entity_key=key, old_value=old, new_value=new
    )


def _log(event: str, key: str, actor: Actor, change_set: uuid.UUID) -> None:
    logger.info("event=%s key=%s user=%s change_set=%s", event, key, actor.actor_id, change_set)


def _today(actor: Actor) -> dt.date:
    return site_today(actor.now)


def _current_value(repository: CarRepository, car: Car) -> dict[str, Any]:
    return audit_value(
        car,
        repository.why_steps_of(car.id),
        repository.approvals_of(car.id),
        repository.references_of(car.id),
    )


def _row(repository: CarRepository, car_id: int) -> CarRow:
    row = repository.get(car_id)
    assert row is not None  # noqa: S101 - exists
    return row


def _locked(repository: CarRepository, car_id: int, version: int | None) -> Car:
    car = repository.lock(car_id)
    if car is None:
        raise RecordNotFoundError(car_id)
    if version is not None and car.version != version:
        raise CarConflictError(_row(repository, car_id))
    return car


def insert_audited(
    repository: CarRepository,
    values: dict[str, Any],
    why_steps: tuple[WhyStep, ...],
    approvals: tuple[Approval, ...],
    references: tuple[Reference, ...],
    actor: Actor,
    change_set: uuid.UUID,
) -> int:
    """Insert a report and its child rows and audit them; the caller commits."""
    car_id = repository.insert_car(values, actor_id=actor.actor_id, at=actor.now)
    repository.replace_why_steps(car_id, why_steps, actor_id=actor.actor_id, at=actor.now)
    repository.replace_approvals(car_id, approvals, actor_id=actor.actor_id, at=actor.now)
    repository.replace_references(car_id, references, actor_id=actor.actor_id, at=actor.now)
    created = repository.lock(car_id)
    assert created is not None  # noqa: S101 - inserted above
    repository.record_audit(
        actor_id=actor.actor_id,
        change_set_id=change_set,
        at=actor.now,
        changes=[_change("create", entity_key(car_id), None, _current_value(repository, created))],
    )
    return car_id


def insert_action_audited(
    repository: CarRepository,
    car_id: int,
    values: dict[str, Any],
    actor: Actor,
    change_set: uuid.UUID,
) -> int:
    position = repository.next_action_position(car_id)
    action_id = repository.insert_action(
        car_id, {**values, "position": position}, actor_id=actor.actor_id, at=actor.now
    )
    created = repository.lock_action(car_id, action_id)
    assert created is not None  # noqa: S101 - inserted above
    repository.record_audit(
        actor_id=actor.actor_id,
        change_set_id=change_set,
        at=actor.now,
        changes=[
            _change(
                "create",
                action_key(car_id, action_id),
                None,
                action_audit_value(created),
                entity_type=ACTION_ENTITY_TYPE,
            )
        ],
    )
    return action_id


def create(repository: CarRepository, request: CarCreate, actor: Actor) -> CarRow:
    """A new report, numbered ``Q-<request year>-<next>``."""
    change_set = uuid.uuid4()
    try:
        if request.status == "closed":
            raise RecordRuleError(
                "closed_on_create",
                "Save the CAR and record its actions before closing it.",
                field="status",
            )
        values, why, references = _validated(repository, request, actor=actor, today=_today(actor))
        check_permissions(values, None, actor)
        repository.lock_numbers()
        year = request.request_date.year
        number = next_number(repository.numbers_for_year(CAR_NUMBER_PREFIX, year), year)
        car_id = insert_audited(
            repository,
            {**values, "car_number": number, "source": "manual"},
            why,
            (),
            references,
            actor,
            change_set,
        )
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    _log("quality_car_created", entity_key(car_id), actor, change_set)
    return _row(repository, car_id)


def update(repository: CarRepository, car_id: int, request: CarUpdate, actor: Actor) -> CarRow:
    """Edit a report (not its actions). Unchanged values write nothing."""
    change_set = uuid.uuid4()
    try:
        car = _locked(repository, car_id, request.version)
        actions = repository.actions_of(car_id)
        values, why, references = _validated(
            repository, request, actor=actor, today=_today(actor), actions=actions, current=car
        )
        check_permissions(values, car, actor)
        before_why = repository.why_steps_of(car_id)
        before_approvals = repository.approvals_of(car_id)
        before_references = repository.references_of(car_id)
        changed = {
            k: v for k, v in values.items() if _comparable(getattr(car, k)) != _comparable(v)
        }
        why_changed = before_why != why
        references_changed = before_references != references
        if not (changed or why_changed or references_changed):
            repository.rollback()
            return _row(repository, car_id)
        before = audit_value(car, before_why, before_approvals, before_references)
        version = car.version
        repository.update_car(
            car_id, changed, version=version, actor_id=actor.actor_id, at=actor.now
        )
        if why_changed:
            repository.replace_why_steps(car_id, why, actor_id=actor.actor_id, at=actor.now)
        if references_changed:
            repository.replace_references(car_id, references, actor_id=actor.actor_id, at=actor.now)
        after = repository.lock(car_id)
        assert after is not None  # noqa: S101 - updated above
        repository.record_audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change("update", entity_key(car_id), before, _current_value(repository, after))
            ],
        )
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    _log("quality_car_updated", entity_key(car_id), actor, change_set)
    return _row(repository, car_id)


def _refuse_if_closed(car: Car) -> None:
    if car.status == "closed":
        raise RecordRuleError(
            "car_closed",
            "This CAR is closed. Reopen it (set the status to Open) to change its actions.",
            field="status",
        )


def add_action(
    repository: CarRepository, car_id: int, request: ActionFields, actor: Actor
) -> CarRow:
    change_set = uuid.uuid4()
    try:
        car = _locked(repository, car_id, None)
        _refuse_if_closed(car)
        values = _validated_action(repository, request, today=_today(actor))
        if values["status"] == "complete" and not can_complete_action(
            values["owner_user_id"], actor
        ):
            raise RecordForbiddenError(COMPLETE_FORBIDDEN)
        action_id = insert_action_audited(repository, car_id, values, actor, change_set)
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    _log("quality_car_action_created", action_key(car_id, action_id), actor, change_set)
    return _row(repository, car_id)


def _write_action(
    repository: CarRepository,
    car_id: int,
    action_id: int,
    version: int,
    values_for: Any,
    actor: Actor,
) -> CarRow:
    change_set = uuid.uuid4()
    try:
        car = _locked(repository, car_id, None)
        action = repository.lock_action(car_id, action_id)
        if action is None:
            raise RecordNotFoundError(action_id)
        if action.version != version:
            raise CarConflictError(_row(repository, car_id))
        _refuse_if_closed(car)
        values = values_for(action)
        changed = {
            k: v for k, v in values.items() if _comparable(getattr(action, k)) != _comparable(v)
        }
        if not changed:
            repository.rollback()
            return _row(repository, car_id)
        completing = values["status"] == "complete" and action.status != "complete"
        if completing and not can_complete_action(values["owner_user_id"], actor):
            raise RecordForbiddenError(COMPLETE_FORBIDDEN)
        # Without car.manageActions, owners may only update the status of their own action.
        if actor.permissions is not None and Permission.CAR_MANAGE_ACTIONS not in actor.permissions:
            own = action.owner_user_id is not None and action.owner_user_id == actor.user_id
            if set(changed) - {"status", "completed_on"} or not own:
                raise RecordForbiddenError("Changing corrective actions needs car.manageActions.")
        before = action_audit_value(action)
        repository.update_action(
            action_id, changed, version=action.version, actor_id=actor.actor_id, at=actor.now
        )
        after = repository.lock_action(car_id, action_id)
        assert after is not None  # noqa: S101 - updated above
        repository.record_audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "update",
                    action_key(car_id, action_id),
                    before,
                    action_audit_value(after),
                    entity_type=ACTION_ENTITY_TYPE,
                )
            ],
        )
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    _log("quality_car_action_updated", action_key(car_id, action_id), actor, change_set)
    return _row(repository, car_id)


def update_action(
    repository: CarRepository,
    car_id: int,
    action_id: int,
    request: ActionFields,
    version: int,
    actor: Actor,
) -> CarRow:
    return _write_action(
        repository,
        car_id,
        action_id,
        version,
        lambda current: _validated_action(
            repository, request, today=_today(actor), current=current
        ),
        actor,
    )


def complete_action(
    repository: CarRepository, car_id: int, action_id: int, request: ActionComplete, actor: Actor
) -> CarRow:
    def values_for(current: CarAction) -> dict[str, Any]:
        fields = ActionFields(
            action=current.action,
            owner=current.owner,
            owner_user_id=current.owner_user_id,
            target_date=current.target_date,
            status="complete",
            completed_on=request.completed_on,
            procedures_revised=current.procedures_revised,
            training_completed=current.training_completed,
            supporting_documents=current.supporting_documents,
        )
        return _validated_action(repository, fields, today=_today(actor), current=current)

    return _write_action(repository, car_id, action_id, request.version, values_for, actor)


def _set_cost_link(
    repository: CarRepository, car: Car, record_id: int | None, actor: Actor, change_set: uuid.UUID
) -> None:
    before = _current_value(repository, car)
    repository.update_car(
        car.id,
        {"quality_cost_record_id": record_id},
        version=car.version,
        actor_id=actor.actor_id,
        at=actor.now,
    )
    after = repository.lock(car.id)
    assert after is not None  # noqa: S101 - updated above
    repository.record_audit(
        actor_id=actor.actor_id,
        change_set_id=change_set,
        at=actor.now,
        changes=[_change("update", entity_key(car.id), before, _current_value(repository, after))],
    )


def create_quality_cost(
    repository: CarRepository, car_id: int, request: QualityCostCreate, actor: Actor
) -> CarRow:
    """Create a Quality Cost record from the report's cost impact, through the
    Quality Cost record rules, and link it, in one transaction."""
    change_set = uuid.uuid4()
    try:
        car = _locked(repository, car_id, request.version)
        if car.quality_cost_record_id is not None:
            raise RecordRuleError(
                "already_linked",
                "This CAR is already linked to a Quality Cost record. Remove the link first.",
                field="qualityCost",
            )
        closed = car.status == "closed"
        # The assignee becomes the owner when they are an active user and the
        # actor may set owners; a name recorded before users existed is not copied.
        owner_id = (
            car.assigned_to_user_id
            if people.is_active_user(repository.session, car.assigned_to_user_id)
            and (actor.permissions is None or Permission.QUALITY_COST_ASSIGN in actor.permissions)
            else None
        )
        cost_request = CostRecordCreate(
            record_date=car.request_date,
            title=f"{car.car_number} {car.subject}"[:200],
            area_id=request.area_id,
            coq_class=request.coq_class,
            category_code=request.category_code,
            description=(car.nonconformity_description or car.subject)[:4000],
            product=car.product,
            campaign=car.campaign,
            lot=car.lot,
            location=car.location,
            equipment=(car.equipment_involved or None),
            counterparty=car.counterparty,
            owner_user_id=owner_id,
            material_cost=car.material_loss,
            production_cost=car.production_time_loss,
            other_cost=car.other_costs,
            financial_status=request.financial_status,
            status="closed" if closed else "open",
            date_closed=car.date_closed if closed else None,
            references=[ReferenceIn(type="car", key=car.car_number, label=car.subject[:200])],
        )
        costs = CostRepository(repository.session)
        values, references = cost_records._validated(costs, cost_request, today=_today(actor))
        cost_records.check_permissions(values, None, actor)
        record_id = cost_records.insert_audited(
            costs, {**values, "source": "manual"}, references, actor, change_set
        )
        _set_cost_link(repository, car, record_id, actor, change_set)
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    _log("quality_car_cost_record_created", entity_key(car_id), actor, change_set)
    return _row(repository, car_id)


def link_quality_cost(
    repository: CarRepository, car_id: int, request: QualityCostLink, actor: Actor
) -> CarRow:
    """Link an existing Quality Cost record to the report, or remove the link."""
    change_set = uuid.uuid4()
    try:
        car = _locked(repository, car_id, request.version)
        if car.quality_cost_record_id == request.record_id:
            repository.rollback()
            return _row(repository, car_id)
        if request.record_id is not None:
            if CostRepository(repository.session).get(request.record_id) is None:
                raise RecordRuleError(
                    "cost_record_not_found", "No such Quality Cost record.", field="recordId"
                )
            other = repository.car_for_cost_record(request.record_id)
            if other is not None and other.id != car_id:
                raise RecordRuleError(
                    "cost_record_linked",
                    f"That Quality Cost record is already linked to {other.car_number}.",
                    field="recordId",
                )
        _set_cost_link(repository, car, request.record_id, actor, change_set)
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    _log("quality_car_cost_link_updated", entity_key(car_id), actor, change_set)
    return _row(repository, car_id)


def _write_approvals(
    repository: CarRepository,
    car: Car,
    approvals: tuple[Approval, ...],
    actor: Actor,
    change_set: uuid.UUID,
) -> None:
    before = _current_value(repository, car)
    repository.replace_approvals(car.id, approvals, actor_id=actor.actor_id, at=actor.now)
    repository.touch_car(car.id, version=car.version, actor_id=actor.actor_id, at=actor.now)
    after = repository.lock(car.id)
    assert after is not None  # noqa: S101 - updated above
    repository.record_audit(
        actor_id=actor.actor_id,
        change_set_id=change_set,
        at=actor.now,
        changes=[_change("update", entity_key(car.id), before, _current_value(repository, after))],
    )


def record_approval(
    repository: CarRepository, car_id: int, request: ApprovalRecord, actor: Actor
) -> CarRow:
    """Record the signed-in user's approval for one function, dated today. The
    approver's name and identity come from the session."""
    change_set = uuid.uuid4()
    label = APPROVAL_FUNCTIONS[request.function_code]
    try:
        car = _locked(repository, car_id, request.version)
        if car.status == "closed":
            raise RecordRuleError(
                "car_closed",
                "This CAR is closed. Reopen it to change approvals.",
                field="approvals",
            )
        current = repository.approvals_of(car_id)
        if any(a.function_code == request.function_code for a in current):
            raise RecordRuleError(
                "already_approved", f"{label} approval is already recorded.", field="approvals"
            )
        if actor.user_id is None or not actor.name:
            raise RecordForbiddenError("Approvals are recorded by a signed-in user.")
        approval = Approval(request.function_code, actor.name, _today(actor), actor.user_id)
        _write_approvals(repository, car, (*current, approval), actor, change_set)
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    _log("quality_car_approval_recorded", entity_key(car_id), actor, change_set)
    return _row(repository, car_id)


def withdraw_approval(
    repository: CarRepository, car_id: int, function_code: str, version: int, actor: Actor
) -> CarRow:
    """Remove an approval: your own, or any with car.admin."""
    change_set = uuid.uuid4()
    try:
        car = _locked(repository, car_id, version)
        if car.status == "closed":
            raise RecordRuleError(
                "car_closed",
                "This CAR is closed. Reopen it to change approvals.",
                field="approvals",
            )
        current = repository.approvals_of(car_id)
        approval = next((a for a in current if a.function_code == function_code), None)
        if approval is None:
            raise RecordNotFoundError(function_code)
        own = approval.user_id is not None and approval.user_id == actor.user_id
        if not own:
            actor.require(
                Permission.CAR_ADMIN, "Only the approver or a CAR administrator can withdraw it."
            )
        remaining = tuple(a for a in current if a.function_code != function_code)
        _write_approvals(repository, car, remaining, actor, change_set)
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    _log("quality_car_approval_withdrawn", entity_key(car_id), actor, change_set)
    return _row(repository, car_id)
