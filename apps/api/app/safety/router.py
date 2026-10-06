"""Safety endpoints. Each Safety function has its own metric set and permissions."""

import datetime as dt
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from app.core.authorization import UserPrincipal, require_permission
from app.core.permissions import Permission
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.safety import service
from app.safety.models import MAX_REPORTING_YEAR, MIN_REPORTING_YEAR
from app.safety.repository import DatabaseSafetyMetricsRepository, SafetyMetricsRepository
from app.safety.schemas import (
    MonthlyMetricsResponse,
    SaveMonthlyMetricsRequest,
    SaveMonthlyMetricsResponse,
)
from app.safety.service import EditConflictError, UnknownCategoryError

router = APIRouter(prefix="/safety", tags=["safety"])

INCIDENTS_METRIC_SET = "incidents"


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


def safety_repository() -> Iterator[SafetyMetricsRepository]:
    """Repository bound to a request-scoped session. A missing database is a 503."""
    try:
        sessions = get_sessionmaker()
    except DatabaseNotConfiguredError:
        raise _database_unavailable() from None
    with sessions() as session:
        yield DatabaseSafetyMetricsRepository(session)


Repository = Annotated[SafetyMetricsRepository, Depends(safety_repository)]
IncidentViewer = Annotated[
    UserPrincipal, Depends(require_permission(Permission.SAFETY_INCIDENTS_VIEW))
]
IncidentEditor = Annotated[
    UserPrincipal, Depends(require_permission(Permission.SAFETY_INCIDENTS_EDIT))
]


@router.get("/incidents/metrics", response_model=MonthlyMetricsResponse)
def incident_metrics(
    principal: IncidentViewer,
    repository: Repository,
    year: Annotated[int, Query(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)],
) -> MonthlyMetricsResponse:
    """Incident & Near Miss monthly values for one reporting year, with calculated totals."""
    try:
        return service.load_metrics(
            repository,
            metric_set=INCIDENTS_METRIC_SET,
            year=year,
            can_edit=principal.has(Permission.SAFETY_INCIDENTS_EDIT),
        )
    except SQLAlchemyError:
        raise _database_unavailable() from None


@router.patch(
    "/incidents/metrics",
    response_model=SaveMonthlyMetricsResponse,
    responses={
        401: {"description": "Not signed in"},
        403: {"description": "Missing safety.incidents.edit"},
        409: {"description": "Stored values changed since they were loaded; nothing saved"},
        422: {"description": "Invalid request or unknown category; nothing saved"},
        503: {"description": "Database unavailable; nothing saved"},
    },
)
def save_incident_metrics(
    principal: IncidentEditor,
    repository: Repository,
    request: SaveMonthlyMetricsRequest,
) -> SaveMonthlyMetricsResponse:
    """Set or clear monthly cells. All changes are applied together or not at all."""
    assert principal.user_id is not None  # noqa: S101 - require_permission admits users only
    try:
        outcome = service.save_changes(
            repository,
            metric_set=INCIDENTS_METRIC_SET,
            year=request.year,
            changes=request.changes,
            actor_id=principal.user_id,
            now=dt.datetime.now(dt.UTC),
        )
        metrics = service.load_metrics(
            repository, metric_set=INCIDENTS_METRIC_SET, year=request.year, can_edit=True
        )
    except UnknownCategoryError as error:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "unknown_category",
            "One or more categories are not active Incident & Near Miss categories.",
            categoryIds=error.category_ids,
        ) from None
    except EditConflictError as error:
        raise _error(
            status.HTTP_409_CONFLICT,
            "edit_conflict",
            "Some values were changed by someone else since you loaded them. Nothing was saved.",
            conflicts=[c.model_dump(by_alias=True) for c in error.conflicts],
        ) from None
    except SQLAlchemyError:
        repository.rollback()
        raise _database_unavailable() from None
    return SaveMonthlyMetricsResponse(changed_cells=outcome.changed_cells, metrics=metrics)
