"""Process Safety Management rules: studies, recommendations, hazard scenarios,
dispositions, actions, closure and evidence.

Every change runs in one transaction with its audit events (and any
notification it queues); on any error nothing is written. Records are archived,
never deleted. Status moves follow the action lifecycle:

    Not Started -> In Progress -> Pending Verification -> Closed
    Not Started -> Pending Verification     (closure requested, with a reason)
    Pending Verification -> In Progress     (returned by the verifier, with a reason)
    Closed -> In Progress                   (reopened, with a reason)

Closure is never a field edit: it takes a closure request (summary plus evidence
or a documented exception) and a verification. Editing other fields never
changes the status.
"""

import datetime as dt
import hashlib
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

from sqlalchemy import func, select

from app.audit.recorder import AuditChange
from app.auth import people
from app.core.permissions import Permission
from app.quality.cost.records import (
    Actor,
    RecordNotFoundError,
    RecordRuleError,
)
from app.safety.models import Area
from app.safety.psm import metrics, notifications
from app.safety.psm.metrics import ActionView, RecommendationView
from app.safety.psm.models import (
    PsmAction,
    PsmActionUpdate,
    PsmAttachment,
    PsmAttachmentContent,
    PsmDepartment,
    PsmNotificationSettings,
    PsmProcessNode,
    PsmRecommendation,
    PsmScenario,
    PsmStudy,
    PsmStudyType,
)
from app.safety.psm.reference import (
    ACTION_STATUSES,
    ATTACHMENT_EXTENSIONS,
    DISPOSITIONS,
    EVIDENCE_TYPES,
    MANUAL_TRANSITIONS,
    MAX_ATTACHMENT_BYTES,
    MIN_REASON_LENGTH,
    action_number,
    display_id,
)
from app.safety.psm.schemas import (
    AcceptRequest,
    ActionOut,
    ActionUpdate,
    Assignment,
    AttachmentOut,
    ClosureRequest,
    CommentRequest,
    NotificationOut,
    NotificationSettingsWrite,
    Option,
    ReasonRequest,
    RecommendationCreate,
    RecommendationRow,
    RecommendationUpdate,
    ReferenceWrite,
    RejectRequest,
    ResolutionRequest,
    ScenarioOrder,
    ScenarioOut,
    ScenarioUpdate,
    ScenarioWrite,
    StatusChange,
    StudyOut,
    StudyWrite,
    UpdateOut,
    VerificationApprove,
)
from app.safety.psm.store import NUMBER_LOCK_KEY, PsmStore, Scope
from app.safety.site_calendar import site_today

STUDY = "safety.psm_study"
RECOMMENDATION = "safety.psm_recommendation"
SCENARIO = "safety.psm_scenario"
ACTION = "safety.psm_action"
ATTACHMENT = "safety.psm_attachment"
REFERENCE = "safety.psm_reference"


def study_key(study_id: int) -> str:
    return f"psm/studies/{study_id}"


def recommendation_key(recommendation_id: int) -> str:
    return f"psm/recommendations/{recommendation_id}"


def scenario_key(recommendation_id: int, scenario_id: int) -> str:
    return f"{recommendation_key(recommendation_id)}/scenarios/{scenario_id}"


def action_key(recommendation_id: int, action_id: int) -> str:
    return f"{recommendation_key(recommendation_id)}/actions/{action_id}"


class PsmConflictError(RuntimeError):
    """The record changed since the client loaded it. Nothing was written."""


# Helpers --------------------------------------------------------------------------


def _today(actor: Actor) -> dt.date:
    return site_today(actor.now)


def _actor_name(actor: Actor) -> str:
    return actor.name or people.actor_label(actor.actor_id, {})


def _json(value: Any) -> Any:
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _values(row: Any, fields: Sequence[str]) -> dict[str, Any]:
    return {name: _json(getattr(row, name)) for name in fields}


def _change(
    action: str,
    entity_type: str,
    key: str,
    old: dict[str, Any] | None,
    new: dict[str, Any] | None,
    event: str,
) -> AuditChange:
    return AuditChange(
        action=action,  # type: ignore[arg-type]
        entity_type=entity_type,
        entity_key=key,
        old_value=old,
        new_value={**(new or {}), "event": event},
    )


def name_key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()


def _check_version(row: Any, version: int | None) -> None:
    if version is not None and row.version != version:
        raise PsmConflictError


def _locked_recommendation(
    store: PsmStore, recommendation_id: int, version: int | None
) -> PsmRecommendation:
    rec = store.get(PsmRecommendation, recommendation_id, for_update=True)
    if rec is None:
        raise RecordNotFoundError(recommendation_id)
    _check_version(rec, version)
    return rec


def _locked_action(store: PsmStore, action_id: int, version: int | None) -> PsmAction:
    action = store.get(PsmAction, action_id, for_update=True)
    if action is None:
        raise RecordNotFoundError(action_id)
    _check_version(action, version)
    return action


def _refuse_archived(rec: PsmRecommendation) -> None:
    if rec.archived_at is not None:
        raise RecordRuleError(
            "recommendation_archived", "This recommendation is archived. Restore it first."
        )


def _refuse_inactive_action(action: PsmAction) -> None:
    if action.archived_at is not None:
        raise RecordRuleError("action_archived", "This action is archived.")


def _touch(row: Any, actor: Actor, *, bump: bool = True) -> None:
    row.updated_at = actor.now
    row.updated_by = actor.actor_id
    if bump:
        row.version += 1


def _run(store: PsmStore, work: Callable[[uuid.UUID], Any]) -> Any:
    """Run ``work`` in one transaction: commit on success, roll back on any error."""
    try:
        result = work(uuid.uuid4())
        store.commit()
        return result
    except Exception:
        store.rollback()
        raise


# Views and responses ---------------------------------------------------------------


def owner_key(action: PsmAction) -> str | None:
    if action.owner_user_id is not None:
        return f"user:{action.owner_user_id}"
    if action.owner_name:
        return f"ext:{name_key(action.owner_name)}"
    return None


def action_view(action: PsmAction, scope: Scope) -> ActionView:
    department = scope.departments.get(action.department_id) if action.department_id else None
    return ActionView(
        id=action.id,
        action_number=action.action_number,
        status=action.status,
        department_id=action.department_id,
        department=department.name if department else None,
        owner_key=owner_key(action),
        owner=action.owner_name,
        due_date=action.due_date,
        created_on=site_today(action.created_at),
        returned=action.status in ("not_started", "in_progress")
        and (action.returned_at is not None or action.reopened_at is not None),
        failed_notification=action.id in scope.failed_notifications,
        requires_resolution=action.requires_resolution,
        archived=action.archived_at is not None,
    )


def views(scope: Scope) -> list[RecommendationView]:
    found = []
    for rec in scope.recommendations:
        scenarios = scope.scenarios.get(rec.id, [])
        action = scope.actions.get(rec.id)
        found.append(
            RecommendationView(
                id=rec.id,
                study_id=rec.study_id,
                display_id=rec.display_id,
                disposition=rec.disposition,
                scenario_risks=tuple(s.risk for s in scenarios),
                action=action_view(action, scope) if action else None,
                is_draft=rec.is_draft,
                archived=rec.archived_at is not None,
                extra={"rec": rec, "scenarios": scenarios, "action": action},
            )
        )
    return found


def study_out(
    study: PsmStudy,
    type_name: str,
    areas: Sequence[Area],
    recs: Sequence[RecommendationView],
    today: dt.date,
) -> StudyOut:
    k = metrics.kpis(recs, today)
    return StudyOut(
        id=study.id,
        study_code=study.study_code,
        title=study.title,
        year=study.year,
        study_type_id=study.study_type_id,
        study_type=type_name,
        description=study.description,
        recommendation_prefix=study.recommendation_prefix,
        status=study.status,
        study_date=study.study_date,
        areas=[Option(id=a.id, name=a.name, active=True) for a in areas],
        source_file_name=study.source_file_name,
        source_sheet_name=study.source_sheet_name,
        source_reference=study.source_reference,
        imported=study.source_key is not None,
        version=study.version,
        created_at=study.created_at,
        updated_at=study.updated_at,
        counts={
            "recommendations": k.total,
            "scenarios": sum(metrics.scenario_risks(recs).values()),
            "pending": k.pending,
            "accepted": k.accepted,
            "rejected": k.rejected,
            "openActions": k.not_started + k.in_progress + k.pending_verification,
            "closed": k.closed,
            "overdue": k.overdue,
            "drafts": sum(r.is_draft and not r.archived for r in recs),
            "governingRisks": metrics.governing_risks(recs),
        },
    )


