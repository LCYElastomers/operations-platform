"""Corrective Action Report endpoints.

Reading needs ``quality.cars.view``; creating and editing reports, their
actions and their Quality Cost link ``quality.cars.edit``. Creating a Quality
Cost record from a report also needs ``quality.cost.edit``; linking an existing
one needs ``quality.cost.view``.

``/cars`` is the CAR Register; ``/cars/dashboard`` returns the dashboard figures
of the same reports with the same filters.
"""

import datetime as dt
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from app.core.authorization import UserPrincipal, require_permission
from app.core.config import get_settings
from app.core.permissions import Permission
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.quality.car import dashboard, service
from app.quality.car.reference import (
    ACTION_STATUSES,
    APPROVAL_FUNCTIONS,
    CAR_STATUSES,
    DEPARTMENTS,
    DISPOSITIONS,
    EFFECTIVENESS_RESULTS,
    LEGACY_DEPARTMENTS,
    LEGACY_DISPOSITIONS,
    REFERENCE_TYPES,
    ROOT_CAUSE_CATEGORIES,
    SOURCES,
    STEPS,
)
from app.quality.car.repository import CarFilter, CarRepository
from app.quality.car.schemas import (
    ActionComplete,
    ActionCreate,
    ActionUpdate,
    CarCreate,
    CarDashboardResponse,
    CarHistoryEventOut,
    CarHistoryResponse,
    CarLinkOut,
    CarListResponse,
    CarOptionsResponse,
    CarResponse,
    CarUpdate,
    ChoiceOut,
    CodeLabelOut,
    QualityCostCreate,
    QualityCostLink,
)
from app.quality.cost.records import Actor, RecordNotFoundError, RecordRuleError
from app.safety.site_calendar import site_today

router = APIRouter(prefix="/quality/cars", tags=["quality"])

MAX_PAGE = 500


def _error(status_code: int, error: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error": error, "message": message, **extra}
    )


def _database_unavailable() -> HTTPException:
    return _error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "database_unavailable",
        "Corrective Action Report data is unavailable because the database could not be reached.",
    )


def car_repository() -> Iterator[CarRepository]:
    try:
        sessions = get_sessionmaker()
    except DatabaseNotConfiguredError:
        raise _database_unavailable() from None
    with sessions() as session:
        yield CarRepository(session)


Repository = Annotated[CarRepository, Depends(car_repository)]
Viewer = Annotated[UserPrincipal, Depends(require_permission(Permission.QUALITY_CARS_VIEW))]
Editor = Annotated[UserPrincipal, Depends(require_permission(Permission.QUALITY_CARS_EDIT))]
Text = Annotated[str | None, Query(max_length=200)]
Codes = Annotated[list[str] | None, Query(max_length=20)]

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
    404: {"description": "No such report or action"},
    409: {"description": "The report changed since it was loaded; nothing saved"},
    422: {"description": "Invalid request; nothing saved"},
    503: {"description": "Database unavailable; nothing saved"},
}


def _today() -> dt.date:
    return site_today(dt.datetime.now(dt.UTC))


def _due_soon_days() -> int:
    return get_settings().car_due_soon_days


def _can_edit(principal: UserPrincipal) -> bool:
    return principal.has(Permission.QUALITY_CARS_EDIT)


def _can_edit_cost(principal: UserPrincipal) -> bool:
    return _can_edit(principal) and principal.has(Permission.QUALITY_COST_EDIT)


def _actor(principal: UserPrincipal) -> Actor:
    assert principal.user_id is not None  # noqa: S101 - require_permission admits users only
    return Actor(principal.user_id, dt.datetime.now(dt.UTC))


def _write_error(error: Exception) -> HTTPException:
    if isinstance(error, RecordNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "record_not_found", "No such record.")
    if isinstance(error, service.CarConflictError):
        return _error(
            status.HTTP_409_CONFLICT,
            "edit_conflict",
            "This CAR was changed by someone else since you loaded it. Nothing was saved.",
            current=service.car_out(error.current, _today(), _due_soon_days()).model_dump(
                mode="json", by_alias=True
            ),
        )
    if isinstance(error, RecordRuleError):
        return _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, error.error, error.message, field=error.field
        )
    return _database_unavailable()


_WRITE_ERRORS = (RecordNotFoundError, service.CarConflictError, RecordRuleError, SQLAlchemyError)


def _response(principal: UserPrincipal, row: Any) -> CarResponse:
    return CarResponse(
        car=service.car_out(row, _today(), _due_soon_days()),
        can_edit=_can_edit(principal),
        can_edit_cost=_can_edit_cost(principal),
    )


def _clean(values: list[str] | None) -> tuple[str, ...]:
    return tuple(v.strip() for v in values or () if v.strip())


