"""Safety Performance endpoints: ``safetyRecord.view`` / ``.edit``; clearing a
month ``.delete``; closing or reopening ``.close``; the dashboard also needs
``safetyDashboard.view``."""

import datetime as dt
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.exc import SQLAlchemyError

from app.core.authorization import UserPrincipal, require_all_permissions, require_permission
from app.core.permissions import Permission
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.safety.models import MAX_REPORTING_YEAR, MIN_REPORTING_YEAR
from app.safety.performance import service
from app.safety.performance.repository import (
    DatabasePerformanceRepository,
    PerformanceRepository,
)
from app.safety.performance.schemas import (
    HoursOut,
    PerformanceDashboardResponse,
    PerformanceYearResponse,
    SaveMonthHoursRequest,
)
from app.safety.performance.service import EditConflictError, PerformanceRuleError

router = APIRouter(prefix="/safety/performance", tags=["safety"])

WRITE_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not signed in"},
    403: {"description": "Missing permission"},
    409: {"description": "The month changed since it was loaded; nothing saved"},
    422: {"description": "Invalid input or a Safety Performance rule was broken; nothing saved"},
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


def _conflict(error: EditConflictError) -> HTTPException:
    current = error.current
    return _error(
        status.HTTP_409_CONFLICT,
        "edit_conflict",
        "This month was changed by someone else since you loaded it. Nothing was saved.",
        current=(
            service.hours_out(current).model_dump(mode="json", by_alias=True)
            if current is not None
            else None
        ),
    )


def performance_repository() -> Iterator[PerformanceRepository]:
    """Repository bound to a request-scoped session. A missing database is a 503."""
    try:
        sessions = get_sessionmaker()
    except DatabaseNotConfiguredError:
        raise _database_unavailable() from None
    with sessions() as session:
        yield DatabasePerformanceRepository(session)


Repository = Annotated[PerformanceRepository, Depends(performance_repository)]
Viewer = Annotated[UserPrincipal, Depends(require_permission(Permission.SAFETY_RECORD_VIEW))]
Editor = Annotated[UserPrincipal, Depends(require_permission(Permission.SAFETY_RECORD_EDIT))]
Clearer = Annotated[UserPrincipal, Depends(require_permission(Permission.SAFETY_RECORD_DELETE))]
DashboardViewer = Annotated[
    UserPrincipal,
    Depends(
        require_all_permissions(Permission.SAFETY_RECORD_VIEW, Permission.SAFETY_DASHBOARD_VIEW)
    ),
]
Year = Annotated[int, Query(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)]
PathYear = Annotated[int, Path(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)]
PathMonth = Annotated[int, Path(ge=1, le=12)]


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _forbidden(error: service.PerformanceForbiddenError) -> HTTPException:
    return _error(status.HTTP_403_FORBIDDEN, "permission_denied", str(error))


@router.get("/months", response_model=PerformanceYearResponse)
def get_months(principal: Viewer, repository: Repository, year: Year) -> PerformanceYearResponse:
    """A year's worked hours, month status and read-only event counts."""
    try:
        return service.year_view(
            repository,
            year,
            can_edit=principal.has(Permission.SAFETY_RECORD_EDIT),
            now=_now(),
        )
    except SQLAlchemyError:
        raise _database_unavailable() from None


@router.put("/months/{year}/{month}", response_model=HoursOut, responses=WRITE_RESPONSES)
def save_month(
    principal: Editor,
    repository: Repository,
    year: PathYear,
    month: PathMonth,
    request: SaveMonthHoursRequest,
) -> HoursOut:
    """Save one month's hours and closed status (audited). Closing, reopening or
    changing a closed month also needs ``safetyRecord.close``."""
    try:
        record = service.save_month(
            repository,
            year,
            month,
            request,
            actor_id=principal.actor_id,
            now=_now(),
            can_close=principal.has(Permission.SAFETY_RECORD_CLOSE),
        )
    except service.PerformanceForbiddenError as error:
        raise _forbidden(error) from None
    except PerformanceRuleError as error:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, error.error, error.message) from None
    except EditConflictError as error:
        raise _conflict(error) from None
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return service.hours_out(record)


@router.delete(
    "/months/{year}/{month}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_RESPONSES,
)
def clear_month(
    principal: Clearer,
    repository: Repository,
    year: PathYear,
    month: PathMonth,
    expected_updated_at: Annotated[dt.datetime, Query(alias="expectedUpdatedAt")],
) -> Response:
    """Remove a month's hours so it is Not Reported again (audited)."""
    try:
        service.clear_month(
            repository,
            year,
            month,
            expected_updated_at=expected_updated_at,
            actor_id=principal.actor_id,
            now=_now(),
            can_close=principal.has(Permission.SAFETY_RECORD_CLOSE),
        )
    except service.PerformanceForbiddenError as error:
        raise _forbidden(error) from None
    except EditConflictError as error:
        raise _conflict(error) from None
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/dashboard", response_model=PerformanceDashboardResponse)
def get_dashboard(
    principal: DashboardViewer,
    repository: Repository,
    year: Year,
    through_month: Annotated[int | None, Query(alias="throughMonth", ge=1, le=12)] = None,
) -> PerformanceDashboardResponse:
    """YTD and 12MRA rates through a closed month, monthly trends and annual TRIR."""
    try:
        return service.dashboard(repository, year, through_month=through_month, now=_now())
    except SQLAlchemyError:
        raise _database_unavailable() from None
