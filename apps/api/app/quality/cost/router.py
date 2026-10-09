"""Cost of Quality endpoints.

Reading needs ``qualityCost.view`` (the COPQ / COQ figures also
``qualityDashboard.view``); adding records ``qualityCost.create`` and editing
them ``qualityCost.edit``. Within an edit, changing the owner also needs
``qualityCost.assign``, confirming a cost ``qualityCost.confirmFinancial`` and
closing or reopening ``qualityCost.close`` (``records.check_permissions``).

``/records`` is the Quality Cost Register. ``/summary`` returns the COPQ and
COQ Matrix figures calculated from the same records, with the same filters.
``/estimator`` and ``/estimate`` are the incident cost estimator, which stores
nothing.
"""

import calendar
import datetime as dt
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from app.auth import people
from app.core.authorization import UserPrincipal, require_all_permissions, require_permission
from app.core.permissions import Permission
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.quality.cost import estimator, records, service
from app.quality.cost.classification import (
    CATEGORIES,
    CONFIRMED_FINANCIAL,
    COQ_CLASSES,
    COST_COMPONENTS,
    FINANCIAL_STATUSES,
    OPERATIONAL_STATUSES,
    POOR_CLASSES,
    REFERENCE_TYPES,
    CoqClass,
    FinancialStatus,
    OperationalStatus,
    quality_group,
)
from app.quality.cost.models import MAX_REPORTING_YEAR, MIN_REPORTING_YEAR
from app.quality.cost.repository import CostRepository, RecordFilter
from app.quality.cost.schemas import (
    CodeLabelOut,
    CoqClassOptionOut,
    CostAbilitiesOut,
    CostComponentOut,
    CostRecordCreate,
    CostRecordListResponse,
    CostRecordOptionsResponse,
    CostRecordResponse,
    CostRecordUpdate,
    CostSummaryResponse,
    EstimateRequest,
    EstimateResponse,
    EstimatorReferenceResponse,
    FinancialStatusOut,
    HistoryEventOut,
    HistoryResponse,
    OptionOut,
)
from app.safety.site_calendar import site_today

router = APIRouter(prefix="/quality/cost", tags=["quality"])

MAX_PAGE = 500


def _error(status_code: int, error: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error": error, "message": message, **extra}
    )


def _database_unavailable() -> HTTPException:
    return _error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "database_unavailable",
        "Cost of Quality data is unavailable because the database could not be reached.",
    )


def cost_repository() -> Iterator[CostRepository]:
    try:
        sessions = get_sessionmaker()
    except DatabaseNotConfiguredError:
        raise _database_unavailable() from None
    with sessions() as session:
        yield CostRepository(session)


Repository = Annotated[CostRepository, Depends(cost_repository)]
Viewer = Annotated[UserPrincipal, Depends(require_permission(Permission.QUALITY_COST_VIEW))]
DashboardViewer = Annotated[
    UserPrincipal,
    Depends(
        require_all_permissions(Permission.QUALITY_COST_VIEW, Permission.QUALITY_DASHBOARD_VIEW)
    ),
]
Creator = Annotated[UserPrincipal, Depends(require_permission(Permission.QUALITY_COST_CREATE))]
Editor = Annotated[UserPrincipal, Depends(require_permission(Permission.QUALITY_COST_EDIT))]
Year = Annotated[int | None, Query(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)]
Month = Annotated[int | None, Query(ge=1, le=12)]
Text = Annotated[str | None, Query(max_length=200)]

RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not signed in"},
    403: {"description": "Missing permission"},
}
READ_RESPONSES: dict[int | str, dict[str, Any]] = {
    **RESPONSES,
    503: {"description": "Database unavailable"},
}
WRITE_RESPONSES: dict[int | str, dict[str, Any]] = {
    **RESPONSES,
    404: {"description": "No such record"},
    409: {"description": "The record changed since it was loaded; nothing saved"},
    422: {"description": "Invalid request; nothing saved"},
    503: {"description": "Database unavailable; nothing saved"},
}


