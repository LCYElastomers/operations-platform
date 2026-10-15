"""Process Safety Management endpoints (``/safety/psm``).

Reading needs ``psm.view``. Each change needs its own permission: studies
(``psm.manageStudies``), recommendations and scenarios
(``psm.editRecommendations``), dispositions (``psm.decideDisposition``), action
assignment and status (``psm.manageActions``), closure requests
(``psm.requestClosure``), verification (``psm.verifyClosure``), reopening
(``psm.reopen``), reference data, notification settings and resolutions
(``psm.admin``) and imports (``psm.import``).

Email is sent after the change commits; a delivery failure never undoes it.
"""

import datetime as dt
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.auth import people
from app.core.authorization import (
    UserPrincipal,
    require_any_permission,
    require_permission,
)
from app.core.config import get_settings
from app.core.permissions import Permission
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.quality.cost.records import RecordForbiddenError, RecordNotFoundError, RecordRuleError
from app.quality.cost.router import actor_of
from app.safety.psm import metrics, notifications, pha_import, service
from app.safety.psm.models import (
    PsmAction,
    PsmAttachment,
    PsmAttachmentContent,
    PsmDepartment,
    PsmProcessNode,
    PsmRecommendation,
)
from app.safety.psm.reference import (
    ACTION_STATUSES,
    DISPOSITIONS,
    EVIDENCE_TYPES,
    MAX_ATTACHMENT_BYTES,
    RISKS,
)
from app.safety.psm.reports import (
    ActionFilters,
    RecommendationFilters,
    action_filter,
    register_filter,
)
from app.safety.psm.schemas import (
    Abilities,
    AcceptRequest,
    ActionDetail,
    ActionPage,
    ActionUpdate,
    ClosureRequest,
    CodeLabel,
    CommentRequest,
    DashboardList,
    DashboardOut,
    DepartmentLoadOut,
    NotificationSettingsWrite,
    Option,
    OptionsOut,
    OwnerLoadOut,
    ReasonRequest,
    RecommendationCreate,
    RecommendationDetail,
    RecommendationPage,
    RecommendationUpdate,
    ReferenceWrite,
    RejectRequest,
    ResolutionRequest,
    ScenarioOrder,
    ScenarioUpdate,
    ScenarioWrite,
    StageOut,
    StatusChange,
    StudyOut,
    StudyWrite,
    Timeline,
    TimelineEvent,
    VerificationApprove,
)
from app.safety.psm.store import PsmStore
from app.safety.site_calendar import site_today

router = APIRouter(prefix="/safety/psm", tags=["safety"])

P = Permission
MAX_PAGE = 200


def _error(status_code: int, error: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error": error, "message": message, **extra}
    )


def _unavailable() -> HTTPException:
    return _error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "database_unavailable",
        "Process Safety Management data is unavailable because the database could not be reached.",
    )


def psm_store() -> Iterator[PsmStore]:
    try:
        sessions = get_sessionmaker()
    except DatabaseNotConfiguredError:
        raise _unavailable() from None
    with sessions() as session:
        yield PsmStore(session)


def _role(*permissions: Permission) -> Any:
    if len(permissions) == 1:
        return Depends(require_permission(permissions[0]))
    return Depends(require_any_permission(*permissions))


Store = Annotated[PsmStore, Depends(psm_store)]
Viewer = Annotated[UserPrincipal, _role(P.PSM_VIEW)]
StudyManager = Annotated[UserPrincipal, _role(P.PSM_MANAGE_STUDIES)]
Editor = Annotated[UserPrincipal, _role(P.PSM_EDIT_RECOMMENDATIONS)]
NodeEditor = Annotated[UserPrincipal, _role(P.PSM_EDIT_RECOMMENDATIONS, P.PSM_ADMIN)]
Decider = Annotated[UserPrincipal, _role(P.PSM_DECIDE_DISPOSITION)]
ActionManager = Annotated[UserPrincipal, _role(P.PSM_MANAGE_ACTIONS)]
ActionWorker = Annotated[UserPrincipal, _role(P.PSM_MANAGE_ACTIONS, P.PSM_REQUEST_CLOSURE)]
ClosureRequester = Annotated[UserPrincipal, _role(P.PSM_REQUEST_CLOSURE)]
Verifier = Annotated[UserPrincipal, _role(P.PSM_VERIFY_CLOSURE)]
Reopener = Annotated[UserPrincipal, _role(P.PSM_REOPEN)]
Admin = Annotated[UserPrincipal, _role(P.PSM_ADMIN)]
Importer = Annotated[UserPrincipal, _role(P.PSM_IMPORT)]
EvidenceWriter = Annotated[
    UserPrincipal,
    _role(P.PSM_EDIT_RECOMMENDATIONS, P.PSM_MANAGE_ACTIONS, P.PSM_REQUEST_CLOSURE),
]
Codes = Annotated[list[str] | None, Query(max_length=30)]
Text = Annotated[str | None, Query(max_length=200)]

RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not signed in"},
    403: {"description": "Missing permission"},
    503: {"description": "Database unavailable"},
}
WRITE_RESPONSES: dict[int | str, dict[str, Any]] = {
    **RESPONSES,
    404: {"description": "No such record"},
    409: {"description": "Changed since it was loaded; nothing saved"},
    422: {"description": "Invalid request; nothing saved"},
}


