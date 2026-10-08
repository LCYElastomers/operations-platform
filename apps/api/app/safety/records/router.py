"""Incident and Near Miss record endpoints.

Reading records needs ``safety.incidents.records.view``; creating and editing
``safety.incidents.records.edit``; voiding and reclassifying
``safety.incidents.records.manage``; reading a record's audit history
``safety.incidents.history.view``.
"""

import datetime as dt
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from app.core.authorization import UserPrincipal, require_permission
from app.core.permissions import Permission
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.safety.models import MAX_REPORTING_YEAR, MIN_REPORTING_YEAR
from app.safety.records import service
from app.safety.records.numbers import InvalidIncidentNumberError, normalize_incident_number
from app.safety.records.repository import RecordFilter, RecordRepository
from app.safety.records.schemas import (
    EventType,
    HistoryEventOut,
    HistoryResponse,
    OptionOut,
    ReclassifyRequest,
    ReclassifyResponse,
    ReconciliationResponse,
    RecordCreate,
    RecordListResponse,
    RecordOptionsResponse,
    RecordResponse,
    RecordStatus,
    RecordUpdate,
    VoidRequest,
)

router = APIRouter(prefix="/safety/incidents", tags=["safety"])

MAX_PAGE = 500


def _error(status_code: int, error: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error": error, "message": message, **extra}
    )


def _database_unavailable() -> HTTPException:
    return _error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "database_unavailable",
        "Safety data is unavailable because the database could not be reached.",
    )


def record_repository() -> Iterator[RecordRepository]:
    try:
        sessions = get_sessionmaker()
    except DatabaseNotConfiguredError:
        raise _database_unavailable() from None
    with sessions() as session:
        yield RecordRepository(session)


Repository = Annotated[RecordRepository, Depends(record_repository)]
Viewer = Annotated[
    UserPrincipal, Depends(require_permission(Permission.SAFETY_INCIDENT_RECORDS_VIEW))
]
Editor = Annotated[
    UserPrincipal, Depends(require_permission(Permission.SAFETY_INCIDENT_RECORDS_EDIT))
]
Manager = Annotated[
    UserPrincipal, Depends(require_permission(Permission.SAFETY_INCIDENT_RECORDS_MANAGE))
]
HistoryViewer = Annotated[
    UserPrincipal, Depends(require_permission(Permission.SAFETY_INCIDENT_HISTORY_VIEW))
]

WRITE_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not signed in"},
    403: {"description": "Missing permission"},
    404: {"description": "No such record"},
    409: {"description": "The record changed since it was loaded; nothing saved"},
    422: {"description": "Invalid request; nothing saved"},
    503: {"description": "Database unavailable; nothing saved"},
}


def _permissions(principal: UserPrincipal) -> dict[str, bool]:
    return {
        "can_edit": principal.has(Permission.SAFETY_INCIDENT_RECORDS_EDIT),
        "can_manage": principal.has(Permission.SAFETY_INCIDENT_RECORDS_MANAGE),
        "can_view_history": principal.has(Permission.SAFETY_INCIDENT_HISTORY_VIEW),
    }


def _actor(principal: UserPrincipal) -> service.Actor:
    assert principal.user_id is not None  # noqa: S101 - require_permission admits users only
    return service.Actor(principal.user_id, dt.datetime.now(dt.UTC))


def _write_error(error: Exception) -> HTTPException:
    if isinstance(error, service.RecordNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "record_not_found", "No such record.")
    if isinstance(error, service.RecordConflictError):
        return _error(
            status.HTTP_409_CONFLICT,
            "edit_conflict",
            "This record was changed by someone else since you loaded it. Nothing was saved.",
            current=service.record_out(error.current).model_dump(mode="json", by_alias=True),
        )
    if isinstance(error, service.RecordRuleError):
        return _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, error.error, error.message, field=error.field
        )
    return _database_unavailable()


_WRITE_ERRORS = (
    service.RecordNotFoundError,
    service.RecordConflictError,
    service.RecordRuleError,
    SQLAlchemyError,
)