def scenario_out(scenario: PsmScenario, nodes: dict[int, PsmProcessNode]) -> ScenarioOut:
    node = nodes.get(scenario.process_node_id) if scenario.process_node_id else None
    return ScenarioOut(
        id=scenario.id,
        sequence_number=scenario.sequence_number,
        event=scenario.event,
        cause=scenario.cause,
        consequence=scenario.consequence,
        risk=scenario.risk,
        risk_source=scenario.risk_source,
        area_equipment=scenario.area_equipment,
        process_node_id=scenario.process_node_id,
        process_node=node.name if node else None,
        source_row=scenario.source_row,
        version=scenario.version,
    )


def action_out(view: RecommendationView, today: dt.date) -> ActionOut:
    rec: PsmRecommendation = view.extra["rec"]  # type: ignore[assignment]
    action: PsmAction = view.extra["action"]  # type: ignore[assignment]
    a = view.action
    assert a is not None  # noqa: S101 - only called for recommendations with an action
    return ActionOut(
        id=action.id,
        action_number=action.action_number,
        recommendation_id=rec.id,
        recommendation_display_id=rec.display_id,
        study_id=rec.study_id,
        title=action.title,
        description=action.description,
        recommendation_text=rec.recommendation_text,
        area_equipment=rec.area_equipment,
        governing_risk=metrics.governing_risk(view.scenario_risks),
        department_id=action.department_id,
        department=a.department,
        owner_user_id=action.owner_user_id,
        owner_name=action.owner_name,
        owner_email=action.owner_email,
        due_date=action.due_date,
        status=action.status,
        due_state=metrics.due_state(a, today),
        overdue=metrics.is_overdue(a, today),
        age_days=metrics.age_days(a, today),
        attention=metrics.needs_attention(a, today),
        closure_summary=action.closure_summary,
        closure_exception_reason=action.closure_exception_reason,
        closure_requested_at=action.closure_requested_at,
        closure_requested_by_name=action.closure_requested_by_name,
        verified_at=action.verified_at,
        verified_by_name=action.verified_by_name,
        closed_at=action.closed_at,
        returned_at=action.returned_at,
        return_reason=action.return_reason,
        reopened_at=action.reopened_at,
        reopen_reason=action.reopen_reason,
        requires_resolution=action.requires_resolution,
        archived=action.archived_at is not None,
        version=action.version,
        created_at=action.created_at,
        updated_at=action.updated_at,
    )


def recommendation_row(view: RecommendationView, scope: Scope, today: dt.date) -> RecommendationRow:
    rec: PsmRecommendation = view.extra["rec"]  # type: ignore[assignment]
    action: PsmAction | None = view.extra["action"]  # type: ignore[assignment]
    node = scope.nodes.get(rec.process_node_id) if rec.process_node_id else None
    counts = {risk: view.scenario_risks.count(risk) for risk in ("high", "medium", "low")}
    updated = max(rec.updated_at, action.updated_at) if action else rec.updated_at
    return RecommendationRow(
        id=rec.id,
        display_id=rec.display_id,
        study_id=rec.study_id,
        recommendation_number=rec.recommendation_number,
        area_equipment=rec.area_equipment,
        recommendation_text=rec.recommendation_text,
        governing_risk=metrics.governing_risk(view.scenario_risks),
        scenario_count=len(view.scenario_risks),
        scenario_risks=counts,
        process_node_id=rec.process_node_id,
        process_node=node.name if node else None,
        disposition=rec.disposition,
        department=view.action.department if view.action else None,
        owner=action.owner_name if action else None,
        due_date=action.due_date if action else None,
        action_id=action.id if action else None,
        action_number=action.action_number if action else None,
        action_status=action.status if action else None,
        due_state=metrics.due_state(view.action, today),
        overdue=metrics.is_overdue(view.action, today),
        is_draft=rec.is_draft,
        archived=rec.archived_at is not None,
        updated_at=updated,
    )


def attachment_out(row: PsmAttachment) -> AttachmentOut:
    return AttachmentOut(
        id=row.id,
        recommendation_id=row.recommendation_id,
        action_id=row.action_id,
        evidence_type=row.evidence_type,
        description=row.description,
        original_file_name=row.original_file_name,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        uploaded_by_name=row.uploaded_by_name,
        uploaded_at=row.uploaded_at,
        removed_at=row.removed_at,
        removed_by_name=row.removed_by_name,
        removal_reason=row.removal_reason,
    )


def update_out(row: PsmActionUpdate) -> UpdateOut:
    return UpdateOut(
        id=row.id,
        update_type=row.update_type,
        body=row.body,
        previous_status=row.previous_status,
        new_status=row.new_status,
        created_by_name=row.created_by_name,
        created_at=row.created_at,
    )


def notification_out(row: Any) -> NotificationOut:
    return NotificationOut(
        id=row.id,
        event_type=row.event_type,
        recipient_name=row.recipient_name,
        recipient_email=row.recipient_email,
        subject=row.subject,
        status=row.status,
        status_detail=row.status_detail,
        attempts=row.attempts,
        created_at=row.created_at,
        last_attempt_at=row.last_attempt_at,
        sent_at=row.sent_at,
    )


# Register filters -------------------------------------------------------------------


@dataclass(frozen=True)
class RegisterFilter:
    study_id: int | None = None
    dispositions: tuple[str, ...] = ()
    action_statuses: tuple[str, ...] = ()  # "none" = no action
    governing_risks: tuple[str, ...] = ()
    scenario_risks: tuple[str, ...] = ()
    departments: tuple[str, ...] = ()  # department IDs, or "unassigned"
    owners: tuple[str, ...] = ()  # owner keys, or "unassigned"
    equipment: tuple[str, ...] = ()
    nodes: tuple[int, ...] = ()
    due_states: tuple[str, ...] = ()
    overdue: bool = False
    unassigned: bool = False
    missing_due_date: bool = False
    stage: str | None = None
    matrix_risk: str | None = None
    matrix_column: str | None = None
    search: str | None = None
    include_drafts: bool = False
    include_archived: bool = False


def _searchable(view: RecommendationView, scope: Scope) -> str:
    rec: PsmRecommendation = view.extra["rec"]  # type: ignore[assignment]
    action: PsmAction | None = view.extra["action"]  # type: ignore[assignment]
    scenarios: list[PsmScenario] = view.extra["scenarios"]  # type: ignore[assignment]
    node = scope.nodes.get(rec.process_node_id) if rec.process_node_id else None
    parts: list[str | None] = [
        rec.display_id,
        rec.area_equipment,
        rec.recommendation_text,
        rec.notes,
        rec.disposition_justification,
        node.name if node else None,
    ]
    for s in scenarios:
        parts += [s.event, s.cause, s.consequence, s.area_equipment]
    if action is not None:
        parts += [
            action.action_number,
            action.title,
            action.description,
            action.owner_name,
            view.action.department if view.action else None,
        ]
    return "\n".join(p for p in parts if p).lower()