def _filter(
    *,
    date_from: dt.date | None,
    date_to: dt.date | None,
    car_status: list[str] | None = None,
    department: list[str] | None,
    source: list[str] | None,
    root_cause: list[str] | None = None,
    effectiveness: list[str] | None = None,
    assigned_to: str | None,
    past_due: bool = False,
    repeat: bool | None = None,
    search: str | None = None,
) -> CarFilter:
    return CarFilter(
        date_from=date_from,
        date_to=date_to,
        statuses=_clean(car_status),
        departments=_clean(department),
        sources=_clean(source),
        root_causes=_clean(root_cause),
        effectiveness=_clean(effectiveness),
        assigned_to=(assigned_to or "").strip() or None,
        past_due_on=_today() if past_due else None,
        repeat=repeat,
        search=(search or "").strip() or None,
    )


From = Annotated[dt.date | None, Query(alias="from")]
To = Annotated[dt.date | None, Query(alias="to")]
AssignedTo = Annotated[str | None, Query(alias="assignedTo", max_length=200)]


@router.get("", response_model=CarListResponse, responses=READ_RESPONSES)
def list_cars(
    principal: Viewer,
    repository: Repository,
    date_from: From = None,
    date_to: To = None,
    car_status: Annotated[list[str] | None, Query(alias="status", max_length=5)] = None,
    department: Codes = None,
    source: Codes = None,
    root_cause: Annotated[list[str] | None, Query(alias="rootCause", max_length=20)] = None,
    effectiveness: Annotated[list[str] | None, Query(max_length=5)] = None,
    assigned_to: AssignedTo = None,
    past_due: Annotated[bool, Query(alias="pastDue")] = False,
    repeat: bool | None = None,
    search: Text = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = MAX_PAGE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CarListResponse:
    """Reports, newest request first. Status, department, source, root cause and
    effectiveness accept ``not_recorded``. ``search`` matches the CAR number,
    subject, people, description, incident type, root cause, product, lot and
    work order. ``pastDue`` keeps reports not closed whose due date has passed;
    ``repeat`` keeps reports marked (or not marked) as a previous occurrence."""
    criteria = _filter(
        date_from=date_from,
        date_to=date_to,
        car_status=car_status,
        department=department,
        source=source,
        root_cause=root_cause,
        effectiveness=effectiveness,
        assigned_to=assigned_to,
        past_due=past_due,
        repeat=repeat,
        search=search,
    )
    try:
        rows, total = repository.search(criteria, limit=limit, offset=offset)
    except SQLAlchemyError:
        raise _database_unavailable() from None
    today, days = _today(), _due_soon_days()
    return CarListResponse(
        cars=[service.list_item_out(r, today, days) for r in rows],
        total=total,
        can_edit=_can_edit(principal),
    )


def _choices(active: dict[str, str], legacy: dict[str, str] | None = None) -> list[ChoiceOut]:
    return [ChoiceOut(code=c, label=label, active=True) for c, label in active.items()] + [
        ChoiceOut(code=c, label=label, active=False) for c, label in (legacy or {}).items()
    ]


def _code_labels(values: dict[str, str] | tuple[tuple[str, str], ...]) -> list[CodeLabelOut]:
    items = values.items() if isinstance(values, dict) else values
    return [CodeLabelOut(code=c, label=label) for c, label in items]


@router.get("/options", response_model=CarOptionsResponse, responses=READ_RESPONSES)
def options(principal: Viewer, repository: Repository) -> CarOptionsResponse:
    """The controlled lists of the CAR form (older-form values flagged inactive)
    and the names already used on reports."""
    try:
        people, assignees = repository.people()
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return CarOptionsResponse(
        sources=_choices(SOURCES),
        departments=_choices(DEPARTMENTS, LEGACY_DEPARTMENTS),
        root_causes=_choices(ROOT_CAUSE_CATEGORIES),
        dispositions=_choices(DISPOSITIONS, LEGACY_DISPOSITIONS),
        action_statuses=_code_labels(ACTION_STATUSES),
        effectiveness_results=_code_labels(EFFECTIVENESS_RESULTS),
        car_statuses=_code_labels(CAR_STATUSES),
        approval_functions=_code_labels(APPROVAL_FUNCTIONS),
        reference_types=_code_labels(REFERENCE_TYPES),
        steps=_code_labels(STEPS),
        people=people,
        assignees=assignees,
        due_soon_days=_due_soon_days(),
        can_edit=_can_edit(principal),
        can_edit_cost=_can_edit_cost(principal),
    )


@router.get("/dashboard", response_model=CarDashboardResponse, responses=READ_RESPONSES)
def car_dashboard(
    principal: Viewer,
    repository: Repository,
    date_from: From = None,
    date_to: To = None,
    department: Codes = None,
    source: Codes = None,
    assigned_to: AssignedTo = None,
) -> CarDashboardResponse:
    """Dashboard figures of the reports requested in the date range (default: all)."""
    criteria = _filter(
        date_from=date_from,
        date_to=date_to,
        department=department,
        source=source,
        assigned_to=assigned_to,
    )
    try:
        rows, _ = repository.search(criteria)
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return dashboard.summary(rows, today=_today(), due_soon_days=_due_soon_days())


@router.get("/linked", response_model=list[CarLinkOut], responses=READ_RESPONSES)
def linked_cars(
    principal: Viewer,
    repository: Repository,
    cost_record_id: Annotated[int, Query(alias="costRecordId", ge=1)],
) -> list[CarLinkOut]:
    """The report linked to a Quality Cost record, if any."""
    try:
        car = repository.car_for_cost_record(cost_record_id)
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return (
        []
        if car is None
        else [CarLinkOut(id=car.id, car_number=car.car_number, subject=car.subject)]
    )


@router.get("/{car_id}", response_model=CarResponse, responses=READ_RESPONSES)
def get_car(principal: Viewer, repository: Repository, car_id: int) -> CarResponse:
    try:
        row = repository.get(car_id)
    except SQLAlchemyError:
        raise _database_unavailable() from None
    if row is None:
        raise _error(status.HTTP_404_NOT_FOUND, "record_not_found", "No such CAR.")
    return _response(principal, row)


@router.get("/{car_id}/history", response_model=CarHistoryResponse, responses=READ_RESPONSES)
def car_history(principal: Viewer, repository: Repository, car_id: int) -> CarHistoryResponse:
    """The report's audit trail and its actions', oldest first."""
    try:
        if repository.get(car_id) is None:
            raise _error(status.HTTP_404_NOT_FOUND, "record_not_found", "No such CAR.")
        events = repository.history(
            (service.ENTITY_TYPE, service.ACTION_ENTITY_TYPE), service.entity_key(car_id)
        )
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return CarHistoryResponse(
        car_id=car_id,
        events=[
            CarHistoryEventOut(
                occurred_at=e.occurred_at,
                actor_id=e.actor_id,
                action=e.action,  # type: ignore[arg-type]
                change_set_id=str(e.change_set_id),
                old_value=service.public_audit_value(e.old_value),
                new_value=service.public_audit_value(e.new_value),
                entity="action" if e.entity_type == service.ACTION_ENTITY_TYPE else "car",
                action_id=(
                    int(e.entity_key.rsplit("/", 1)[1])
                    if e.entity_type == service.ACTION_ENTITY_TYPE
                    else None
                ),
            )
            for e in events
        ],
    )


@router.post(
    "", response_model=CarResponse, status_code=status.HTTP_201_CREATED, responses=WRITE_RESPONSES
)
def create_car(principal: Editor, repository: Repository, request: CarCreate) -> CarResponse:
    """A new report. Only the subject and request date are required; the rest
    can be completed later. The CAR number is assigned from the request year."""
    try:
        row = service.create(repository, request, _actor(principal))
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return _response(principal, row)


@router.put("/{car_id}", response_model=CarResponse, responses=WRITE_RESPONSES)
def update_car(
    principal: Editor, repository: Repository, car_id: int, request: CarUpdate
) -> CarResponse:
    try:
        row = service.update(repository, car_id, request, _actor(principal))
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return _response(principal, row)


@router.post(
    "/{car_id}/actions",
    response_model=CarResponse,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_RESPONSES,
)
def add_action(
    principal: Editor, repository: Repository, car_id: int, request: ActionCreate
) -> CarResponse:
    try:
        row = service.add_action(repository, car_id, request, _actor(principal))
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return _response(principal, row)


@router.put("/{car_id}/actions/{action_id}", response_model=CarResponse, responses=WRITE_RESPONSES)
def update_action(
    principal: Editor, repository: Repository, car_id: int, action_id: int, request: ActionUpdate
) -> CarResponse:
    try:
        row = service.update_action(
            repository, car_id, action_id, request, request.version, _actor(principal)
        )
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return _response(principal, row)


@router.post(
    "/{car_id}/actions/{action_id}/complete",
    response_model=CarResponse,
    responses=WRITE_RESPONSES,
)
def complete_action(
    principal: Editor,
    repository: Repository,
    car_id: int,
    action_id: int,
    request: ActionComplete,
) -> CarResponse:
    try:
        row = service.complete_action(repository, car_id, action_id, request, _actor(principal))
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return _response(principal, row)


@router.post("/{car_id}/quality-cost", response_model=CarResponse, responses=WRITE_RESPONSES)
def create_quality_cost(
    principal: Editor, repository: Repository, car_id: int, request: QualityCostCreate
) -> CarResponse:
    """Create a Quality Cost record from the report's cost impact and link it."""
    if not principal.has(Permission.QUALITY_COST_EDIT):
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "forbidden",
            "Adding Quality Cost records needs the quality.cost.edit permission.",
        )
    try:
        row = service.create_quality_cost(repository, car_id, request, _actor(principal))
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return _response(principal, row)


@router.put("/{car_id}/quality-cost", response_model=CarResponse, responses=WRITE_RESPONSES)
def link_quality_cost(
    principal: Editor, repository: Repository, car_id: int, request: QualityCostLink
) -> CarResponse:
    """Link an existing Quality Cost record (``recordId``), or remove the link (null)."""
    if not principal.has(Permission.QUALITY_COST_VIEW):
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "forbidden",
            "Linking Quality Cost records needs the quality.cost.view permission.",
        )
    try:
        row = service.link_quality_cost(repository, car_id, request, _actor(principal))
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return _response(principal, row)
