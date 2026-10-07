"""Safety Observations endpoints (``safety.observations.view`` / ``.edit``)."""

import datetime as dt
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import SQLAlchemyError

from app.core.authorization import UserPrincipal, require_permission
from app.core.permissions import Permission
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.safety.models import MAX_REPORTING_YEAR, MIN_REPORTING_YEAR
from app.safety.observations import service
from app.safety.observations.repository import (
    DatabaseObservationRepository,
    ObservationFilter,
    ObservationRepository,
)
from app.safety.observations.schemas import (
    Kind,
    ObservationCategoriesResponse,
    ObservationCategoryOut,
    ObservationDashboardResponse,
    ObservationInput,
    ObservationListResponse,
    ObservationOut,
    ObservationSummaryResponse,
    ObservationUpdate,
    Outcome,
)
from app.safety.observations.service import (
    EditConflictError,
    ObservationNotFoundError,
    ObservedOnInFutureError,
    UnknownCategoryError,
)

router = APIRouter(prefix="/safety/observations", tags=["safety"])

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500

WRITE_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not signed in"},
    403: {"description": "Missing safety.observations.edit"},
    422: {"description": "Invalid observation or unknown category; nothing saved"},
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


def _not_found() -> HTTPException:
    return _error(
        status.HTTP_404_NOT_FOUND,
        "observation_not_found",
        "The observation does not exist. It may have been deleted.",
    )


def _invalid(error: str, message: str, **extra: Any) -> HTTPException:
    return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, error, message, **extra)


def observation_repository() -> Iterator[ObservationRepository]:
    """Repository bound to a request-scoped session. A missing database is a 503."""
    try:
        sessions = get_sessionmaker()
    except DatabaseNotConfiguredError:
        raise _database_unavailable() from None
    with sessions() as session:
        yield DatabaseObservationRepository(session)


Repository = Annotated[ObservationRepository, Depends(observation_repository)]
Viewer = Annotated[UserPrincipal, Depends(require_permission(Permission.SAFETY_OBSERVATIONS_VIEW))]
Editor = Annotated[UserPrincipal, Depends(require_permission(Permission.SAFETY_OBSERVATIONS_EDIT))]
Year = Annotated[int, Query(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)]
Month = Annotated[int | None, Query(ge=1, le=12)]


def _can_edit(principal: UserPrincipal) -> bool:
    return principal.has(Permission.SAFETY_OBSERVATIONS_EDIT)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@router.get("/categories", response_model=ObservationCategoriesResponse)
def observation_categories(
    principal: Viewer, repository: Repository
) -> ObservationCategoriesResponse:
    """Categories offered for new observations, in display order."""
    try:
        categories = service.active_categories(repository)
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return ObservationCategoriesResponse(
        categories=[ObservationCategoryOut(id=c.id, code=c.code, name=c.name) for c in categories],
        can_edit=_can_edit(principal),
    )