def _today() -> dt.date:
    return site_today(dt.datetime.now(dt.UTC))


def abilities(principal: UserPrincipal) -> Abilities:
    p = principal.has
    return Abilities(
        edit_recommendation=p(P.PSM_EDIT_RECOMMENDATIONS),
        decide_disposition=p(P.PSM_DECIDE_DISPOSITION),
        manage_actions=p(P.PSM_MANAGE_ACTIONS),
        request_closure=p(P.PSM_REQUEST_CLOSURE),
        verify_closure=p(P.PSM_VERIFY_CLOSURE),
        reopen=p(P.PSM_REOPEN),
        admin=p(P.PSM_ADMIN),
        manage_studies=p(P.PSM_MANAGE_STUDIES),
        import_data=p(P.PSM_IMPORT),
        export=p(P.PSM_EXPORT),
    )


def _write_error(error: Exception) -> HTTPException:
    if isinstance(error, RecordNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "record_not_found", "No such record.")
    if isinstance(error, RecordForbiddenError):
        return _error(status.HTTP_403_FORBIDDEN, "permission_denied", error.message)
    if isinstance(error, service.PsmConflictError):
        return _error(
            status.HTTP_409_CONFLICT,
            "edit_conflict",
            "This record was changed by someone else since you loaded it. Nothing was saved. "
            "Reload to see the current values.",
        )
    if isinstance(error, RecordRuleError):
        return _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, error.error, error.message, field=error.field
        )
    if isinstance(error, pha_import.ImportValidationError):
        return _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "import_validation_failed",
            "The worksheet did not pass validation. Nothing was imported.",
            errors=error.errors,
        )
    if isinstance(error, IntegrityError):
        return _error(
            status.HTTP_409_CONFLICT,
            "duplicate",
            "This would duplicate an existing record. Nothing was saved.",
        )
    return _unavailable()


_WRITE_ERRORS = (
    RecordNotFoundError,
    RecordForbiddenError,
    RecordRuleError,
    service.PsmConflictError,
    pha_import.ImportValidationError,
    SQLAlchemyError,
)


def _deliver_later(background: BackgroundTasks) -> None:
    settings = get_settings()
    if settings.mail_enabled:
        background.add_task(notifications.deliver, get_sessionmaker(), settings)


def _base_url() -> str | None:
    return get_settings().app_public_url


# Options and dashboard ----------------------------------------------------------------


@router.get("/options", response_model=OptionsOut, responses=RESPONSES)
def options(principal: Viewer, store: Store) -> OptionsOut:
    try:
        scope = store.scope()
        studies = store.studies()
        types = store.study_types()
        areas = store.areas()
        elements = store.elements()
    except SQLAlchemyError:
        raise _unavailable() from None
    owners: dict[str, str] = {}
    equipment: set[str] = set()
    for view in service.views(scope):
        rec: PsmRecommendation = view.extra["rec"]  # type: ignore[assignment]
        equipment.add(rec.area_equipment)
        equipment.update(s.area_equipment for s in view.extra["scenarios"] if s.area_equipment)  # type: ignore[attr-defined]
        if view.action and view.action.owner_key:
            owners[view.action.owner_key] = view.action.owner or ""
    return OptionsOut(
        studies=[Option(id=s.id, name=s.title, active=s.status != "archived") for s in studies],
        study_types=[Option(id=t.id, name=t.name, active=t.active) for t in types],
        areas=[Option(id=a.id, name=f"{a.code} {a.name}", active=True) for a in areas],
        departments=[
            Option(id=d.id, name=d.name, active=d.active) for d in scope.departments.values()
        ],
        process_nodes=[Option(id=n.id, name=n.name, active=n.active) for n in scope.nodes.values()],
        equipment=sorted(equipment, key=str.lower),
        owners=[
            CodeLabel(code=k, label=v)
            for k, v in sorted(owners.items(), key=lambda i: i[1].lower())
        ],
        elements=[CodeLabel(code=e.code, label=f"{e.name} ({e.regulation})") for e in elements],
        dispositions=[CodeLabel(code=k, label=v) for k, v in DISPOSITIONS.items()],
        action_statuses=[CodeLabel(code=k, label=v) for k, v in ACTION_STATUSES.items()],
        risks=[CodeLabel(code=k, label=v) for k, v in RISKS.items()],
        evidence_types=[CodeLabel(code=k, label=v) for k, v in EVIDENCE_TYPES.items()],
        abilities=abilities(principal),
    )


def _dashboard_item(view: metrics.RecommendationView) -> DashboardList:
    action: PsmAction = view.extra["action"]  # type: ignore[assignment]
    assert view.action is not None  # noqa: S101 - lists hold actions only
    return DashboardList(
        recommendation_id=view.id,
        display_id=view.display_id,
        action_id=action.id,
        action_number=action.action_number,
        title=action.description or action.title,
        owner=action.owner_name,
        department=view.action.department,
        due_date=action.due_date,
        status=action.status,
        governing_risk=metrics.governing_risk(view.scenario_risks),
    )