def matches(view: RecommendationView, f: RegisterFilter, scope: Scope, today: dt.date) -> bool:
    rec: PsmRecommendation = view.extra["rec"]  # type: ignore[assignment]
    scenarios: list[PsmScenario] = view.extra["scenarios"]  # type: ignore[assignment]
    a = view.action
    if view.archived and not f.include_archived:
        return False
    if view.is_draft and not f.include_drafts:
        return False
    if f.study_id is not None and view.study_id != f.study_id:
        return False
    if f.dispositions and view.disposition not in f.dispositions:
        return False
    if f.action_statuses and (a.status if a else "none") not in f.action_statuses:
        return False
    governing = metrics.governing_risk(view.scenario_risks)
    if f.governing_risks and governing not in f.governing_risks:
        return False
    if f.scenario_risks and not set(view.scenario_risks) & set(f.scenario_risks):
        return False
    if f.departments:
        value = str(a.department_id) if a and a.department_id else "unassigned"
        if a is None or value not in f.departments:
            return False
    if f.owners:
        value = a.owner_key if a and a.owner_key else "unassigned"
        if a is None or value not in f.owners:
            return False
    if f.equipment:
        found = {rec.area_equipment} | {s.area_equipment for s in scenarios if s.area_equipment}
        if not found & set(f.equipment):
            return False
    if f.nodes:
        found_nodes = {rec.process_node_id} | {s.process_node_id for s in scenarios}
        if not found_nodes & set(f.nodes):
            return False
    if f.due_states and metrics.due_state(a, today) not in f.due_states:
        return False
    if f.overdue and not metrics.is_overdue(a, today):
        return False
    if f.unassigned and (a is None or not a.is_open or a.owner_key is not None):
        return False
    if f.missing_due_date and not metrics.needs_scheduling(a):
        return False
    if f.stage and f.stage not in metrics.stages(view):
        return False
    if f.matrix_risk and governing != f.matrix_risk:
        return False
    if f.matrix_column and metrics.matrix_column(view) != f.matrix_column:
        return False
    if f.search:
        text = _searchable(view, scope)
        if not all(term in text for term in f.search.lower().split()):
            return False
    return True


REGISTER_SORTS: dict[str, Callable[[RecommendationRow], Any]] = {
    "id": lambda r: (r.study_id, r.recommendation_number),
    "equipment": lambda r: r.area_equipment.lower(),
    "recommendation": lambda r: r.recommendation_text.lower(),
    "governingRisk": lambda r: {"high": 0, "medium": 1, "low": 2}.get(r.governing_risk or "", 3),
    "scenarioCount": lambda r: r.scenario_count,
    "node": lambda r: (r.process_node or "~").lower(),
    "disposition": lambda r: list(DISPOSITIONS).index(r.disposition),
    "department": lambda r: (r.department or "~").lower(),
    "owner": lambda r: (r.owner or "~").lower(),
    "dueDate": lambda r: (r.due_date is None, r.due_date or dt.date.max),
    "actionStatus": lambda r: (
        list(ACTION_STATUSES).index(r.action_status) if r.action_status else -1
    ),
    "updated": lambda r: r.updated_at,
}


def register(
    store: PsmStore,
    f: RegisterFilter,
    today: dt.date,
    *,
    sort: str = "id",
    descending: bool = False,
) -> list[RecommendationRow]:
    scope = store.scope(study_id=f.study_id, include_archived=f.include_archived)
    rows = [
        recommendation_row(v, scope, today) for v in views(scope) if matches(v, f, scope, today)
    ]
    key = REGISTER_SORTS.get(sort, REGISTER_SORTS["id"])
    rows.sort(key=lambda r: (key(r), r.study_id, r.recommendation_number), reverse=descending)
    return rows


# Actions list -----------------------------------------------------------------------

ACTION_TABS = (
    "all",
    "attention",
    "not_started",
    "in_progress",
    "pending_verification",
    "overdue",
    "closed",
)


@dataclass(frozen=True)
class ActionFilter:
    tab: str = "all"
    study_id: int | None = None
    departments: tuple[str, ...] = ()
    owners: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    due_states: tuple[str, ...] = ()
    aging: str | None = None  # open actions in one aging bucket
    search: str | None = None
    include_archived: bool = False


def _in_tab(out: ActionOut, tab: str) -> bool:
    if tab == "all":
        return True
    if tab == "attention":
        return bool(out.attention)
    if tab == "overdue":
        return out.overdue
    return out.status == tab


ACTION_SORTS: dict[str, Callable[[ActionOut], Any]] = {
    "action": lambda a: a.action_number,
    "recommendation": lambda a: a.recommendation_display_id,
    "equipment": lambda a: a.area_equipment.lower(),
    "risk": lambda a: {"high": 0, "medium": 1, "low": 2}.get(a.governing_risk or "", 3),
    "department": lambda a: (a.department or "~").lower(),
    "owner": lambda a: (a.owner_name or "~").lower(),
    "dueDate": lambda a: (a.due_date is None, a.due_date or dt.date.max),
    "status": lambda a: list(ACTION_STATUSES).index(a.status),
    "age": lambda a: a.age_days,
    "updated": lambda a: a.updated_at,
}


def action_list(
    store: PsmStore,
    f: ActionFilter,
    today: dt.date,
    *,
    sort: str = "dueDate",
    descending: bool = False,
) -> tuple[list[ActionOut], dict[str, int]]:
    """Matching actions of official recommendations, and per-tab counts of the
    actions matching every filter but the tab."""
    scope = store.scope(study_id=f.study_id, include_archived=f.include_archived)
    found: list[ActionOut] = []
    for view in views(scope):
        if view.action is None or view.is_draft:
            continue
        if view.action.archived and not f.include_archived:
            continue
        out = action_out(view, today)
        if (
            f.departments
            and (str(out.department_id) if out.department_id else "unassigned") not in f.departments
        ):
            continue
        if f.owners and (view.action.owner_key or "unassigned") not in f.owners:
            continue
        if f.risks and out.governing_risk not in f.risks:
            continue
        if f.due_states and out.due_state not in f.due_states:
            continue
        if f.aging and (
            not view.action.is_open or metrics.aging_bucket(view.action, today) != f.aging
        ):
            continue
        if f.search:
            text = _searchable(view, scope)
            if not all(term in text for term in f.search.lower().split()):
                continue
        found.append(out)
    counts = {tab: sum(_in_tab(a, tab) for a in found) for tab in ACTION_TABS}
    rows = [a for a in found if _in_tab(a, f.tab)]
    key = ACTION_SORTS.get(sort, ACTION_SORTS["dueDate"])
    rows.sort(key=lambda a: (key(a), a.action_number), reverse=descending)
    return rows, counts


# Studies ----------------------------------------------------------------------------

STUDY_FIELDS = (
    "study_code",
    "title",
    "year",
    "study_type_id",
    "description",
    "recommendation_prefix",
    "status",
    "study_date",
)


def _validate_study(store: PsmStore, request: StudyWrite, current: PsmStudy | None) -> None:
    study_type = store.get(PsmStudyType, request.study_type_id)
    if study_type is None or (
        not study_type.active and (current is None or current.study_type_id != study_type.id)
    ):
        raise RecordRuleError("invalid_study_type", "Choose a study type.", field="studyTypeId")
    s = PsmStudy
    for column, value, label, field_name in (
        (s.study_code, request.study_code, "study code", "studyCode"),
        (
            s.recommendation_prefix,
            request.recommendation_prefix,
            "recommendation prefix",
            "recommendationPrefix",
        ),
    ):
        statement = select(s.id).where(func.lower(column) == value.lower())
        if current is not None:
            statement = statement.where(s.id != current.id)
        if store.session.scalar(statement) is not None:
            raise RecordRuleError(
                "duplicate", f"Another study already uses this {label}.", field=field_name
            )
    known = {a.id for a in store.areas()}
    if not set(request.area_ids) <= known:
        raise RecordRuleError("invalid_area", "Choose areas from the list.", field="areaIds")


def create_study(store: PsmStore, request: StudyWrite, actor: Actor) -> int:
    def work(change_set: uuid.UUID) -> int:
        _validate_study(store, request, None)
        study = PsmStudy(
            **{name: getattr(request, name) for name in STUDY_FIELDS},
            created_by=actor.actor_id,
            updated_by=actor.actor_id,
            created_at=actor.now,
            updated_at=actor.now,
        )
        store.session.add(study)
        store.flush()
        store.set_study_areas(study.id, request.area_ids)
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "create",
                    STUDY,
                    study_key(study.id),
                    None,
                    {**_values(study, STUDY_FIELDS), "area_ids": sorted(request.area_ids)},
                    "created",
                )
            ],
        )
        return study.id

    return _run(store, work)