@router.get("", response_model=ObservationListResponse)
def list_observations(
    principal: Viewer,
    repository: Repository,
    year: Annotated[int | None, Query(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)] = None,
    month: Month = None,
    observed_from: Annotated[dt.date | None, Query(alias="observedFrom")] = None,
    observed_to: Annotated[dt.date | None, Query(alias="observedTo")] = None,
    outcome: Outcome | None = None,
    kind: Kind | None = None,
    category_id: Annotated[int | None, Query(alias="categoryId", ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ObservationListResponse:
    """Observations matching every given filter, newest observed date first.

    ``year`` (optionally with ``month``) and ``observedFrom``/``observedTo``
    (inclusive) may be combined; the result is their intersection.
    """
    if month is not None and year is None:
        raise _invalid("month_requires_year", "A month filter needs a year.")
    if observed_from and observed_to and observed_from > observed_to:
        raise _invalid("invalid_date_range", "observedFrom must not be after observedTo.")
    starts, ends = [observed_from], [observed_to]
    if year is not None:
        reporting_period = service.period(year, month)
        starts.append(reporting_period.observed_from)
        ends.append(reporting_period.observed_to)
    start = max((d for d in starts if d), default=None)
    end = min((d for d in ends if d), default=None)
    criteria = ObservationFilter(
        observed_from=start,
        observed_to=end,
        outcome=outcome,
        kind=kind,
        category_id=category_id,
    )
    try:
        records, total = repository.search(criteria, limit=limit, offset=offset)
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return ObservationListResponse(
        observations=[service.to_out(record) for record in records],
        total_matching=total,
        can_edit=_can_edit(principal),
    )


@router.post(
    "",
    response_model=ObservationOut,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_RESPONSES,
)
def create_observation(
    principal: Editor, repository: Repository, request: ObservationInput
) -> ObservationOut:
    """Record one observation (audited)."""
    assert principal.user_id is not None  # noqa: S101 - require_permission admits users only
    try:
        record = service.create_observation(
            repository, request, actor_id=principal.user_id, now=_now()
        )
    except (UnknownCategoryError, ObservedOnInFutureError) as error:
        raise _validation_error(error) from None
    except SQLAlchemyError:
        repository.rollback()
        raise _database_unavailable() from None
    return service.to_out(record)


@router.put(
    "/{observation_id}",
    response_model=ObservationOut,
    responses={
        **WRITE_RESPONSES,
        404: {"description": "No such observation"},
        409: {"description": "Changed by someone else since it was loaded; nothing saved"},
    },
)
def update_observation(
    principal: Editor,
    repository: Repository,
    observation_id: int,
    request: ObservationUpdate,
) -> ObservationOut:
    """Replace an observation's fields (audited). Unchanged observations are not written."""
    assert principal.user_id is not None  # noqa: S101 - require_permission admits users only
    try:
        record = service.update_observation(
            repository, observation_id, request, actor_id=principal.user_id, now=_now()
        )
    except (UnknownCategoryError, ObservedOnInFutureError) as error:
        raise _validation_error(error) from None
    except ObservationNotFoundError:
        raise _not_found() from None
    except EditConflictError as error:
        raise _error(
            status.HTTP_409_CONFLICT,
            "edit_conflict",
            "This observation was changed by someone else since you loaded it. Nothing was saved.",
            current=service.to_out(error.current).model_dump(mode="json", by_alias=True),
        ) from None
    except SQLAlchemyError:
        repository.rollback()
        raise _database_unavailable() from None
    return service.to_out(record)


@router.delete(
    "/{observation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**WRITE_RESPONSES, 404: {"description": "No such observation"}},
)
def delete_observation(principal: Editor, repository: Repository, observation_id: int) -> Response:
    """Delete an observation. Its last values remain in the audit trail."""
    assert principal.user_id is not None  # noqa: S101 - require_permission admits users only
    try:
        service.delete_observation(
            repository, observation_id, actor_id=principal.user_id, now=_now()
        )
    except ObservationNotFoundError:
        raise _not_found() from None
    except SQLAlchemyError:
        repository.rollback()
        raise _database_unavailable() from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/summary", response_model=ObservationSummaryResponse)
def observation_summary(
    principal: Viewer, repository: Repository, year: Year, month: Month = None
) -> ObservationSummaryResponse:
    """Counts for a year or one month, all derived from the same observation records."""
    try:
        return service.summarize(repository, year=year, month=month)
    except SQLAlchemyError:
        raise _database_unavailable() from None


@router.get("/dashboard", response_model=ObservationDashboardResponse)
def observation_dashboard(
    principal: Viewer, repository: Repository, year: Year
) -> ObservationDashboardResponse:
    """Year totals, monthly counts, and per-category counts derived from observation records."""
    try:
        return service.dashboard(repository, year=year, today=_now().date())
    except SQLAlchemyError:
        raise _database_unavailable() from None


def _validation_error(error: UnknownCategoryError | ObservedOnInFutureError) -> HTTPException:
    if isinstance(error, UnknownCategoryError):
        return _invalid(
            "unknown_category",
            "The category is not an active Safety Observation category.",
            categoryId=error.category_id,
        )
    return _invalid(
        "observed_on_in_future",
        "The observed date cannot be in the future.",
        today=error.today.isoformat(),
    )