@router.get("/dashboard", response_model=DashboardOut, responses=RESPONSES)
def dashboard(
    principal: Viewer,
    store: Store,
    study_id: Annotated[int | None, Query(alias="studyId")] = None,
) -> DashboardOut:
    """Command Center figures for one study or every study (``studyId`` omitted)."""
    today = _today()
    try:
        recs = service.views(store.scope(study_id=study_id))
    except SQLAlchemyError:
        raise _unavailable() from None
    k = metrics.kpis(recs, today)
    counts = metrics.lifecycle(recs)
    return DashboardOut(
        scope_study_id=study_id,
        today=today,
        kpis={
            "total": k.total,
            "pending": k.pending,
            "accepted": k.accepted,
            "rejected": k.rejected,
            "notStarted": k.not_started,
            "inProgress": k.in_progress,
            "pendingVerification": k.pending_verification,
            "closed": k.closed,
            "overdue": k.overdue,
            "needsScheduling": k.needs_scheduling,
            "closurePct": k.closure_pct,
            "actions": k.actions,
        },
        lifecycle=[
            StageOut(code=c, label=label, definition=d, count=counts[c])
            for c, label, d in metrics.STAGES
        ],
        rejected=StageOut(
            code=metrics.REJECTED_STAGE[0],
            label=metrics.REJECTED_STAGE[1],
            definition=metrics.REJECTED_STAGE[2],
            count=counts["rejected"],
        ),
        scenario_risks=metrics.scenario_risks(recs),
        governing_risks=metrics.governing_risks(recs),
        matrix=metrics.matrix(recs),
        matrix_columns=[CodeLabel(code=c, label=label) for c, label in metrics.MATRIX_COLUMNS],
        departments=[
            DepartmentLoadOut(department=name, department_id=dep_id, counts=c)
            for name, dep_id, c in metrics.by_department(recs)
        ],
        aging=[
            {"code": code, "label": label, "count": metrics.aging(recs, today)[code]}
            for code, label, _, _ in metrics.AGING_BUCKETS
        ],
        due_7=[_dashboard_item(v) for v in metrics.deadlines(recs, today, 7)],
        due_30=[_dashboard_item(v) for v in metrics.deadlines(recs, today, 30)],
        overdue=[_dashboard_item(v) for v in metrics.overdue(recs, today)],
        needs_scheduling=k.needs_scheduling,
        distribution=[
            OwnerLoadOut(
                owner=load.owner,
                owner_key=load.owner_key,
                not_started=load.not_started,
                in_progress=load.in_progress,
                pending_verification=load.pending_verification,
                overdue=load.overdue,
                total_active=load.total_active,
            )
            for load in metrics.distribution(recs, today)
        ],
        drafts=sum(r.is_draft and not r.archived for r in recs),
    )


# Studies ---------------------------------------------------------------------------------


def _studies(store: PsmStore, study_ids: list[int] | None = None) -> list[StudyOut]:
    today = _today()
    studies = [s for s in store.studies() if study_ids is None or s.id in study_ids]
    types = {t.id: t.name for t in store.study_types()}
    areas = store.study_areas([s.id for s in studies])
    recs = service.views(store.scope())
    return [
        service.study_out(
            s,
            types.get(s.study_type_id, ""),
            areas.get(s.id, []),
            [r for r in recs if r.study_id == s.id],
            today,
        )
        for s in studies
    ]


@router.get("/studies", response_model=list[StudyOut], responses=RESPONSES)
def list_studies(principal: Viewer, store: Store) -> list[StudyOut]:
    try:
        return _studies(store)
    except SQLAlchemyError:
        raise _unavailable() from None


@router.get("/studies/{study_id}", response_model=StudyOut, responses=RESPONSES)
def get_study(principal: Viewer, store: Store, study_id: int) -> StudyOut:
    try:
        found = _studies(store, [study_id])
    except SQLAlchemyError:
        raise _unavailable() from None
    if not found:
        raise _error(status.HTTP_404_NOT_FOUND, "record_not_found", "No such study.")
    return found[0]


@router.post("/studies", response_model=StudyOut, status_code=201, responses=WRITE_RESPONSES)
def create_study(principal: StudyManager, store: Store, request: StudyWrite) -> StudyOut:
    try:
        study_id = service.create_study(store, request, actor_of(principal))
        return _studies(store, [study_id])[0]
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None


@router.put("/studies/{study_id}", response_model=StudyOut, responses=WRITE_RESPONSES)
def update_study(
    principal: StudyManager, store: Store, study_id: int, request: StudyWrite
) -> StudyOut:
    try:
        service.update_study(store, study_id, request, actor_of(principal))
        return _studies(store, [study_id])[0]
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None


# Recommendations --------------------------------------------------------------------------