def update_study(store: PsmStore, study_id: int, request: StudyWrite, actor: Actor) -> None:
    def work(change_set: uuid.UUID) -> None:
        study = store.get(PsmStudy, study_id, for_update=True)
        if study is None:
            raise RecordNotFoundError(study_id)
        _check_version(study, request.version)
        _validate_study(store, request, study)
        has_recs = store.session.scalar(
            select(PsmRecommendation.id).where(PsmRecommendation.study_id == study.id).limit(1)
        )
        if has_recs is not None and request.recommendation_prefix != study.recommendation_prefix:
            raise RecordRuleError(
                "prefix_in_use",
                "Recommendation IDs are already assigned with this prefix; it cannot change.",
                field="recommendationPrefix",
            )
        old = _values(study, STUDY_FIELDS)
        old_areas = sorted(a.id for a in store.study_areas([study.id]).get(study.id, []))
        for name in STUDY_FIELDS:
            setattr(study, name, getattr(request, name))
        study.archived_at = actor.now if request.status == "archived" else None
        new = _values(study, STUDY_FIELDS)
        changed_old = {k: v for k, v in old.items() if new[k] != v}
        changed_new = {k: new[k] for k in changed_old}
        if sorted(request.area_ids) != old_areas:
            changed_old["area_ids"] = old_areas
            changed_new["area_ids"] = sorted(request.area_ids)
            store.set_study_areas(study.id, request.area_ids)
        if not changed_new:
            return
        _touch(study, actor)
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change("update", STUDY, study_key(study.id), changed_old, changed_new, "edited")
            ],
        )

    _run(store, work)


# Recommendations and scenarios ----------------------------------------------------------

REC_FIELDS = ("area_equipment", "recommendation_text", "process_node_id", "notes", "is_draft")
SCENARIO_FIELDS = (
    "sequence_number",
    "event",
    "cause",
    "consequence",
    "risk",
    "area_equipment",
    "process_node_id",
)


def _node(store: PsmStore, node_id: int | None, current: int | None = None) -> int | None:
    if node_id is None:
        return None
    node = store.get(PsmProcessNode, node_id)
    if node is None or (not node.active and node_id != current):
        raise RecordRuleError(
            "invalid_node", "Choose an active process node.", field="processNodeId"
        )
    return node_id


def _new_scenario(
    store: PsmStore, rec_id: int, number: int, values: ScenarioWrite, actor: Actor
) -> PsmScenario:
    scenario = PsmScenario(
        recommendation_id=rec_id,
        sequence_number=number,
        event=values.event,
        cause=values.cause,
        consequence=values.consequence,
        risk=values.risk,
        area_equipment=values.area_equipment,
        process_node_id=_node(store, values.process_node_id),
        created_at=actor.now,
        created_by=actor.actor_id,
        updated_at=actor.now,
        updated_by=actor.actor_id,
    )
    store.session.add(scenario)
    return scenario


def create_recommendation(store: PsmStore, request: RecommendationCreate, actor: Actor) -> int:
    def work(change_set: uuid.UUID) -> int:
        study = store.get(PsmStudy, request.study_id, for_update=True)
        if study is None:
            raise RecordRuleError("invalid_study", "Choose a study.", field="studyId")
        if study.status == "archived":
            raise RecordRuleError("study_archived", "This study is archived.", field="studyId")
        store.lock(NUMBER_LOCK_KEY)
        number = store.next_recommendation_number(study.id)
        rec = PsmRecommendation(
            study_id=study.id,
            recommendation_number=number,
            display_id=display_id(study.recommendation_prefix, number),
            area_equipment=request.area_equipment,
            recommendation_text=request.recommendation_text,
            process_node_id=_node(store, request.process_node_id),
            notes=request.notes,
            is_draft=request.is_draft,
            created_at=actor.now,
            created_by=actor.actor_id,
            updated_at=actor.now,
            updated_by=actor.actor_id,
        )
        store.session.add(rec)
        store.flush()
        scenarios = [
            _new_scenario(store, rec.id, i, s, actor) for i, s in enumerate(request.scenarios, 1)
        ]
        store.flush()
        changes = [
            _change(
                "create",
                RECOMMENDATION,
                recommendation_key(rec.id),
                None,
                {"display_id": rec.display_id, **_values(rec, REC_FIELDS)},
                "created",
            )
        ]
        changes += [
            _change(
                "create",
                SCENARIO,
                scenario_key(rec.id, s.id),
                None,
                _values(s, SCENARIO_FIELDS),
                "scenario_added",
            )
            for s in scenarios
        ]
        store.audit(
            actor_id=actor.actor_id, change_set_id=change_set, at=actor.now, changes=changes
        )
        return rec.id

    return _run(store, work)


def update_recommendation(
    store: PsmStore, rec_id: int, request: RecommendationUpdate, actor: Actor
) -> None:
    def work(change_set: uuid.UUID) -> None:
        rec = _locked_recommendation(store, rec_id, request.version)
        _refuse_archived(rec)
        if not request.is_draft and not store.scenarios_of(rec.id):
            raise RecordRuleError(
                "scenario_required",
                "Add at least one hazard scenario before finalizing the recommendation.",
                field="isDraft",
            )
        if request.is_draft and not rec.is_draft and rec.disposition != "pending_review":
            raise RecordRuleError(
                "decided",
                "A recommendation with a disposition cannot become a draft.",
                field="isDraft",
            )
        old = _values(rec, REC_FIELDS)
        rec.area_equipment = request.area_equipment
        rec.recommendation_text = request.recommendation_text
        rec.process_node_id = _node(store, request.process_node_id, rec.process_node_id)
        rec.notes = request.notes
        rec.is_draft = request.is_draft
        new = _values(rec, REC_FIELDS)
        changed = {k for k in REC_FIELDS if old[k] != new[k]}
        if not changed:
            return
        _touch(rec, actor)
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "update",
                    RECOMMENDATION,
                    recommendation_key(rec.id),
                    {k: old[k] for k in changed},
                    {k: new[k] for k in changed},
                    "edited",
                )
            ],
        )

    _run(store, work)


def add_scenario(store: PsmStore, rec_id: int, request: ScenarioWrite, actor: Actor) -> None:
    def work(change_set: uuid.UUID) -> None:
        rec = _locked_recommendation(store, rec_id, None)
        _refuse_archived(rec)
        scenario = _new_scenario(store, rec.id, store.next_scenario_number(rec.id), request, actor)
        store.flush()
        _touch(rec, actor, bump=False)
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "create",
                    SCENARIO,
                    scenario_key(rec.id, scenario.id),
                    None,
                    _values(scenario, SCENARIO_FIELDS),
                    "scenario_added",
                )
            ],
        )

    _run(store, work)


def update_scenario(
    store: PsmStore, rec_id: int, scenario_id: int, request: ScenarioUpdate, actor: Actor
) -> None:
    def work(change_set: uuid.UUID) -> None:
        rec = _locked_recommendation(store, rec_id, None)
        _refuse_archived(rec)
        scenario = store.get(PsmScenario, scenario_id, for_update=True)
        if scenario is None or scenario.recommendation_id != rec.id:
            raise RecordNotFoundError(scenario_id)
        _check_version(scenario, request.version)
        old = _values(scenario, SCENARIO_FIELDS)
        scenario.event = request.event
        scenario.cause = request.cause
        scenario.consequence = request.consequence
        scenario.risk = request.risk
        scenario.area_equipment = request.area_equipment
        scenario.process_node_id = _node(store, request.process_node_id, scenario.process_node_id)
        new = _values(scenario, SCENARIO_FIELDS)
        changed = {k for k in SCENARIO_FIELDS if old[k] != new[k]}
        if not changed:
            return
        _touch(scenario, actor)
        _touch(rec, actor, bump=False)
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "update",
                    SCENARIO,
                    scenario_key(rec.id, scenario.id),
                    {k: old[k] for k in changed},
                    {k: new[k] for k in changed},
                    "scenario_edited",
                )
            ],
        )

    _run(store, work)


def reorder_scenarios(store: PsmStore, rec_id: int, request: ScenarioOrder, actor: Actor) -> None:
    def work(change_set: uuid.UUID) -> None:
        rec = _locked_recommendation(store, rec_id, request.version)
        _refuse_archived(rec)
        scenarios = {s.id: s for s in store.scenarios_of(rec.id)}
        if sorted(request.scenario_ids) != sorted(scenarios):
            raise RecordRuleError(
                "invalid_order", "List every scenario of this recommendation exactly once."
            )
        old = [s.id for s in sorted(scenarios.values(), key=lambda s: s.sequence_number)]
        if old == request.scenario_ids:
            return
        for number, scenario_id in enumerate(request.scenario_ids, 1):
            scenarios[scenario_id].sequence_number = number
        _touch(rec, actor)
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "update",
                    RECOMMENDATION,
                    recommendation_key(rec.id),
                    {"scenario_order": old},
                    {"scenario_order": list(request.scenario_ids)},
                    "scenarios_reordered",
                )
            ],
        )

    _run(store, work)