def _today() -> dt.date:
    return site_today(dt.datetime.now(dt.UTC))


def _can_edit(principal: UserPrincipal) -> bool:
    return principal.has(Permission.QUALITY_COST_EDIT)


def _abilities(principal: UserPrincipal) -> CostAbilitiesOut:
    return CostAbilitiesOut(
        create=principal.has(Permission.QUALITY_COST_CREATE),
        edit=principal.has(Permission.QUALITY_COST_EDIT),
        assign=principal.has(Permission.QUALITY_COST_ASSIGN),
        confirm_financial=principal.has(Permission.QUALITY_COST_CONFIRM_FINANCIAL),
        close=principal.has(Permission.QUALITY_COST_CLOSE),
    )


def actor_of(principal: UserPrincipal) -> records.Actor:
    """The acting user, from the session (never from the request body)."""
    return records.Actor(
        principal.actor_id,
        dt.datetime.now(dt.UTC),
        permissions=principal.granted,
        user_id=principal.user_id,
        name=principal.name,
    )


def _record_response(
    principal: UserPrincipal, repository: CostRepository, row: Any
) -> CostRecordResponse:
    names = repository.actor_names(records.actor_ids([row]))
    return CostRecordResponse(
        record=records.record_out(row, _today(), names),
        can_edit=_can_edit(principal),
        abilities=_abilities(principal),
    )


def _write_error(error: Exception) -> HTTPException:
    if isinstance(error, records.RecordNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "record_not_found", "No such record.")
    if isinstance(error, records.RecordForbiddenError):
        return _error(status.HTTP_403_FORBIDDEN, "permission_denied", error.message)
    if isinstance(error, records.RecordConflictError):
        return _error(
            status.HTTP_409_CONFLICT,
            "edit_conflict",
            "This record was changed by someone else since you loaded it. Nothing was saved.",
            current=records.record_out(error.current, _today()).model_dump(
                mode="json", by_alias=True
            ),
        )
    if isinstance(error, records.RecordRuleError):
        return _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, error.error, error.message, field=error.field
        )
    return _database_unavailable()


_WRITE_ERRORS = (
    records.RecordNotFoundError,
    records.RecordConflictError,
    records.RecordRuleError,
    records.RecordForbiddenError,
    SQLAlchemyError,
)


def _filter(
    *,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    area_id: int | None,
    coq_class: list[CoqClass] | None,
    category: str | None,
    product: str | None,
    owner: str | None,
    financial_status: list[FinancialStatus] | None,
    record_status: list[OperationalStatus] | None = None,
    search: str | None = None,
) -> RecordFilter:
    text = search.strip() if search else None
    return RecordFilter(
        date_from=date_from,
        date_to=date_to,
        area_id=area_id,
        coq_classes=tuple(coq_class or ()),
        category_code=category or None,
        product=(product or "").strip() or None,
        owner=(owner or "").strip() or None,
        financial_statuses=tuple(financial_status or ()),
        statuses=tuple(record_status or ()),
        search=text or None,
        search_id=records.parse_record_number(text) if text else None,
    )


# Shared filter parameters of the Register and the dashboards.
AreaId = Annotated[int | None, Query(alias="areaId", ge=1)]
ClassFilter = Annotated[list[CoqClass] | None, Query(alias="coqClass")]
CategoryFilter = Annotated[str | None, Query(max_length=100)]
FinancialFilter = Annotated[list[FinancialStatus] | None, Query(alias="financialStatus")]


