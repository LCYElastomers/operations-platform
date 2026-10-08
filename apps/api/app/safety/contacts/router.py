"""Supervisor Safety Contacts endpoints (``safety.contacts.view`` / ``.edit``)."""

import datetime as dt
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import SQLAlchemyError

from app.core.authorization import UserPrincipal, require_permission
from app.core.permissions import Permission
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.safety.contacts import service
from app.safety.contacts.repository import (
    ContactFilter,
    ContactRecord,
    ContactRepository,
    DatabaseContactRepository,
    SupervisorRecord,
)
from app.safety.contacts.schemas import (
    ContactCreate,
    ContactDashboardResponse,
    ContactListResponse,
    ContactOut,
    ContactSummaryResponse,
    ContactUpdate,
    SupervisorInput,
    SupervisorListResponse,
    SupervisorOut,
    SupervisorUpdate,
)
from app.safety.contacts.service import (
    ContactNotFoundError,
    ContactRuleError,
    EditConflictError,
    RequestReusedError,
    SupervisorHasContactsError,
    SupervisorNotFoundError,
)
from app.safety.models import MAX_REPORTING_YEAR, MIN_REPORTING_YEAR
from app.safety.site_calendar import site_today

router = APIRouter(prefix="/safety/contacts", tags=["safety"])

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500

WRITE_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not signed in"},
    403: {"description": "Missing safety.contacts.edit"},
    422: {"description": "Invalid input or a program rule was broken; nothing saved"},
    503: {"description": "Database unavailable; nothing saved"},
}


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


def _invalid(error: str, message: str, **extra: Any) -> HTTPException:
    return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, error, message, **extra)


def _rule_broken(error: ContactRuleError) -> HTTPException:
    return _invalid(error.error, error.message, **error.details)


def _contact_not_found() -> HTTPException:
    return _error(
        status.HTTP_404_NOT_FOUND,
        "contact_not_found",
        "The contact does not exist. It may have been deleted.",
    )


def _supervisor_not_found() -> HTTPException:
    return _error(
        status.HTTP_404_NOT_FOUND,
        "supervisor_not_found",
        "The supervisor does not exist. They may have been removed.",
    )


def contact_repository() -> Iterator[ContactRepository]:
    """Repository bound to a request-scoped session. A missing database is a 503."""
    try:
        sessions = get_sessionmaker()
    except DatabaseNotConfiguredError:
        raise _database_unavailable() from None
    with sessions() as session:
        yield DatabaseContactRepository(session)


Repository = Annotated[ContactRepository, Depends(contact_repository)]
Viewer = Annotated[UserPrincipal, Depends(require_permission(Permission.SAFETY_CONTACTS_VIEW))]
Editor = Annotated[UserPrincipal, Depends(require_permission(Permission.SAFETY_CONTACTS_EDIT))]
Year = Annotated[int, Query(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)]
Month = Annotated[int | None, Query(ge=1, le=12)]


def _can_edit(principal: UserPrincipal) -> bool:
    return principal.has(Permission.SAFETY_CONTACTS_EDIT)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _actor(principal: UserPrincipal) -> str:
    assert principal.user_id is not None  # noqa: S101 - require_permission admits users only
    return principal.user_id


# Supervisors ---------------------------------------------------------------------


@router.get("/supervisors", response_model=SupervisorListResponse)
def list_supervisors(principal: Viewer, repository: Repository) -> SupervisorListResponse:
    """Every supervisor on the program list, active and inactive, alphabetical."""
    try:
        supervisors = repository.supervisors()
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return SupervisorListResponse(
        supervisors=[service.supervisor_out(s) for s in supervisors],
        can_edit=_can_edit(principal),
    )


@router.post(
    "/supervisors",
    response_model=SupervisorOut,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_RESPONSES,
)
def create_supervisor(
    principal: Editor, repository: Repository, request: SupervisorInput
) -> SupervisorOut:
    """Add a supervisor to the program list (audited)."""
    try:
        record = service.create_supervisor(
            repository, request, actor_id=_actor(principal), now=_now()
        )
    except ContactRuleError as error:
        raise _rule_broken(error) from None
    except SQLAlchemyError:
        repository.rollback()
        raise _database_unavailable() from None
    return service.supervisor_out(record)


@router.put(
    "/supervisors/{supervisor_id}",
    response_model=SupervisorOut,
    responses={
        **WRITE_RESPONSES,
        404: {"description": "No such supervisor"},
        409: {"description": "Changed by someone else since it was loaded; nothing saved"},
    },
)
def update_supervisor(
    principal: Editor, repository: Repository, supervisor_id: int, request: SupervisorUpdate
) -> SupervisorOut:
    """Correct a supervisor's name, status, eligibility, or effective dates (audited)."""
    try:
        record = service.update_supervisor(
            repository, supervisor_id, request, actor_id=_actor(principal), now=_now()
        )
    except ContactRuleError as error:
        raise _rule_broken(error) from None
    except SupervisorNotFoundError:
        raise _supervisor_not_found() from None
    except EditConflictError as error:
        assert isinstance(error.current, SupervisorRecord)  # noqa: S101
        raise _error(
            status.HTTP_409_CONFLICT,
            "edit_conflict",
            "This supervisor was changed by someone else since you loaded it. Nothing was saved.",
            current=service.supervisor_out(error.current).model_dump(mode="json", by_alias=True),
        ) from None
    except SQLAlchemyError:
        repository.rollback()
        raise _database_unavailable() from None
    return service.supervisor_out(record)