@router.get("/records", response_model=RecordListResponse)
def list_records(
    principal: Viewer,
    repository: Repository,
    year: Annotated[int | None, Query(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)] = None,
    through: Annotated[int | None, Query(ge=1, le=12)] = None,
    month: Annotated[int | None, Query(ge=1, le=12)] = None,
    event_type: Annotated[EventType | None, Query(alias="eventType")] = None,
    area_id: Annotated[int | None, Query(alias="areaId", ge=1)] = None,
    classification_id: Annotated[int | None, Query(alias="classificationId", ge=1)] = None,
    record_status: Annotated[list[RecordStatus] | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = MAX_PAGE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RecordListResponse:
    """Records, oldest first. Active records only unless ``status`` says otherwise.
    ``search`` matches the description or the number (in any accepted form)."""
    if (through is not None or month is not None) and year is None:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "year_required",
            "Choose a year to filter by month.",
        )
    text = search.strip() if search else None
    try:
        number = normalize_incident_number(text) if text else None
    except InvalidIncidentNumberError:
        number = None
    criteria = RecordFilter(
        year=year,
        through_month=through,
        month=month,
        event_type=event_type,
        area_id=area_id,
        classification_category_id=classification_id,
        statuses=tuple(record_status) if record_status else ("active",),
        search=text or None,
        search_number=number,
    )
    try:
        rows, total = repository.search(criteria, limit=limit, offset=offset)
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return RecordListResponse(
        records=[service.record_out(r) for r in rows], total=total, **_permissions(principal)
    )


@router.get("/records/options", response_model=RecordOptionsResponse)
def record_options(principal: Viewer, repository: Repository) -> RecordOptionsResponse:
    """Areas and Incident Classifications a record can reference (inactive ones flagged)."""
    try:
        areas, classifications = repository.areas(), repository.classifications()
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return RecordOptionsResponse(
        areas=[OptionOut(id=o.id, code=o.code, name=o.name, active=o.active) for o in areas],
        classifications=[
            OptionOut(id=o.id, code=o.code, name=o.name, active=o.active) for o in classifications
        ],
    )


@router.get("/records/reconciliation", response_model=ReconciliationResponse)
def record_reconciliation(
    principal: Viewer,
    repository: Repository,
    year: Annotated[int, Query(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)],
) -> ReconciliationResponse:
    """Monthly Incident and Near Miss totals against their active records. Warnings only."""
    try:
        return service.reconciliation(repository, year, _permissions(principal))
    except SQLAlchemyError:
        raise _database_unavailable() from None


@router.get("/records/{record_id}", response_model=RecordResponse)
def get_record(principal: Viewer, repository: Repository, record_id: int) -> RecordResponse:
    try:
        row = repository.get(record_id)
    except SQLAlchemyError:
        raise _database_unavailable() from None
    if row is None:
        raise _error(status.HTTP_404_NOT_FOUND, "record_not_found", "No such record.")
    return RecordResponse(record=service.record_out(row), **_permissions(principal))


@router.get("/records/{record_id}/history", response_model=HistoryResponse)
def record_history(
    principal: HistoryViewer, repository: Repository, record_id: int
) -> HistoryResponse:
    """The record's audit trail, oldest first."""
    try:
        if repository.get(record_id) is None:
            raise _error(status.HTTP_404_NOT_FOUND, "record_not_found", "No such record.")
        events = repository.history(service.ENTITY_TYPE, service.entity_key(record_id))
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return HistoryResponse(
        record_id=record_id,
        events=[
            HistoryEventOut(
                occurred_at=e.occurred_at,
                actor_id=e.actor_id,
                action=e.action,  # type: ignore[arg-type]
                change_set_id=str(e.change_set_id),
                old_value=service.public_audit_value(e.old_value),
                new_value=service.public_audit_value(e.new_value),
            )
            for e in events
        ],
    )


@router.post(
    "/records",
    response_model=RecordResponse,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_RESPONSES,
)
def create_record(
    principal: Editor, repository: Repository, request: RecordCreate
) -> RecordResponse:
    try:
        row = service.create(repository, request, _actor(principal))
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return RecordResponse(record=service.record_out(row), **_permissions(principal))


@router.put("/records/{record_id}", response_model=RecordResponse, responses=WRITE_RESPONSES)
def update_record(
    principal: Editor, repository: Repository, record_id: int, request: RecordUpdate
) -> RecordResponse:
    try:
        row = service.update(repository, record_id, request, _actor(principal))
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return RecordResponse(record=service.record_out(row), **_permissions(principal))


@router.post("/records/{record_id}/void", response_model=RecordResponse, responses=WRITE_RESPONSES)
def void_record(
    principal: Manager, repository: Repository, record_id: int, request: VoidRequest
) -> RecordResponse:
    try:
        row = service.void(repository, record_id, request, _actor(principal))
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return RecordResponse(record=service.record_out(row), **_permissions(principal))


@router.post(
    "/records/{record_id}/reclassify",
    response_model=ReclassifyResponse,
    responses=WRITE_RESPONSES,
)
def reclassify_record(
    principal: Manager, repository: Repository, record_id: int, request: ReclassifyRequest
) -> ReclassifyResponse:
    try:
        original, replacement = service.reclassify(
            repository, record_id, request, _actor(principal)
        )
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return ReclassifyResponse(
        record=service.record_out(original),
        replacement=service.record_out(replacement),
        **_permissions(principal),
    )