def archive_recommendation(
    store: PsmStore, rec_id: int, request: ReasonRequest, actor: Actor
) -> None:
    def work(change_set: uuid.UUID) -> None:
        rec = _locked_recommendation(store, rec_id, request.version)
        _refuse_archived(rec)
        action = store.action_of(rec.id)
        if action is not None and action.archived_at is None and action.status != "closed":
            raise RecordRuleError(
                "open_action",
                "This recommendation has an open action. Close or resolve the action first.",
            )
        rec.archived_at = actor.now
        rec.archived_by = actor.actor_id
        rec.archive_reason = request.reason
        _touch(rec, actor)
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "update",
                    RECOMMENDATION,
                    recommendation_key(rec.id),
                    {"archived_at": None},
                    {"archived_at": _json(actor.now), "archive_reason": request.reason},
                    "archived",
                )
            ],
        )

    _run(store, work)


def restore_recommendation(
    store: PsmStore, rec_id: int, request: ReasonRequest, actor: Actor
) -> None:
    def work(change_set: uuid.UUID) -> None:
        rec = _locked_recommendation(store, rec_id, request.version)
        if rec.archived_at is None:
            raise RecordRuleError("not_archived", "This recommendation is not archived.")
        old = {"archived_at": _json(rec.archived_at), "archive_reason": rec.archive_reason}
        rec.archived_at = None
        rec.archived_by = None
        rec.archive_reason = None
        _touch(rec, actor)
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "update",
                    RECOMMENDATION,
                    recommendation_key(rec.id),
                    old,
                    {"archived_at": None, "reason": request.reason},
                    "restored",
                )
            ],
        )

    _run(store, work)


# Assignment ------------------------------------------------------------------------

ASSIGNMENT_FIELDS = ("department_id", "owner_user_id", "owner_name", "owner_email", "due_date")


@dataclass(frozen=True)
class Owner:
    user_id: uuid.UUID | None
    name: str | None
    email: str | None


def _owner(store: PsmStore, request: Assignment, current: PsmAction | None) -> Owner:
    """A platform user (by ID), a person recorded by name (and email) without an
    account, or nobody. A user's name is taken from their account."""
    if request.owner_user_id is not None:
        user = store.user(request.owner_user_id)
        unchanged = current is not None and current.owner_user_id == request.owner_user_id
        if user is None or (user.status != "active" and not unchanged):
            raise RecordRuleError("invalid_owner", "Choose an active user.", field="ownerUserId")
        return Owner(user.id, user.name, request.owner_email or user.email)
    if request.owner_name is not None:
        return Owner(None, request.owner_name, request.owner_email)
    if request.owner_email is not None:
        raise RecordRuleError(
            "owner_name_required",
            "Enter the owner's name with the email address.",
            field="ownerName",
        )
    return Owner(None, None, None)


def _department(store: PsmStore, department_id: int | None, current: int | None) -> int | None:
    if department_id is None:
        return None
    department = store.get(PsmDepartment, department_id)
    if department is None or (not department.active and department_id != current):
        raise RecordRuleError(
            "invalid_department", "Choose an active department.", field="departmentId"
        )
    return department_id


def _add_update(
    store: PsmStore,
    action: PsmAction,
    actor: Actor,
    update_type: str,
    body: str,
    previous: str | None = None,
    new: str | None = None,
) -> None:
    store.session.add(
        PsmActionUpdate(
            action_id=action.id,
            update_type=update_type,
            body=body,
            previous_status=previous,
            new_status=new,
            created_by=actor.actor_id,
            created_by_user_id=actor.user_id,
            created_by_name=_actor_name(actor),
            created_at=actor.now,
        )
    )


def _notify(
    store: PsmStore,
    action: PsmAction,
    rec: PsmRecommendation,
    event: str,
    detail: str | None,
    base_url: str | None,
    actor: Actor | None = None,
) -> None:
    store.flush()
    # Shared Notifications platform (transactional event + optional outbox).
    # When an enabled shared workflow exists for this event, skip the legacy
    # SMTP outbox so the owner is not emailed twice.
    from app.notifications.publisher import has_enabled_workflow, publish_notification_event
    from app.notifications.registry import PSM_LEGACY_TO_CODE

    shared_code = PSM_LEGACY_TO_CODE.get(event)
    if shared_code is not None:
        base = (base_url or "").rstrip("/")
        action_url = f"{base}/safety/psm/actions/{action.id}" if base else ""
        payload = {
            "action.reference": action.action_number,
            "action.title": action.title,
            "action.owner_name": action.owner_name,
            "action.due_date": action.due_date.isoformat() if action.due_date else None,
            "action.status": action.status,
            "action.url": action_url,
            "recommendation.reference": rec.display_id,
            "owner_email": action.owner_email,
            "owner_name": action.owner_name,
            "owner_user_id": str(action.owner_user_id) if action.owner_user_id else None,
        }
        if detail:
            payload["detail"] = detail
        publish_notification_event(
            store.session,
            event_type_code=shared_code,
            entity_type="safety.psm_action",
            entity_id=str(action.id),
            entity_reference=action.action_number,
            payload=payload,
            actor_user_id=actor.user_id if actor is not None else None,
            idempotency_key=f"{shared_code}:{action.id}:{action.version}:{event}",
            occurred_at=action.updated_at,
        )
        if has_enabled_workflow(store.session, shared_code):
            return
    notifications.enqueue(
        store.session,
        action=action,
        recommendation=rec,
        event=event,
        detail=detail,
        base_url=base_url,
    )


# Disposition -------------------------------------------------------------------------


def accept(
    store: PsmStore, rec_id: int, request: AcceptRequest, actor: Actor, base_url: str | None = None
) -> None:
    """Accept, generating the primary action (or reinstating the one kept from an
    earlier acceptance). Never creates a second action."""

    def work(change_set: uuid.UUID) -> None:
        rec = _locked_recommendation(store, rec_id, request.version)
        _refuse_archived(rec)
        if rec.is_draft:
            raise RecordRuleError("draft", "Finalize the draft before deciding its disposition.")
        if rec.disposition == "accepted":
            raise RecordRuleError("already_accepted", "This recommendation is already accepted.")
        if not store.scenarios_of(rec.id):
            raise RecordRuleError("scenario_required", "Add a hazard scenario first.")
        store.lock(NUMBER_LOCK_KEY)
        old_disposition = rec.disposition
        rec.disposition = "accepted"
        rec.disposition_at = actor.now
        rec.disposition_by_user_id = actor.user_id
        rec.disposition_by_name = _actor_name(actor)
        _touch(rec, actor)
        changes = [
            _change(
                "update",
                RECOMMENDATION,
                recommendation_key(rec.id),
                {"disposition": old_disposition},
                {"disposition": "accepted"},
                "disposition_changed",
            )
        ]
        action = store.action_of(rec.id, for_update=True)
        owner = _owner(store, request, action)
        department_id = _department(
            store, request.department_id, action.department_id if action else None
        )
        if action is None:
            year = _today(actor).year
            action = PsmAction(
                recommendation_id=rec.id,
                action_number=action_number(year, store.next_action_sequence(year)),
                title=f"Implement recommendation {rec.display_id}",
                description=request.task,
                department_id=department_id,
                owner_user_id=owner.user_id,
                owner_name=owner.name,
                owner_email=owner.email,
                due_date=request.due_date,
                created_at=actor.now,
                created_by=actor.actor_id,
                updated_at=actor.now,
                updated_by=actor.actor_id,
            )
            store.session.add(action)
            store.flush()
            changes.append(
                _change(
                    "create",
                    ACTION,
                    action_key(rec.id, action.id),
                    None,
                    {
                        "action_number": action.action_number,
                        "title": action.title,
                        "description": action.description,
                        "status": "not_started",
                        **_values(action, ASSIGNMENT_FIELDS),
                    },
                    "action_generated",
                )
            )
        else:
            # Accepted again after a rejection: the kept action is reinstated.
            old = {
                "requires_resolution": action.requires_resolution,
                "archived_at": _json(action.archived_at),
                **_values(action, ASSIGNMENT_FIELDS),
                "description": action.description,
            }
            action.requires_resolution = False
            action.archived_at = None
            action.archived_by = None
            action.archive_reason = None
            if department_id is not None:
                action.department_id = department_id
            if owner.name is not None:
                action.owner_user_id, action.owner_name, action.owner_email = (
                    owner.user_id,
                    owner.name,
                    owner.email,
                )
            if request.due_date is not None:
                action.due_date = request.due_date
            if request.task is not None:
                action.description = request.task
            _touch(action, actor)
            changes.append(
                _change(
                    "update",
                    ACTION,
                    action_key(rec.id, action.id),
                    old,
                    {
                        "requires_resolution": False,
                        "archived_at": None,
                        **_values(action, ASSIGNMENT_FIELDS),
                        "description": action.description,
                    },
                    "action_reinstated",
                )
            )
        _add_update(
            store,
            action,
            actor,
            "disposition",
            f"Recommendation {rec.display_id} accepted.",
        )
        store.audit(
            actor_id=actor.actor_id, change_set_id=change_set, at=actor.now, changes=changes
        )
        if action.owner_name is not None:
            _notify(store, action, rec, "action_assigned", None, base_url, actor=actor)

    _run(store, work)