def recommendation_filters(
    study_id: Annotated[int | None, Query(alias="studyId")] = None,
    q: Text = None,
    disposition: Codes = None,
    action_status: Annotated[list[str] | None, Query(alias="actionStatus", max_length=30)] = None,
    governing_risk: Annotated[list[str] | None, Query(alias="governingRisk", max_length=30)] = None,
    scenario_risk: Annotated[list[str] | None, Query(alias="scenarioRisk", max_length=30)] = None,
    department: Codes = None,
    owner: Codes = None,
    equipment: Codes = None,
    node: Annotated[list[int] | None, Query(max_length=30)] = None,
    due_state: Annotated[list[str] | None, Query(alias="dueState", max_length=30)] = None,
    overdue: bool = False,
    unassigned: bool = False,
    missing_due_date: Annotated[bool, Query(alias="missingDueDate")] = False,
    stage: Text = None,
    matrix_risk: Annotated[str | None, Query(alias="matrixRisk", max_length=20)] = None,
    matrix_column: Annotated[str | None, Query(alias="matrixColumn", max_length=40)] = None,
    drafts: bool = False,
    archived: bool = False,
    sort: Annotated[str, Query(max_length=40)] = "id",
    desc: bool = False,
) -> RecommendationFilters:
    return RecommendationFilters(
        study_id=study_id,
        search=(q or "").strip() or None,
        disposition=disposition or [],
        action_status=action_status or [],
        governing_risk=governing_risk or [],
        scenario_risk=scenario_risk or [],
        department=department or [],
        owner=owner or [],
        equipment=equipment or [],
        node=node or [],
        due_state=due_state or [],
        overdue=overdue,
        unassigned=unassigned,
        missing_due_date=missing_due_date,
        stage=stage,
        matrix_risk=matrix_risk,
        matrix_column=matrix_column,
        drafts=drafts,
        archived=archived,
        sort=sort,
        desc=desc,
    )


@router.get("/recommendations", response_model=RecommendationPage, responses=RESPONSES)
def list_recommendations(
    principal: Viewer,
    store: Store,
    filters: Annotated[RecommendationFilters, Depends(recommendation_filters)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=MAX_PAGE)] = 25,
) -> RecommendationPage:
    try:
        rows = service.register(
            store, register_filter(filters), _today(), sort=filters.sort, descending=filters.desc
        )
    except SQLAlchemyError:
        raise _unavailable() from None
    start = (page - 1) * page_size
    return RecommendationPage(
        rows=rows[start : start + page_size], total=len(rows), page=page, page_size=page_size
    )


def _recommendation_detail(
    store: PsmStore, principal: UserPrincipal, rec_id: int
) -> RecommendationDetail:
    scope = store.scope(recommendation_ids=[rec_id], include_archived=True)
    if not scope.recommendations:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "record_not_found",
            "No such recommendation. It may have been removed from your view or never existed.",
        )
    today = _today()
    view = service.views(scope)[0]
    rec: PsmRecommendation = view.extra["rec"]  # type: ignore[assignment]
    study = _studies(store, [rec.study_id])[0]
    node = scope.nodes.get(rec.process_node_id) if rec.process_node_id else None
    return RecommendationDetail(
        id=rec.id,
        display_id=rec.display_id,
        study=study,
        recommendation_number=rec.recommendation_number,
        area_equipment=rec.area_equipment,
        recommendation_text=rec.recommendation_text,
        process_node_id=rec.process_node_id,
        process_node=node.name if node else None,
        governing_risk=metrics.governing_risk(view.scenario_risks),
        disposition=rec.disposition,
        disposition_justification=rec.disposition_justification,
        disposition_by_name=rec.disposition_by_name,
        disposition_at=rec.disposition_at,
        notes=rec.notes,
        is_draft=rec.is_draft,
        archived_at=rec.archived_at,
        archive_reason=rec.archive_reason,
        source_row_start=rec.source_row_start,
        source_row_end=rec.source_row_end,
        source_key=rec.source_key,
        version=rec.version,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
        scenarios=[service.scenario_out(s, scope.nodes) for s in scope.scenarios.get(rec.id, [])],
        action=service.action_out(view, today) if view.action else None,
        attachments=[
            service.attachment_out(a) for a in store.attachments(recommendation_id=rec.id)
        ],
        abilities=abilities(principal),
    )


@router.get("/recommendations/{rec_id}", response_model=RecommendationDetail, responses=RESPONSES)
def get_recommendation(principal: Viewer, store: Store, rec_id: int) -> RecommendationDetail:
    try:
        return _recommendation_detail(store, principal, rec_id)
    except SQLAlchemyError:
        raise _unavailable() from None


@router.get("/recommendations/{rec_id}/timeline", response_model=Timeline, responses=RESPONSES)
def recommendation_timeline(principal: Viewer, store: Store, rec_id: int) -> Timeline:
    """Every audited change to the recommendation, its scenarios, action and evidence."""
    try:
        if store.get(PsmRecommendation, rec_id) is None:
            raise _error(status.HTTP_404_NOT_FOUND, "record_not_found", "No such recommendation.")
        events = store.history(service.recommendation_key(rec_id))
    except SQLAlchemyError:
        raise _unavailable() from None
    entity = {
        service.RECOMMENDATION: "recommendation",
        service.SCENARIO: "scenario",
        service.ACTION: "action",
        service.ATTACHMENT: "evidence",
    }
    return Timeline(
        events=[
            TimelineEvent(
                occurred_at=e.occurred_at,
                actor_name=e.actor_name or people.actor_label(e.actor_id, {}),
                event=str((e.new_value or {}).get("event") or e.action),
                entity=entity.get(e.entity_type, "recommendation"),
                entity_key=e.entity_key,
                action=e.action,
                old_value=e.old_value,
                new_value={k: v for k, v in (e.new_value or {}).items() if k != "event"} or None,
            )
            for e in events
        ]
    )