@router.get("/records", response_model=CostRecordListResponse, responses=READ_RESPONSES)
def list_records(
    principal: Viewer,
    repository: Repository,
    date_from: Annotated[dt.date | None, Query(alias="from")] = None,
    date_to: Annotated[dt.date | None, Query(alias="to")] = None,
    area_id: AreaId = None,
    coq_class: ClassFilter = None,
    category: CategoryFilter = None,
    product: Text = None,
    owner: Text = None,
    financial_status: FinancialFilter = None,
    record_status: Annotated[list[OperationalStatus] | None, Query(alias="status")] = None,
    open_only: Annotated[bool, Query(alias="open")] = False,
    search: Text = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = MAX_PAGE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CostRecordListResponse:
    """Quality Cost records, newest first. ``search`` matches the record number,
    title, description, product, campaign, lot, owner, customer / supplier and notes.
    ``open`` keeps records whose status is not Closed."""
    statuses = record_status or (
        [s for s in OPERATIONAL_STATUSES if s != "closed"] if open_only else None
    )
    criteria = _filter(
        date_from=date_from,
        date_to=date_to,
        area_id=area_id,
        coq_class=coq_class,
        category=category,
        product=product,
        owner=owner,
        financial_status=financial_status,
        record_status=statuses,  # type: ignore[arg-type]
        search=search,
    )
    try:
        rows, total = repository.search(criteria, limit=limit, offset=offset)
        names = repository.actor_names(records.actor_ids(rows))
    except SQLAlchemyError:
        raise _database_unavailable() from None
    today = _today()
    return CostRecordListResponse(
        records=[records.record_out(r, today, names) for r in rows],
        total=total,
        can_edit=_can_edit(principal),
        abilities=_abilities(principal),
    )


@router.get("/records/options", response_model=CostRecordOptionsResponse, responses=READ_RESPONSES)
def record_options(principal: Viewer, repository: Repository) -> CostRecordOptionsResponse:
    """Everything the entry form and filters choose from: areas (inactive ones
    flagged), classes with their categories, statuses, cost components and the
    products and owners already used on records."""
    try:
        areas = repository.areas()
        products = repository.distinct_values("product")
        owners = repository.distinct_values("owner")
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return CostRecordOptionsResponse(
        areas=[OptionOut(id=a.id, code=a.code, name=a.name, active=a.active) for a in areas],
        classes=[
            CoqClassOptionOut(
                code=code,
                label=label,
                quality_group=quality_group(code),
                categories=[
                    CodeLabelOut(code=c.code, label=c.label)
                    for c in CATEGORIES
                    if c.coq_class == code
                ],
            )
            for code, label in COQ_CLASSES.items()
        ],
        financial_statuses=[
            FinancialStatusOut(code=code, label=label, confirmed=code in CONFIRMED_FINANCIAL)
            for code, label in FINANCIAL_STATUSES.items()
        ],
        operational_statuses=[
            CodeLabelOut(code=code, label=label) for code, label in OPERATIONAL_STATUSES.items()
        ],
        cost_components=[
            CostComponentOut(field=_camel(field), label=label) for field, label in COST_COMPONENTS
        ],
        reference_types=[CodeLabelOut(code=c, label=label) for c, label in REFERENCE_TYPES.items()],
        products=products,
        owners=owners,
        can_edit=_can_edit(principal),
        abilities=_abilities(principal),
    )


def _camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.title() for part in rest)


@router.get("/records/{record_id}", response_model=CostRecordResponse, responses=READ_RESPONSES)
def get_record(principal: Viewer, repository: Repository, record_id: int) -> CostRecordResponse:
    try:
        row = repository.get(record_id)
        if row is None:
            raise _error(status.HTTP_404_NOT_FOUND, "record_not_found", "No such record.")
        return _record_response(principal, repository, row)
    except SQLAlchemyError:
        raise _database_unavailable() from None