def reject(store: PsmStore, rec_id: int, request: RejectRequest, actor: Actor) -> None:
    """Reject with a justification, kept permanently. An action generated by an
    earlier acceptance is kept and flagged for an administrator to resolve."""

    def work(change_set: uuid.UUID) -> None:
        rec = _locked_recommendation(store, rec_id, request.version)
        _refuse_archived(rec)
        if rec.is_draft:
            raise RecordRuleError("draft", "Finalize the draft before deciding its disposition.")
        old = {
            "disposition": rec.disposition,
            "disposition_justification": rec.disposition_justification,
        }
        if rec.disposition == "rejected" and rec.disposition_justification == request.justification:
            return
        event = (
            "rejection_justification_changed"
            if rec.disposition == "rejected"
            else "disposition_changed"
        )
        rec.disposition = "rejected"
        rec.disposition_justification = request.justification
        rec.disposition_at = actor.now
        rec.disposition_by_user_id = actor.user_id
        rec.disposition_by_name = _actor_name(actor)
        _touch(rec, actor)
        changes = [
            _change(
                "update",
                RECOMMENDATION,
                recommendation_key(rec.id),
                old,
                {"disposition": "rejected", "disposition_justification": request.justification},
                event,
            )
        ]
        if event == "disposition_changed":
            changes.append(
                _change(
                    "update",
                    RECOMMENDATION,
                    recommendation_key(rec.id),
                    {"disposition_justification": old["disposition_justification"]},
                    {"disposition_justification": request.justification},
                    "rejection_justification_added",
                )
            )
        action = store.action_of(rec.id, for_update=True)
        if action is not None and action.archived_at is None:
            action.requires_resolution = True
            _touch(action, actor)
            _add_update(
                store,
                action,
                actor,
                "disposition",
                "The recommendation was rejected after this action was generated. "
                "An administrator must decide whether to keep or archive the action. "
                f"Rejection justification: {request.justification}",
            )
            changes.append(
                _change(
                    "update",
                    ACTION,
                    action_key(rec.id, action.id),
                    {"requires_resolution": False},
                    {"requires_resolution": True},
                    "flagged_for_resolution",
                )
            )
        store.audit(
            actor_id=actor.actor_id, change_set_id=change_set, at=actor.now, changes=changes
        )

    _run(store, work)


def return_to_pending(store: PsmStore, rec_id: int, request: ReasonRequest, actor: Actor) -> None:
    """Undo a disposition decided in error, while no action exists."""

    def work(change_set: uuid.UUID) -> None:
        rec = _locked_recommendation(store, rec_id, request.version)
        _refuse_archived(rec)
        if rec.disposition == "pending_review":
            raise RecordRuleError(
                "already_pending", "This recommendation is already pending review."
            )
        if store.action_of(rec.id) is not None:
            raise RecordRuleError(
                "action_exists",
                "An action exists for this recommendation. Accept or reject it instead.",
            )
        old = {"disposition": rec.disposition}
        rec.disposition = "pending_review"
        rec.disposition_at = None
        rec.disposition_by_user_id = None
        rec.disposition_by_name = None
        _touch(rec, actor)
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "update",
                    RECOMMENDATION,
                    recommendation_key(rec.id),
                    old,
                    {"disposition": "pending_review", "reason": request.reason},
                    "disposition_changed",
                )
            ],
        )

    _run(store, work)


# Actions --------------------------------------------------------------------------------


def _action_with_rec(
    store: PsmStore, action_id: int, version: int | None
) -> tuple[PsmAction, PsmRecommendation]:
    action = _locked_action(store, action_id, version)
    rec = store.get(PsmRecommendation, action.recommendation_id)
    assert rec is not None  # noqa: S101 - foreign key
    return action, rec


def update_action(
    store: PsmStore,
    action_id: int,
    request: ActionUpdate,
    actor: Actor,
    base_url: str | None = None,
) -> None:
    """Edit the title, task, department, owner and due date. Never the status."""

    def work(change_set: uuid.UUID) -> None:
        action, rec = _action_with_rec(store, action_id, request.version)
        _refuse_inactive_action(action)
        if action.status == "closed":
            raise RecordRuleError(
                "action_closed", "This action is closed. Reopen it to make changes."
            )
        owner = _owner(store, request, action)
        department_id = _department(store, request.department_id, action.department_id)
        due_moved = action.due_date is not None and request.due_date != action.due_date
        if due_moved and action.status != "not_started":
            reason = request.due_date_reason or ""
            if len(reason) < MIN_REASON_LENGTH:
                raise RecordRuleError(
                    "reason_required",
                    "Work has begun on this action. Give a reason for changing the due date "
                    f"(at least {MIN_REASON_LENGTH} characters).",
                    field="dueDateReason",
                )
        key = action_key(rec.id, action.id)
        changes: list[AuditChange] = []
        notices: list[tuple[str, str | None]] = []

        def field_change(
            fields: dict[str, tuple[Any, Any]], event: str, extra: dict[str, Any] | None = None
        ) -> None:
            if all(old == new for old, new in fields.values()):
                return
            changes.append(
                _change(
                    "update",
                    ACTION,
                    key,
                    {k: _json(o) for k, (o, _) in fields.items()},
                    {**{k: _json(n) for k, (_, n) in fields.items()}, **(extra or {})},
                    event,
                )
            )

        field_change({"title": (action.title, request.title)}, "edited")
        field_change({"description": (action.description, request.task)}, "task_changed")
        field_change({"department_id": (action.department_id, department_id)}, "department_changed")
        owner_fields = {
            "owner_user_id": (action.owner_user_id, owner.user_id),
            "owner_name": (action.owner_name, owner.name),
            "owner_email": (action.owner_email, owner.email),
        }
        owner_changed = any(o != n for o, n in owner_fields.values())
        field_change(owner_fields, "owner_changed")
        due_changed = action.due_date != request.due_date
        field_change(
            {"due_date": (action.due_date, request.due_date)},
            "due_date_changed",
            {"reason": request.due_date_reason} if request.due_date_reason else None,
        )
        if not changes:
            return
        had_owner = action.owner_name is not None
        action.title = request.title
        action.description = request.task
        action.department_id = department_id
        action.owner_user_id, action.owner_name, action.owner_email = (
            owner.user_id,
            owner.name,
            owner.email,
        )
        action.due_date = request.due_date
        _touch(action, actor)
        summary = []
        if owner_changed:
            summary.append(f"Owner: {owner.name or 'Unassigned'}.")
            if owner.name is not None:
                notices.append(("owner_changed" if had_owner else "action_assigned", None))
        if due_changed:
            due_text = request.due_date.isoformat() if request.due_date else "not scheduled"
            summary.append(f"Due date: {due_text}.")
            if request.due_date_reason:
                summary.append(f"Reason: {request.due_date_reason}")
            notices.append(("due_date_changed", f"New due date: {due_text}"))
        if summary:
            _add_update(store, action, actor, "assignment", " ".join(summary))
        store.audit(
            actor_id=actor.actor_id, change_set_id=change_set, at=actor.now, changes=changes
        )
        for event, detail in notices:
            _notify(store, action, rec, event, detail, base_url, actor=actor)

    _run(store, work)