@router.post(
    "/recommendations",
    response_model=RecommendationDetail,
    status_code=201,
    responses=WRITE_RESPONSES,
)
def create_recommendation(
    principal: Editor, store: Store, request: RecommendationCreate
) -> RecommendationDetail:
    try:
        rec_id = service.create_recommendation(store, request, actor_of(principal))
        return _recommendation_detail(store, principal, rec_id)
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None


def _rec_write(
    principal: UserPrincipal, store: PsmStore, rec_id: int, run: Any
) -> RecommendationDetail:
    try:
        run()
        return _recommendation_detail(store, principal, rec_id)
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None


@router.put(
    "/recommendations/{rec_id}", response_model=RecommendationDetail, responses=WRITE_RESPONSES
)
def update_recommendation(
    principal: Editor, store: Store, rec_id: int, request: RecommendationUpdate
) -> RecommendationDetail:
    actor = actor_of(principal)
    return _rec_write(
        principal,
        store,
        rec_id,
        lambda: service.update_recommendation(store, rec_id, request, actor),
    )


@router.post(
    "/recommendations/{rec_id}/scenarios",
    response_model=RecommendationDetail,
    responses=WRITE_RESPONSES,
)
def add_scenario(
    principal: Editor, store: Store, rec_id: int, request: ScenarioWrite
) -> RecommendationDetail:
    actor = actor_of(principal)
    return _rec_write(
        principal, store, rec_id, lambda: service.add_scenario(store, rec_id, request, actor)
    )


@router.put(
    "/recommendations/{rec_id}/scenarios/{scenario_id}",
    response_model=RecommendationDetail,
    responses=WRITE_RESPONSES,
)
def update_scenario(
    principal: Editor, store: Store, rec_id: int, scenario_id: int, request: ScenarioUpdate
) -> RecommendationDetail:
    actor = actor_of(principal)
    return _rec_write(
        principal,
        store,
        rec_id,
        lambda: service.update_scenario(store, rec_id, scenario_id, request, actor),
    )


@router.put(
    "/recommendations/{rec_id}/scenario-order",
    response_model=RecommendationDetail,
    responses=WRITE_RESPONSES,
)
def reorder_scenarios(
    principal: Editor, store: Store, rec_id: int, request: ScenarioOrder
) -> RecommendationDetail:
    actor = actor_of(principal)
    return _rec_write(
        principal, store, rec_id, lambda: service.reorder_scenarios(store, rec_id, request, actor)
    )


@router.post(
    "/recommendations/{rec_id}/accept",
    response_model=RecommendationDetail,
    responses=WRITE_RESPONSES,
)
def accept(
    principal: Decider,
    store: Store,
    background: BackgroundTasks,
    rec_id: int,
    request: AcceptRequest,
) -> RecommendationDetail:
    """Accept and generate the linked action (never a second one)."""
    actor = actor_of(principal)
    assigns = any(
        value is not None
        for value in (
            request.department_id,
            request.owner_name,
            request.owner_user_id,
            request.due_date,
            request.task,
        )
    )
    if assigns and not principal.has(P.PSM_MANAGE_ACTIONS):
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "permission_denied",
            "Assigning the action needs permission to manage actions. "
            "Accept without assignment instead.",
        )
    detail = _rec_write(
        principal, store, rec_id, lambda: service.accept(store, rec_id, request, actor, _base_url())
    )
    _deliver_later(background)
    return detail


@router.post(
    "/recommendations/{rec_id}/reject",
    response_model=RecommendationDetail,
    responses=WRITE_RESPONSES,
)
def reject(
    principal: Decider, store: Store, rec_id: int, request: RejectRequest
) -> RecommendationDetail:
    actor = actor_of(principal)
    return _rec_write(
        principal, store, rec_id, lambda: service.reject(store, rec_id, request, actor)
    )


@router.post(
    "/recommendations/{rec_id}/return-to-pending",
    response_model=RecommendationDetail,
    responses=WRITE_RESPONSES,
)
def return_to_pending(
    principal: Decider, store: Store, rec_id: int, request: ReasonRequest
) -> RecommendationDetail:
    actor = actor_of(principal)
    return _rec_write(
        principal, store, rec_id, lambda: service.return_to_pending(store, rec_id, request, actor)
    )


@router.post(
    "/recommendations/{rec_id}/archive",
    response_model=RecommendationDetail,
    responses=WRITE_RESPONSES,
)
def archive(
    principal: Editor, store: Store, rec_id: int, request: ReasonRequest
) -> RecommendationDetail:
    actor = actor_of(principal)
    return _rec_write(
        principal,
        store,
        rec_id,
        lambda: service.archive_recommendation(store, rec_id, request, actor),
    )


@router.post(
    "/recommendations/{rec_id}/restore",
    response_model=RecommendationDetail,
    responses=WRITE_RESPONSES,
)
def restore(
    principal: Editor, store: Store, rec_id: int, request: ReasonRequest
) -> RecommendationDetail:
    actor = actor_of(principal)
    return _rec_write(
        principal,
        store,
        rec_id,
        lambda: service.restore_recommendation(store, rec_id, request, actor),
    )


# Actions ------------------------------------------------------------------------------------


