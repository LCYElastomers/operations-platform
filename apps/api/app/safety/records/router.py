"""Incident and Near Miss record endpoints.

Permissions follow the record's type: ``incident.*`` for incidents and
``nearMiss.*`` for near misses. Reading needs ``.view`` (lists show only the
types the user may view); creating ``.create``; editing ``.edit``; voiding
``.delete``. Reclassifying (incident <-> near miss) needs ``incident.classify``.
A record's audit history also needs ``safetyRecord.view``.
"""

import datetime as dt
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from app.auth import people
from app.core.authorization import (
    UserPrincipal,
    ensure,
    require_any_permission,
    require_permission,
)
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
    RecordOut,
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
    UserPrincipal,
    Depends(require_any_permission(Permission.INCIDENT_VIEW, Permission.NEAR_MISS_VIEW)),
]
Creator = Annotated[
    UserPrincipal,
    Depends(require_any_permission(Permission.INCIDENT_CREATE, Permission.NEAR_MISS_CREATE)),
]
Editor = Annotated[
    UserPrincipal,
    Depends(require_any_permission(Permission.INCIDENT_EDIT, Permission.NEAR_MISS_EDIT)),
]
Voider = Annotated[
    UserPrincipal,
    Depends(require_any_permission(Permission.INCIDENT_DELETE, Permission.NEAR_MISS_DELETE)),
]
Classifier = Annotated[UserPrincipal, Depends(require_permission(Permission.INCIDENT_CLASSIFY))]
HistoryViewer = Annotated[UserPrincipal, Depends(require_permission(Permission.SAFETY_RECORD_VIEW))]

# Record-type permissions: (view, create, edit, delete).
TYPE_PERMISSIONS: dict[str, tuple[Permission, Permission, Permission, Permission]] = {
    "incident": (
        Permission.INCIDENT_VIEW,
        Permission.INCIDENT_CREATE,
        Permission.INCIDENT_EDIT,
        Permission.INCIDENT_DELETE,
    ),
    "near_miss": (
        Permission.NEAR_MISS_VIEW,
        Permission.NEAR_MISS_CREATE,
        Permission.NEAR_MISS_EDIT,
        Permission.NEAR_MISS_DELETE,
    ),
}
VIEW, CREATE, EDIT, DELETE = range(4)


def _viewable_types(principal: UserPrincipal) -> tuple[str, ...]:
    return tuple(t for t, perms in TYPE_PERMISSIONS.items() if principal.has(perms[VIEW]))


def _require_type(principal: UserPrincipal, event_type: str, which: int) -> None:
    ensure(principal, TYPE_PERMISSIONS[event_type][which])


def _type_of(repository: RecordRepository, record_id: int) -> str:
    row = repository.get(record_id)
    if row is None:
        raise _error(status.HTTP_404_NOT_FOUND, "record_not_found", "No such record.")
    return row.record.event_type


WRITE_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not signed in"},
    403: {"description": "Missing permission"},
    404: {"description": "No such record"},
    409: {"description": "The record changed since it was loaded; nothing saved"},
    422: {"description": "Invalid request; nothing saved"},
    503: {"description": "Database unavailable; nothing saved"},
}


def _types(principal: UserPrincipal, which: int) -> list[str]:
    return [t for t, perms in TYPE_PERMISSIONS.items() if principal.has(perms[which])]


def _permissions(principal: UserPrincipal) -> dict[str, Any]:
    can_classify = principal.has(Permission.INCIDENT_CLASSIFY)
    voidable = _types(principal, DELETE)
    return {
        "can_edit": bool(_types(principal, EDIT)),
        "can_manage": bool(voidable) or can_classify,
        "can_view_history": principal.has(Permission.SAFETY_RECORD_VIEW),
        "can_classify": can_classify,
        "viewable_types": _types(principal, VIEW),
        "creatable_types": _types(principal, CREATE),
        "editable_types": _types(principal, EDIT),
        "voidable_types": voidable,
    }


def _out(repository: RecordRepository, *rows: Any) -> list[RecordOut]:
    names = repository.actor_names(
        actor for row in rows for actor in (row.record.created_by, row.record.updated_by)
    )
    outs = []
    for row in rows:
        out = service.record_out(row)
        outs.append(
            out.model_copy(
                update={
                    "created_by_name": people.actor_label(out.created_by, names),
                    "updated_by_name": people.actor_label(out.updated_by, names),
                }
            )
        )
    return outs


def _actor(principal: UserPrincipal) -> service.Actor:
    return service.Actor(principal.actor_id, dt.datetime.now(dt.UTC))


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
    viewable = _viewable_types(principal)
    if event_type is not None:
        _require_type(principal, event_type, VIEW)
    elif len(viewable) == 1:
        event_type = viewable[0]  # type: ignore[assignment]
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
        records = _out(repository, *rows)
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return RecordListResponse(records=records, total=total, **_permissions(principal))


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
        if row is None:
            raise _error(status.HTTP_404_NOT_FOUND, "record_not_found", "No such record.")
        _require_type(principal, row.record.event_type, VIEW)
        (record,) = _out(repository, row)
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return RecordResponse(record=record, **_permissions(principal))


@router.get("/records/{record_id}/history", response_model=HistoryResponse)
def record_history(
    principal: HistoryViewer, repository: Repository, record_id: int
) -> HistoryResponse:
    """The record's audit trail, oldest first."""
    try:
        _require_type(principal, _type_of(repository, record_id), VIEW)
        events = repository.history(service.ENTITY_TYPE, service.entity_key(record_id))
        names = repository.actor_names(e.actor_id for e in events)
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return HistoryResponse(
        record_id=record_id,
        events=[
            HistoryEventOut(
                occurred_at=e.occurred_at,
                actor_id=e.actor_id,
                actor_name=e.actor_name or people.actor_label(e.actor_id, names),
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
    principal: Creator, repository: Repository, request: RecordCreate
) -> RecordResponse:
    _require_type(principal, request.event_type, CREATE)
    try:
        row = service.create(repository, request, _actor(principal))
        (record,) = _out(repository, row)
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return RecordResponse(record=record, **_permissions(principal))


@router.put("/records/{record_id}", response_model=RecordResponse, responses=WRITE_RESPONSES)
def update_record(
    principal: Editor, repository: Repository, record_id: int, request: RecordUpdate
) -> RecordResponse:
    try:
        _require_type(principal, _type_of(repository, record_id), EDIT)
        row = service.update(repository, record_id, request, _actor(principal))
        (record,) = _out(repository, row)
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return RecordResponse(record=record, **_permissions(principal))


@router.post("/records/{record_id}/void", response_model=RecordResponse, responses=WRITE_RESPONSES)
def void_record(
    principal: Voider, repository: Repository, record_id: int, request: VoidRequest
) -> RecordResponse:
    try:
        _require_type(principal, _type_of(repository, record_id), DELETE)
        row = service.void(repository, record_id, request, _actor(principal))
        (record,) = _out(repository, row)
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return RecordResponse(record=record, **_permissions(principal))


@router.post(
    "/records/{record_id}/reclassify",
    response_model=ReclassifyResponse,
    responses=WRITE_RESPONSES,
)
def reclassify_record(
    principal: Classifier, repository: Repository, record_id: int, request: ReclassifyRequest
) -> ReclassifyResponse:
    try:
        original, replacement = service.reclassify(
            repository, record_id, request, _actor(principal)
        )
        record, replacement_out = _out(repository, original, replacement)
    except _WRITE_ERRORS as error:
        raise _write_error(error) from None
    return ReclassifyResponse(record=record, replacement=replacement_out, **_permissions(principal))