def change_status(
    store: PsmStore,
    action_id: int,
    request: StatusChange,
    actor: Actor,
    base_url: str | None = None,
) -> None:
    """Not Started <-> In Progress. Other moves have their own workflows."""

    def work(change_set: uuid.UUID) -> None:
        action, rec = _action_with_rec(store, action_id, request.version)
        _refuse_inactive_action(action)
        if (action.status, request.status) not in MANUAL_TRANSITIONS:
            raise RecordRuleError(
                "invalid_transition",
                f"An action cannot move from {ACTION_STATUSES[action.status]} to "
                f"{ACTION_STATUSES[request.status]} this way.",
                field="status",
            )
        old = action.status
        action.status = request.status
        _touch(action, actor)
        body = (
            request.note
            or f"Status changed from {ACTION_STATUSES[old]} to {ACTION_STATUSES[request.status]}."
        )
        _add_update(store, action, actor, "status_change", body, old, request.status)
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "update",
                    ACTION,
                    action_key(rec.id, action.id),
                    {"status": old},
                    {"status": request.status},
                    "status_changed",
                )
            ],
        )
        _notify(
            store,
            action,
            rec,
            "status_changed",
            f"Status: {ACTION_STATUSES[request.status]}",
            base_url,
            actor=actor,
        )

    _run(store, work)


def request_closure(
    store: PsmStore,
    action_id: int,
    request: ClosureRequest,
    actor: Actor,
    base_url: str | None = None,
) -> None:
    def work(change_set: uuid.UUID) -> None:
        action, rec = _action_with_rec(store, action_id, request.version)
        _refuse_inactive_action(action)
        if action.status not in ("not_started", "in_progress"):
            raise RecordRuleError(
                "invalid_transition",
                "Closure cannot be requested while the action is "
                f"{ACTION_STATUSES[action.status]}.",
            )
        if action.status == "not_started" and len(request.skip_reason or "") < MIN_REASON_LENGTH:
            raise RecordRuleError(
                "reason_required",
                "Work was never marked In Progress. Explain why the action is ready for "
                f"verification (at least {MIN_REASON_LENGTH} characters).",
                field="skipReason",
            )
        if request.exception_reason is not None:
            actor.require(
                Permission.PSM_ADMIN,
                "Only a PSM administrator can request closure without evidence.",
            )
            if len(request.exception_reason) < MIN_REASON_LENGTH:
                raise RecordRuleError(
                    "reason_required",
                    "Document why no evidence is attached.",
                    field="exceptionReason",
                )
        elif store.active_evidence_count(action.id) == 0:
            raise RecordRuleError(
                "evidence_required",
                "Attach at least one piece of evidence before requesting closure.",
                field="evidence",
            )
        old = action.status
        action.status = "pending_verification"
        action.closure_summary = request.summary
        action.closure_exception_reason = request.exception_reason
        action.closure_requested_at = actor.now
        action.closure_requested_by = actor.actor_id
        action.closure_requested_by_name = _actor_name(actor)
        _touch(action, actor)
        body = f"Closure requested. Summary: {request.summary}"
        if request.skip_reason:
            body += f"\nReady without being marked In Progress: {request.skip_reason}"
        if request.exception_reason:
            body += f"\nDocumented exception (no evidence): {request.exception_reason}"
        _add_update(store, action, actor, "closure_request", body, old, "pending_verification")
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "update",
                    ACTION,
                    action_key(rec.id, action.id),
                    {"status": old},
                    {
                        "status": "pending_verification",
                        "closure_summary": request.summary,
                        "closure_exception_reason": request.exception_reason,
                        "skip_reason": request.skip_reason,
                    },
                    "closure_requested",
                )
            ],
        )
        _notify(store, action, rec, "closure_requested", None, base_url, actor=actor)

    _run(store, work)


def approve_closure(
    store: PsmStore,
    action_id: int,
    request: VerificationApprove,
    actor: Actor,
    base_url: str | None = None,
) -> None:
    def work(change_set: uuid.UUID) -> None:
        action, rec = _action_with_rec(store, action_id, request.version)
        _refuse_inactive_action(action)
        if action.status != "pending_verification":
            raise RecordRuleError(
                "invalid_transition", "Only an action pending verification can be closed."
            )
        action.status = "closed"
        action.verified_at = actor.now
        action.verified_by = actor.actor_id
        action.verified_by_name = _actor_name(actor)
        action.closed_at = actor.now
        _touch(action, actor)
        body = "Closure verified and the action closed."
        if request.note:
            body += f" {request.note}"
        _add_update(
            store, action, actor, "closure_approved", body, "pending_verification", "closed"
        )
        key = action_key(rec.id, action.id)
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "update",
                    ACTION,
                    key,
                    {"status": "pending_verification"},
                    {"verified_by_name": action.verified_by_name, "note": request.note},
                    "closure_verified",
                ),
                _change(
                    "update",
                    ACTION,
                    key,
                    {"status": "pending_verification"},
                    {"status": "closed"},
                    "closed",
                ),
            ],
        )
        _notify(store, action, rec, "closure_approved", None, base_url, actor=actor)

    _run(store, work)


def return_closure(
    store: PsmStore,
    action_id: int,
    request: ReasonRequest,
    actor: Actor,
    base_url: str | None = None,
) -> None:
    def work(change_set: uuid.UUID) -> None:
        action, rec = _action_with_rec(store, action_id, request.version)
        _refuse_inactive_action(action)
        if action.status != "pending_verification":
            raise RecordRuleError(
                "invalid_transition", "Only an action pending verification can be returned."
            )
        action.status = "in_progress"
        action.returned_at = actor.now
        action.return_reason = request.reason
        _touch(action, actor)
        _add_update(
            store,
            action,
            actor,
            "closure_returned",
            f"Returned to In Progress: {request.reason}",
            "pending_verification",
            "in_progress",
        )
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "update",
                    ACTION,
                    action_key(rec.id, action.id),
                    {"status": "pending_verification"},
                    {"status": "in_progress", "reason": request.reason},
                    "returned",
                )
            ],
        )
        _notify(store, action, rec, "closure_returned", f"Reason: {request.reason}", base_url, actor=actor)

    _run(store, work)


def reopen(
    store: PsmStore,
    action_id: int,
    request: ReasonRequest,
    actor: Actor,
    base_url: str | None = None,
) -> None:
    def work(change_set: uuid.UUID) -> None:
        action, rec = _action_with_rec(store, action_id, request.version)
        _refuse_inactive_action(action)
        if action.status != "closed":
            raise RecordRuleError("invalid_transition", "Only a closed action can be reopened.")
        old = {
            "status": "closed",
            "closed_at": _json(action.closed_at),
            "verified_at": _json(action.verified_at),
            "verified_by_name": action.verified_by_name,
        }
        action.status = "in_progress"
        action.closed_at = None
        action.verified_at = None
        action.verified_by = None
        action.verified_by_name = None
        action.reopened_at = actor.now
        action.reopen_reason = request.reason
        _touch(action, actor)
        _add_update(
            store, action, actor, "reopened", f"Reopened: {request.reason}", "closed", "in_progress"
        )
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "update",
                    ACTION,
                    action_key(rec.id, action.id),
                    old,
                    {"status": "in_progress", "reason": request.reason},
                    "reopened",
                )
            ],
        )
        _notify(store, action, rec, "reopened", f"Reason: {request.reason}", base_url, actor=actor)

    _run(store, work)


def comment(
    store: PsmStore,
    action_id: int,
    request: CommentRequest,
    actor: Actor,
    base_url: str | None = None,
) -> None:
    def work(change_set: uuid.UUID) -> None:
        action, rec = _action_with_rec(store, action_id, None)
        _refuse_inactive_action(action)
        _add_update(store, action, actor, "comment", request.body)
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "update",
                    ACTION,
                    action_key(rec.id, action.id),
                    None,
                    {"comment": request.body},
                    "comment_added",
                )
            ],
        )
        _notify(store, action, rec, "comment_added", request.body, base_url, actor=actor)

    _run(store, work)