def action_filters(
    tab: Annotated[str, Query(max_length=30)] = "all",
    study_id: Annotated[int | None, Query(alias="studyId")] = None,
    q: Text = None,
    department: Codes = None,
    owner: Codes = None,
    risk: Codes = None,
    due_state: Annotated[list[str] | None, Query(alias="dueState", max_length=30)] = None,
    aging: Annotated[str | None, Query(max_length=20)] = None,
    archived: bool = False,
    sort: Annotated[str, Query(max_length=40)] = "dueDate",
    desc: bool = False,
) -> ActionFilters:
    try:
        return ActionFilters(
            tab=tab,  # type: ignore[arg-type]
            study_id=study_id,
            search=(q or "").strip() or None,
            department=department or [],
            owner=owner or [],
            risk=risk or [],
            due_state=due_state or [],
            aging=aging,  # type: ignore[arg-type]
            archived=archived,
            sort=sort,
            desc=desc,
        )
    except ValidationError:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_filter",
            "Unknown action view or filter.",
        ) from None


@router.get("/actions", response_model=ActionPage, responses=RESPONSES)
def list_actions(
    principal: Viewer,
    store: Store,
    filters: Annotated[ActionFilters, Depends(action_filters)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=MAX_PAGE)] = 25,
) -> ActionPage:
    try:
        rows, counts = service.action_list(
            store, action_filter(filters), _today(), sort=filters.sort, descending=filters.desc
        )
    except SQLAlchemyError:
        raise _unavailable() from None
    start = (page - 1) * page_size
    return ActionPage(
        rows=rows[start : start + page_size],
        total=len(rows),
        page=page,
        page_size=page_size,
        tab_counts=counts,
    )


def _action_detail(store: PsmStore, principal: UserPrincipal, action_id: int) -> ActionDetail:
    action = store.get(PsmAction, action_id)
    if action is None:
        raise _error(status.HTTP_404_NOT_FOUND, "record_not_found", "No such action.")
    scope = store.scope(recommendation_ids=[action.recommendation_id], include_archived=True)
    view = service.views(scope)[0]
    return ActionDetail(
        action=service.action_out(view, _today()),
        updates=[service.update_out(u) for u in store.updates(action.id)],
        attachments=[service.attachment_out(a) for a in store.attachments(action_id=action.id)],
        notifications=[service.notification_out(n) for n in store.notifications(action.id)],
        mail_enabled=get_settings().mail_enabled,
        abilities=abilities(principal),
    )


@router.get("/actions/{action_id}", response_model=ActionDetail, responses=RESPONSES)
def get_action(principal: Viewer, store: Store, action_id: int) -> ActionDetail:
    try:
        return _action_detail(store, principal, action_id)
    except SQLAlchemyError:
        raise _unavailable() from None


def _action_write(
    principal: UserPrincipal,
    store: PsmStore,
    action_id: int,
    run: Any,
    background: BackgroundTasks | None,
) -> ActionDetail:
    try:
        run()
        detail = _action_detail(store, principal, action_id)
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    if background is not None:
        _deliver_later(background)
    return detail


@router.put("/actions/{action_id}", response_model=ActionDetail, responses=WRITE_RESPONSES)
def update_action(
    principal: ActionManager,
    store: Store,
    background: BackgroundTasks,
    action_id: int,
    request: ActionUpdate,
) -> ActionDetail:
    """Title, task, department, owner and due date. The status never changes here."""
    actor = actor_of(principal)
    return _action_write(
        principal,
        store,
        action_id,
        lambda: service.update_action(store, action_id, request, actor, _base_url()),
        background,
    )


@router.post("/actions/{action_id}/status", response_model=ActionDetail, responses=WRITE_RESPONSES)
def change_status(
    principal: ActionWorker,
    store: Store,
    background: BackgroundTasks,
    action_id: int,
    request: StatusChange,
) -> ActionDetail:
    actor = actor_of(principal)
    return _action_write(
        principal,
        store,
        action_id,
        lambda: service.change_status(store, action_id, request, actor, _base_url()),
        background,
    )


@router.post(
    "/actions/{action_id}/closure-request", response_model=ActionDetail, responses=WRITE_RESPONSES
)
def request_closure(
    principal: ClosureRequester,
    store: Store,
    background: BackgroundTasks,
    action_id: int,
    request: ClosureRequest,
) -> ActionDetail:
    actor = actor_of(principal)
    return _action_write(
        principal,
        store,
        action_id,
        lambda: service.request_closure(store, action_id, request, actor, _base_url()),
        background,
    )


@router.post(
    "/actions/{action_id}/closure-approval", response_model=ActionDetail, responses=WRITE_RESPONSES
)
def approve_closure(
    principal: Verifier,
    store: Store,
    background: BackgroundTasks,
    action_id: int,
    request: VerificationApprove,
) -> ActionDetail:
    actor = actor_of(principal)
    return _action_write(
        principal,
        store,
        action_id,
        lambda: service.approve_closure(store, action_id, request, actor, _base_url()),
        background,
    )


@router.post(
    "/actions/{action_id}/closure-return", response_model=ActionDetail, responses=WRITE_RESPONSES
)
def return_closure(
    principal: Verifier,
    store: Store,
    background: BackgroundTasks,
    action_id: int,
    request: ReasonRequest,
) -> ActionDetail:
    actor = actor_of(principal)
    return _action_write(
        principal,
        store,
        action_id,
        lambda: service.return_closure(store, action_id, request, actor, _base_url()),
        background,
    )