@router.delete(
    "/supervisors/{supervisor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        **WRITE_RESPONSES,
        404: {"description": "No such supervisor"},
        409: {"description": "The supervisor has contacts; set them inactive instead"},
    },
)
def delete_supervisor(principal: Editor, repository: Repository, supervisor_id: int) -> Response:
    """Remove a supervisor added by mistake (audited). Supervisors with contacts are kept."""
    try:
        service.delete_supervisor(repository, supervisor_id, actor_id=_actor(principal), now=_now())
    except SupervisorNotFoundError:
        raise _supervisor_not_found() from None
    except SupervisorHasContactsError:
        raise _error(
            status.HTTP_409_CONFLICT,
            "supervisor_has_contacts",
            "Contacts are recorded for this supervisor, so they cannot be deleted. "
            "Set them inactive instead.",
        ) from None
    except SQLAlchemyError:
        repository.rollback()
        raise _database_unavailable() from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Contacts ------------------------------------------------------------------------


@router.get("", response_model=ContactListResponse)
def list_contacts(
    principal: Viewer,
    repository: Repository,
    year: Annotated[int | None, Query(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)] = None,
    month: Month = None,
    contact_from: Annotated[dt.date | None, Query(alias="contactFrom")] = None,
    contact_to: Annotated[dt.date | None, Query(alias="contactTo")] = None,
    supervisor_id: Annotated[int | None, Query(alias="supervisorId", ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ContactListResponse:
    """Contacts matching every given filter, newest contact date first.

    ``year`` (optionally with ``month``) and ``contactFrom``/``contactTo``
    (inclusive) may be combined; the result is their intersection.
    """
    if month is not None and year is None:
        raise _invalid("month_requires_year", "A month filter needs a year.")
    if contact_from and contact_to and contact_from > contact_to:
        raise _invalid("invalid_date_range", "contactFrom must not be after contactTo.")
    starts, ends = [contact_from], [contact_to]
    if year is not None:
        reporting_period = service.period(year, month)
        starts.append(reporting_period.contact_from)
        ends.append(reporting_period.contact_to)
    criteria = ContactFilter(
        contact_from=max((d for d in starts if d), default=None),
        contact_to=min((d for d in ends if d), default=None),
        supervisor_id=supervisor_id,
    )
    try:
        records, total = repository.search(criteria, limit=limit, offset=offset)
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return ContactListResponse(
        contacts=[service.contact_out(record) for record in records],
        total_matching=total,
        can_edit=_can_edit(principal),
    )


@router.post(
    "",
    response_model=ContactOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        **WRITE_RESPONSES,
        200: {"description": "This requestId was already recorded; the existing contact"},
        409: {"description": "This requestId was already used for a different contact"},
    },
)
def create_contact(
    principal: Editor, repository: Repository, request: ContactCreate, response: Response
) -> ContactOut:
    """Credit one contact to one supervisor (audited)."""
    try:
        record, created = service.create_contact(
            repository, request, actor_id=_actor(principal), now=_now()
        )
    except ContactRuleError as error:
        raise _rule_broken(error) from None
    except RequestReusedError:
        raise _error(
            status.HTTP_409_CONFLICT,
            "request_id_reused",
            "This request was already used for a different contact. Nothing was saved.",
        ) from None
    except SQLAlchemyError:
        repository.rollback()
        raise _database_unavailable() from None
    if not created:
        response.status_code = status.HTTP_200_OK
    return service.contact_out(record)


@router.put(
    "/{contact_id}",
    response_model=ContactOut,
    responses={
        **WRITE_RESPONSES,
        404: {"description": "No such contact"},
        409: {"description": "Changed by someone else since it was loaded; nothing saved"},
    },
)
def update_contact(
    principal: Editor, repository: Repository, contact_id: int, request: ContactUpdate
) -> ContactOut:
    """Change a contact's date or supervisor (audited). Unchanged contacts are not written."""
    try:
        record = service.update_contact(
            repository, contact_id, request, actor_id=_actor(principal), now=_now()
        )
    except ContactRuleError as error:
        raise _rule_broken(error) from None
    except ContactNotFoundError:
        raise _contact_not_found() from None
    except EditConflictError as error:
        assert isinstance(error.current, ContactRecord)  # noqa: S101
        raise _error(
            status.HTTP_409_CONFLICT,
            "edit_conflict",
            "This contact was changed by someone else since you loaded it. Nothing was saved.",
            current=service.contact_out(error.current).model_dump(mode="json", by_alias=True),
        ) from None
    except SQLAlchemyError:
        repository.rollback()
        raise _database_unavailable() from None
    return service.contact_out(record)


@router.delete(
    "/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**WRITE_RESPONSES, 404: {"description": "No such contact"}},
)
def delete_contact(principal: Editor, repository: Repository, contact_id: int) -> Response:
    """Delete a contact, e.g. to undo a +1. Its last values remain in the audit trail."""
    try:
        service.delete_contact(repository, contact_id, actor_id=_actor(principal), now=_now())
    except ContactNotFoundError:
        raise _contact_not_found() from None
    except SQLAlchemyError:
        repository.rollback()
        raise _database_unavailable() from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Counts --------------------------------------------------------------------------


@router.get("/summary", response_model=ContactSummaryResponse)
def contact_summary(
    principal: Viewer, repository: Repository, year: Year, month: Month = None
) -> ContactSummaryResponse:
    """Contacts per supervisor for a year or one month; participation for a month."""
    try:
        return service.summarize(repository, year=year, month=month)
    except SQLAlchemyError:
        raise _database_unavailable() from None


@router.get("/dashboard", response_model=ContactDashboardResponse)
def contact_dashboard(
    principal: Viewer, repository: Repository, year: Year
) -> ContactDashboardResponse:
    """Year totals, monthly contacts and participation, and the supervisor x month counts."""
    try:
        return service.dashboard(repository, year=year, today=site_today(_now()))
    except SQLAlchemyError:
        raise _database_unavailable() from None