@router.get(
    "/records/{record_id}/history", response_model=HistoryResponse, responses=READ_RESPONSES
)
def record_history(principal: Viewer, repository: Repository, record_id: int) -> HistoryResponse:
    """The record's audit trail, oldest first."""
    try:
        if repository.get(record_id) is None:
            raise _error(status.HTTP_404_NOT_FOUND, "record_not_found", "No such record.")
        events = repository.history(records.ENTITY_TYPE, records.entity_key(record_id))
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return HistoryResponse(
        record_id=record_id,
        events=[
            HistoryEventOut(
                occurred_at=e.occurred_at,
                actor_id=e.actor_id,
                actor_name=e.actor_name or people.actor_label(e.actor_id, {}),
                action=e.action,  # type: ignore[arg-type]
                change_set_id=str(e.change_set_id),
                old_value=records.public_audit_value(e.old_value),
                new_value=records.public_audit_value(e.new_value),
            )
            for e in events
        ],
    )


@router.post(
    "/records",
    response_model=CostRecordResponse,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_RESPONSES,
)
def create_record(
    principal: Creator, repository: Repository, request: CostRecordCreate
) -> CostRecordResponse:
    try:
        row = records.create(repository, request, actor_of(principal))
        return _record_response(principal, repository, row)
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None


@router.put("/records/{record_id}", response_model=CostRecordResponse, responses=WRITE_RESPONSES)
def update_record(
    principal: Editor, repository: Repository, record_id: int, request: CostRecordUpdate
) -> CostRecordResponse:
    try:
        row = records.update(repository, record_id, request, actor_of(principal))
        return _record_response(principal, repository, row)
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None


@router.get("/summary", response_model=CostSummaryResponse, responses=READ_RESPONSES)
def summary(
    principal: DashboardViewer,
    repository: Repository,
    year: Year = None,
    from_month: Annotated[int | None, Query(alias="from", ge=1, le=12)] = None,
    through: Month = None,
    area_id: AreaId = None,
    coq_class: ClassFilter = None,
    category: CategoryFilter = None,
    product: Text = None,
    owner: Text = None,
    financial_status: FinancialFilter = None,
    poor_only: Annotated[bool, Query(alias="poorOnly")] = False,
) -> CostSummaryResponse:
    """COPQ and COQ Matrix figures of the records of ``year`` (default: the latest
    year with records), ``from`` (default January) through ``through`` (default the
    latest month with a record), narrowed by the same filters as ``/records``.
    ``poorOnly`` keeps Internal and External Failure records (the COPQ view)."""
    classes = coq_class
    if poor_only:
        classes = [c for c in coq_class if c in POOR_CLASSES] if coq_class else sorted(POOR_CLASSES)
    try:
        years = repository.record_years()
        selected = year if year is not None else (years[0] if years else None)
        rows: list[Any] = []
        # An empty class list here means a filter that excludes every record.
        if selected is not None and (classes is None or classes):
            criteria = _filter(
                date_from=dt.date(selected, 1, 1),
                date_to=dt.date(selected, 12, calendar.monthrange(selected, 12)[1]),
                area_id=area_id,
                coq_class=classes,  # type: ignore[arg-type]
                category=category,
                product=product,
                owner=owner,
                financial_status=financial_status,
            )
            rows, _ = repository.search(criteria)
        stored = [service.MonthInputs.from_row(r) for r in repository.facts().values()]
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return service.summary(
        [row.record for row in rows],
        stored,
        year=selected,
        available_years=years,
        from_month=from_month,
        through_month=through,
        today=_today(),
    )


@router.get("/estimator", response_model=EstimatorReferenceResponse, responses=RESPONSES)
def estimator_reference(principal: Viewer) -> EstimatorReferenceResponse:
    """Products, package types and the workbook's assumptions used by ``/estimate``."""
    return estimator.reference_response()


@router.post(
    "/estimate",
    response_model=EstimateResponse,
    responses={**RESPONSES, 422: {"description": "Invalid or incomplete inputs"}},
)
def estimate(principal: Viewer, request: EstimateRequest) -> EstimateResponse:
    """Estimate one incident's cost of poor quality. Nothing is stored."""
    try:
        return estimator.estimate(request)
    except estimator.EstimateError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "invalid_estimate", "message": str(error)},
        ) from None