@router.post("/actions/{action_id}/reopen", response_model=ActionDetail, responses=WRITE_RESPONSES)
def reopen(
    principal: Reopener,
    store: Store,
    background: BackgroundTasks,
    action_id: int,
    request: ReasonRequest,
) -> ActionDetail:
    actor = actor_of(principal)
    return _action_write(
        principal,
        store,
        action_id,
        lambda: service.reopen(store, action_id, request, actor, _base_url()),
        background,
    )


@router.post(
    "/actions/{action_id}/comments", response_model=ActionDetail, responses=WRITE_RESPONSES
)
def comment(
    principal: ActionWorker,
    store: Store,
    background: BackgroundTasks,
    action_id: int,
    request: CommentRequest,
) -> ActionDetail:
    actor = actor_of(principal)
    return _action_write(
        principal,
        store,
        action_id,
        lambda: service.comment(store, action_id, request, actor, _base_url()),
        background,
    )


@router.post(
    "/actions/{action_id}/resolution", response_model=ActionDetail, responses=WRITE_RESPONSES
)
def resolve(
    principal: Admin, store: Store, action_id: int, request: ResolutionRequest
) -> ActionDetail:
    actor = actor_of(principal)
    return _action_write(
        principal, store, action_id, lambda: service.resolve(store, action_id, request, actor), None
    )


# Evidence ---------------------------------------------------------------------------------------


async def _read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise _error(413, "file_too_large", "Files are limited to 10 MB.")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise _error(413, "file_too_large", "Files are limited to 10 MB.")
        chunks.append(chunk)
    return b"".join(chunks)


FileName = Annotated[str, Query(alias="fileName", min_length=1, max_length=255)]
EvidenceTypeQuery = Annotated[str, Query(alias="evidenceType", max_length=40)]
DescriptionQuery = Annotated[str | None, Query(max_length=1000)]


@router.post(
    "/recommendations/{rec_id}/attachments",
    response_model=RecommendationDetail,
    status_code=201,
    responses={**WRITE_RESPONSES, 413: {"description": "File too large"}},
)
async def add_recommendation_evidence(
    principal: EvidenceWriter,
    store: Store,
    request: Request,
    rec_id: int,
    file_name: FileName,
    evidence_type: EvidenceTypeQuery,
    description: DescriptionQuery = None,
) -> RecommendationDetail:
    """Upload one file as the raw request body (at most 10 MB)."""
    content = await _read_body(request, MAX_ATTACHMENT_BYTES)
    upload = service.Upload(file_name, evidence_type, description, content)
    actor = actor_of(principal)

    def run() -> RecommendationDetail:
        return _rec_write(
            principal,
            store,
            rec_id,
            lambda: service.add_attachment(store, upload, actor, recommendation_id=rec_id),
        )

    return await run_in_threadpool(run)


@router.post(
    "/actions/{action_id}/attachments",
    response_model=ActionDetail,
    status_code=201,
    responses={**WRITE_RESPONSES, 413: {"description": "File too large"}},
)
async def add_action_evidence(
    principal: ActionWorker,
    store: Store,
    request: Request,
    action_id: int,
    file_name: FileName,
    evidence_type: EvidenceTypeQuery,
    description: DescriptionQuery = None,
) -> ActionDetail:
    content = await _read_body(request, MAX_ATTACHMENT_BYTES)
    upload = service.Upload(file_name, evidence_type, description, content)
    actor = actor_of(principal)

    def run() -> ActionDetail:
        return _action_write(
            principal,
            store,
            action_id,
            lambda: service.add_attachment(store, upload, actor, action_id=action_id),
            None,
        )

    return await run_in_threadpool(run)


@router.get("/attachments/{attachment_id}/content", responses=RESPONSES)
def download_evidence(principal: Viewer, store: Store, attachment_id: int) -> Response:
    try:
        row = store.get(PsmAttachment, attachment_id)
        content = store.get(PsmAttachmentContent, attachment_id) if row else None
    except SQLAlchemyError:
        raise _unavailable() from None
    if row is None or content is None or row.removed_at is not None:
        raise _error(status.HTTP_404_NOT_FOUND, "record_not_found", "No such evidence file.")
    ascii_name = row.original_file_name.encode("ascii", "replace").decode().replace('"', "'")
    return Response(
        content=content.content,
        media_type=row.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_name}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/attachments/{attachment_id}/removal", status_code=204, responses=WRITE_RESPONSES)
def remove_evidence(
    principal: EvidenceWriter, store: Store, attachment_id: int, request: CommentRequest
) -> Response:
    """Remove evidence from view, with a reason. The file and its record are kept."""
    try:
        service.remove_attachment(store, attachment_id, request.body, actor_of(principal))
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return Response(status_code=204)


# Reference data and settings -------------------------------------------------------------------


@router.post(
    "/reference/process-nodes", response_model=Option, status_code=201, responses=WRITE_RESPONSES
)
def add_node(principal: NodeEditor, store: Store, request: ReferenceWrite) -> Option:
    try:
        row_id = service.save_reference(store, PsmProcessNode, request, actor_of(principal))
        row = store.get(PsmProcessNode, row_id)
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return Option(id=row.id, name=row.name, active=row.active)