def resolve(store: PsmStore, action_id: int, request: ResolutionRequest, actor: Actor) -> None:
    """An administrator's decision on an action whose recommendation was rejected:
    keep it, or archive it. Nothing is deleted."""

    def work(change_set: uuid.UUID) -> None:
        action, rec = _action_with_rec(store, action_id, request.version)
        if not action.requires_resolution:
            raise RecordRuleError("no_resolution_needed", "This action does not need a resolution.")
        action.requires_resolution = False
        if request.resolution == "archive":
            action.archived_at = actor.now
            action.archived_by = actor.actor_id
            action.archive_reason = request.reason
        _touch(action, actor)
        label = "kept" if request.resolution == "keep" else "archived"
        _add_update(
            store, action, actor, "disposition", f"Resolution: action {label}. {request.reason}"
        )
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "update",
                    ACTION,
                    action_key(rec.id, action.id),
                    {"requires_resolution": True},
                    {"resolution": request.resolution, "reason": request.reason},
                    "resolution_recorded",
                )
            ],
        )

    _run(store, work)


# Evidence ------------------------------------------------------------------------------


def safe_file_name(name: str) -> str:
    """The base name only, without path or control characters."""
    base = PurePath(name.replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return base[:255]


@dataclass(frozen=True)
class Upload:
    file_name: str
    evidence_type: str
    description: str | None
    content: bytes = field(repr=False)


def add_attachment(
    store: PsmStore,
    upload: Upload,
    actor: Actor,
    *,
    recommendation_id: int | None = None,
    action_id: int | None = None,
) -> int:
    def work(change_set: uuid.UUID) -> int:
        name = safe_file_name(upload.file_name)
        extension = PurePath(name).suffix.lower()
        if not name or extension not in ATTACHMENT_EXTENSIONS:
            raise RecordRuleError(
                "file_type",
                "This file type is not accepted. Use PDF, images, Office documents, text, "
                "CSV, email, DWG or ZIP files.",
                field="file",
            )
        if not upload.content:
            raise RecordRuleError("empty_file", "The file is empty.", field="file")
        if len(upload.content) > MAX_ATTACHMENT_BYTES:
            raise RecordRuleError("file_too_large", "Files are limited to 10 MB.", field="file")
        if upload.evidence_type not in EVIDENCE_TYPES:
            raise RecordRuleError("evidence_type", "Choose an evidence type.", field="evidenceType")
        description = (upload.description or "").strip() or None
        if description is not None and len(description) > 1000:
            raise RecordRuleError("description", "Keep the description under 1,000 characters.")
        if action_id is not None:
            action, rec = _action_with_rec(store, action_id, None)
            _refuse_inactive_action(action)
            if action.status == "closed":
                raise RecordRuleError(
                    "action_closed", "This action is closed. Reopen it to add evidence."
                )
            parent_key = action_key(rec.id, action.id)
        else:
            assert recommendation_id is not None  # noqa: S101 - one parent is required
            rec = _locked_recommendation(store, recommendation_id, None)
            _refuse_archived(rec)
            parent_key = recommendation_key(rec.id)
        row = PsmAttachment(
            recommendation_id=None if action_id is not None else rec.id,
            action_id=action_id,
            evidence_type=upload.evidence_type,
            description=description,
            original_file_name=name,
            content_type=ATTACHMENT_EXTENSIONS[extension],
            size_bytes=len(upload.content),
            sha256=hashlib.sha256(upload.content).hexdigest(),
            uploaded_by=actor.actor_id,
            uploaded_by_user_id=actor.user_id,
            uploaded_by_name=_actor_name(actor),
            uploaded_at=actor.now,
        )
        store.session.add(row)
        store.flush()
        store.session.add(PsmAttachmentContent(attachment_id=row.id, content=upload.content))
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "create",
                    ATTACHMENT,
                    f"{parent_key}/attachments/{row.id}",
                    None,
                    {
                        "file_name": name,
                        "evidence_type": upload.evidence_type,
                        "description": description,
                        "size_bytes": row.size_bytes,
                        "sha256": row.sha256,
                    },
                    "evidence_added",
                )
            ],
        )
        return row.id

    return _run(store, work)


def remove_attachment(store: PsmStore, attachment_id: int, reason: str, actor: Actor) -> None:
    def work(change_set: uuid.UUID) -> None:
        if len(reason.strip()) < MIN_REASON_LENGTH:
            raise RecordRuleError(
                "reason_required",
                f"Give a reason (at least {MIN_REASON_LENGTH} characters).",
                field="reason",
            )
        row = store.get(PsmAttachment, attachment_id, for_update=True)
        if row is None:
            raise RecordNotFoundError(attachment_id)
        if row.removed_at is not None:
            raise RecordRuleError("already_removed", "This evidence was already removed.")
        if row.action_id is not None:
            action, rec = _action_with_rec(store, row.action_id, None)
            if action.status in ("pending_verification", "closed"):
                raise RecordRuleError(
                    "locked_evidence",
                    "Evidence cannot be removed while closure is pending or after closure.",
                )
            parent_key = action_key(rec.id, action.id)
        else:
            assert row.recommendation_id is not None  # noqa: S101 - check constraint
            parent_key = recommendation_key(row.recommendation_id)
        row.removed_at = actor.now
        row.removed_by = actor.actor_id
        row.removed_by_name = _actor_name(actor)
        row.removal_reason = reason.strip()
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[
                _change(
                    "update",
                    ATTACHMENT,
                    f"{parent_key}/attachments/{row.id}",
                    {"removed_at": None, "file_name": row.original_file_name},
                    {"removed_at": _json(actor.now), "reason": row.removal_reason},
                    "evidence_removed",
                )
            ],
        )

    _run(store, work)


# Reference data -------------------------------------------------------------------------


def save_reference(
    store: PsmStore,
    model: type[PsmDepartment] | type[PsmProcessNode],
    request: ReferenceWrite,
    actor: Actor,
    row_id: int | None = None,
) -> int:
    """Add or rename a department or process node. Near-duplicates (same name
    ignoring case and spacing) are refused."""

    def work(change_set: uuid.UUID) -> int:
        limit = 200 if model is PsmDepartment else 1000
        if len(request.name) > limit:
            raise RecordRuleError(
                "name_too_long", f"Keep the name under {limit} characters.", field="name"
            )
        key = name_key(request.name)
        if store.name_key_taken(model, key, row_id):
            raise RecordRuleError(
                "near_duplicate",
                "An entry with the same name (ignoring case and spacing) already exists.",
                field="name",
            )
        audit_key = f"psm/reference/{model.__tablename__}"
        if row_id is None:
            order = store.session.scalar(select(func.max(model.display_order))) or 0
            row = model(
                name=request.name,
                name_key=key,
                active=request.active,
                display_order=order + 1,
                created_at=actor.now,
                created_by=actor.actor_id,
                updated_at=actor.now,
                updated_by=actor.actor_id,
            )
            store.session.add(row)
            store.flush()
            new = {"name": row.name, "active": row.active}
            changes = [_change("create", REFERENCE, f"{audit_key}/{row.id}", None, new, "created")]
        else:
            row = store.get(model, row_id, for_update=True)
            if row is None:
                raise RecordNotFoundError(row_id)
            old = {"name": row.name, "active": row.active}
            row.name, row.name_key, row.active = request.name, key, request.active
            row.updated_at, row.updated_by = actor.now, actor.actor_id
            new = {"name": row.name, "active": row.active}
            if old == new:
                return row.id
            changes = [_change("update", REFERENCE, f"{audit_key}/{row.id}", old, new, "edited")]
        store.audit(
            actor_id=actor.actor_id, change_set_id=change_set, at=actor.now, changes=changes
        )
        return row.id

    return _run(store, work)


def save_notification_settings(
    store: PsmStore, request: NotificationSettingsWrite, actor: Actor
) -> None:
    def work(change_set: uuid.UUID) -> None:
        row = store.get(PsmNotificationSettings, 1, for_update=True)
        if row is None:
            raise RecordNotFoundError(1)
        fields = tuple(NotificationSettingsWrite.model_fields)
        old = _values(row, fields)
        for name in fields:
            setattr(row, name, getattr(request, name))
        new = _values(row, fields)
        if old == new:
            return
        row.updated_at, row.updated_by = actor.now, actor.actor_id
        store.audit(
            actor_id=actor.actor_id,
            change_set_id=change_set,
            at=actor.now,
            changes=[_change("update", REFERENCE, "psm/notification-settings", old, new, "edited")],
        )

    _run(store, work)