@router.put("/reference/process-nodes/{row_id}", response_model=Option, responses=WRITE_RESPONSES)
def update_node(principal: Admin, store: Store, row_id: int, request: ReferenceWrite) -> Option:
    try:
        service.save_reference(store, PsmProcessNode, request, actor_of(principal), row_id)
        row = store.get(PsmProcessNode, row_id)
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return Option(id=row.id, name=row.name, active=row.active)


@router.post(
    "/reference/departments", response_model=Option, status_code=201, responses=WRITE_RESPONSES
)
def add_department(principal: Admin, store: Store, request: ReferenceWrite) -> Option:
    try:
        row_id = service.save_reference(store, PsmDepartment, request, actor_of(principal))
        row = store.get(PsmDepartment, row_id)
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return Option(id=row.id, name=row.name, active=row.active)


@router.put("/reference/departments/{row_id}", response_model=Option, responses=WRITE_RESPONSES)
def update_department(
    principal: Admin, store: Store, row_id: int, request: ReferenceWrite
) -> Option:
    try:
        service.save_reference(store, PsmDepartment, request, actor_of(principal), row_id)
        row = store.get(PsmDepartment, row_id)
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return Option(id=row.id, name=row.name, active=row.active)


@router.get("/notification-settings", response_model=NotificationSettingsWrite, responses=RESPONSES)
def get_notification_settings(principal: Viewer, store: Store) -> NotificationSettingsWrite:
    try:
        row = notifications.settings_row(store.session)
    except SQLAlchemyError:
        raise _unavailable() from None
    if row is None:
        raise _error(status.HTTP_404_NOT_FOUND, "record_not_found", "Settings are not set up.")
    return NotificationSettingsWrite.model_validate(row, from_attributes=True)


@router.put(
    "/notification-settings", response_model=NotificationSettingsWrite, responses=WRITE_RESPONSES
)
def save_notification_settings(
    principal: Admin, store: Store, request: NotificationSettingsWrite
) -> NotificationSettingsWrite:
    try:
        service.save_notification_settings(store, request, actor_of(principal))
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return request


@router.post("/notifications/deliver", responses=WRITE_RESPONSES)
def deliver_queued(principal: Admin) -> dict[str, Any]:
    """Try to send queued notifications now. Reports what the mail server accepted."""
    settings = get_settings()
    if not settings.mail_enabled:
        return {"mailEnabled": False, "sent": 0, "failed": 0, "queued": 0}
    try:
        counts = notifications.deliver(get_sessionmaker(), settings)
    except SQLAlchemyError:
        raise _unavailable() from None
    return {"mailEnabled": True, **counts}


# Import --------------------------------------------------------------------------------


async def _workbook(request: Request, file_name: str) -> pha_import.PhaMapping:
    if not file_name.lower().endswith(".xlsx"):
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "file_type",
            "Upload the workbook as an .xlsx file.",
        )
    content = await _read_body(request, MAX_ATTACHMENT_BYTES)
    try:
        return await run_in_threadpool(pha_import.extract, content, file_name)
    except pha_import.ImportValidationError as error:
        raise _write_error(error) from None
    except Exception:  # noqa: BLE001 - an unreadable file is reported, not raised
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "unreadable_workbook",
            "The file could not be read as an Excel workbook. Nothing was imported.",
        ) from None


def _import_summary(mapping: pha_import.PhaMapping, plan: pha_import.Plan) -> dict[str, Any]:
    scenarios = [s for r in mapping.recommendations for s in r.scenarios]
    return {
        "source": mapping.source.model_dump(by_alias=True),
        "study": mapping.study.model_dump(by_alias=True),
        "recommendations": len(mapping.recommendations),
        "scenarios": len(scenarios),
        "risks": {risk: sum(s.risk == risk for s in scenarios) for risk in RISKS},
        "trimmedValues": mapping.trimmed_values,
        "plan": plan.summary(),
    }


@router.post("/imports/pha/plan", responses={**WRITE_RESPONSES, 413: {"description": "Too large"}})
async def plan_import(
    principal: Importer, store: Store, request: Request, file_name: FileName
) -> dict[str, Any]:
    """Validate the workbook and compare it with stored data. Writes nothing."""
    mapping = await _workbook(request, file_name)

    def run() -> dict[str, Any]:
        try:
            plan = pha_import.plan(store, mapping)
            store.rollback()
            return _import_summary(mapping, plan)
        except SQLAlchemyError:
            raise _unavailable() from None

    return await run_in_threadpool(run)


@router.post("/imports/pha/apply", responses={**WRITE_RESPONSES, 413: {"description": "Too large"}})
async def apply_import(
    principal: Importer, store: Store, request: Request, file_name: FileName
) -> dict[str, Any]:
    """Validate and import, all or nothing. Stored records are never overwritten."""
    mapping = await _workbook(request, file_name)
    actor = actor_of(principal)

    def run() -> dict[str, Any]:
        try:
            result = pha_import.apply(store, mapping, actor)
        except _WRITE_ERRORS as error:
            raise _write_error(error) from None
        return {
            **_import_summary(mapping, result.plan),
            "studyId": result.study_id,
            "created": {
                "recommendations": result.recommendations,
                "scenarios": result.scenarios,
                "processNodes": result.nodes,
            },
        }

    return await run_in_threadpool(run)
