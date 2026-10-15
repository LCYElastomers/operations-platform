"""Safety endpoints. Each Safety function has its own metric set and permissions."""

import datetime as dt
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.authorization import UserPrincipal, require_all_permissions, require_permission
from app.core.permissions import Permission
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.safety import analytics, service
from app.safety.analytics import MonthNotStartedError
from app.safety.behavior import service as behavior_service
from app.safety.behavior.repository import BehaviorRepository, DatabaseBehaviorRepository
from app.safety.behavior.schemas import (
    BehaviorCountsResponse,
    SaveBehaviorCountsRequest,
    SaveBehaviorCountsResponse,
)
from app.safety.behavior.service import BehaviorConflictError, UnknownBehaviorCategoryError
from app.safety.models import MAX_REPORTING_YEAR, MIN_REPORTING_YEAR
from app.safety.records import insights
from app.safety.records.schemas import (
    EventExperienceResponse,
    LopcRecordsResponse,
    SeriousRiskResponse,
)
from app.safety.repository import DatabaseSafetyMetricsRepository, SafetyMetricsRepository
from app.safety.schemas import (
    IncidentAnalyticsResponse,
    MonthlyMetricsResponse,
    SaveMonthlyMetricsRequest,
    SaveMonthlyMetricsResponse,
)
from app.safety.service import EditConflictError, UnknownCategoryError
from app.safety.site_calendar import site_today

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


def behavior_repository() -> Iterator[BehaviorRepository]:
    try:
        sessions = get_sessionmaker()
    except DatabaseNotConfiguredError:
        raise _database_unavailable() from None
    with sessions() as session:
        yield DatabaseBehaviorRepository(session)


Repository = Annotated[SafetyMetricsRepository, Depends(safety_repository)]
Behavior = Annotated[BehaviorRepository, Depends(behavior_repository)]
IncidentViewer = Annotated[
    UserPrincipal, Depends(require_permission(Permission.SAFETY_RECORD_VIEW))
]
IncidentEditor = Annotated[
    UserPrincipal, Depends(require_permission(Permission.SAFETY_RECORD_EDIT))
]
DashboardViewer = Annotated[
    UserPrincipal,
    Depends(
        require_all_permissions(Permission.SAFETY_RECORD_VIEW, Permission.SAFETY_DASHBOARD_VIEW)
    ),
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
            can_edit=principal.has(Permission.SAFETY_RECORD_EDIT),
        )
    except SQLAlchemyError:
        raise _database_unavailable() from None


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@router.get(
    "/incidents/analytics",
    response_model=IncidentAnalyticsResponse,
    responses={
        401: {"description": "Not signed in"},
        403: {"description": "Missing safetyRecord.view or safetyDashboard.view"},
        422: {"description": "Invalid year, or a through month that has not started"},
        503: {"description": "Database unavailable"},
    },
)
def incident_analytics(
    principal: DashboardViewer,
    repository: Repository,
    behavior: Behavior,
    year: Annotated[int, Query(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)],
    through: Annotated[int | None, Query(ge=1, le=12)] = None,
) -> IncidentAnalyticsResponse:
    """Read-only Incident & Near Miss analytics for January..through (by default the
    latest month that has started in Baytown). Behavior covers the whole year."""
    try:
        return analytics.load_analytics(
            repository, year=year, through_month=through, now=_now(), behavior=behavior
        )
    except MonthNotStartedError as error:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "month_not_started",
            "Analytics cannot run through a month that has not started.",
            latestMonth=error.latest_month,
        ) from None
    except SQLAlchemyError:
        raise _database_unavailable() from None


def insight_session() -> Iterator[Session]:
    try:
        sessions = get_sessionmaker()
    except DatabaseNotConfiguredError:
        raise _database_unavailable() from None
    with sessions() as session:
        yield session


InsightSession = Annotated[Session, Depends(insight_session)]
INSIGHT_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not signed in"},
    403: {"description": "Missing safetyRecord.view, safetyDashboard.view or incident.view"},
    422: {"description": "Invalid year, or a date or month that has not started"},
    503: {"description": "Database unavailable"},
}


def _incident_insights(principal: UserPrincipal) -> bool:
    """Record-derived views need incident.view; near misses count only with nearMiss.view."""
    if not principal.has(Permission.INCIDENT_VIEW):
        raise _error(
            status.HTTP_403_FORBIDDEN, "forbidden", "Viewing incident records is not permitted."
        )
    return principal.has(Permission.NEAR_MISS_VIEW)


def _through(year: int, through: int | None) -> int | None:
    latest = analytics.latest_started_month(year, site_today(_now()))
    if latest is None or (through is not None and through > latest):
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "month_not_started",
            "Analytics cannot run through a month that has not started.",
            latestMonth=latest,
        )
    return through or latest


@router.get(
    "/incidents/analytics/event-experience",
    response_model=EventExperienceResponse,
    responses=INSIGHT_RESPONSES,
)
def event_experience(
    principal: DashboardViewer,
    session: InsightSession,
    year: Annotated[int, Query(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)],
    as_of: Annotated[dt.date | None, Query(alias="asOf")] = None,
) -> EventExperienceResponse:
    """Days since the latest event and year-to-date counts per category, from the
    active Incident Register records. As of today in Baytown for the current year,
    31 December for a past year."""
    near_misses = _incident_insights(principal)
    today = site_today(_now())
    if year > today.year:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "year_not_started", "The year has not started."
        )
    if as_of is None:
        as_of = today if year == today.year else dt.date(year, 12, 31)
    elif as_of.year != year or as_of > today:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_as_of",
            "The as-of date must be in the selected year and not after today.",
        )
    try:
        return insights.event_experience(session, year=year, as_of=as_of, near_misses=near_misses)
    except SQLAlchemyError:
        raise _database_unavailable() from None


@router.get(
    "/incidents/analytics/lopc-records",
    response_model=LopcRecordsResponse,
    responses=INSIGHT_RESPONSES,
)
def lopc_records(
    principal: DashboardViewer,
    session: InsightSession,
    year: Annotated[int, Query(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)],
    through: Annotated[int | None, Query(ge=1, le=12)] = None,
) -> LopcRecordsResponse:
    """LOPC breakdowns from the Spill / Release records' LOPC details."""
    _incident_insights(principal)
    through = _through(year, through)
    try:
        return insights.lopc_records(session, year=year, through=through)
    except SQLAlchemyError:
        raise _database_unavailable() from None


@router.get(
    "/incidents/analytics/serious-risk",
    response_model=SeriousRiskResponse,
    responses=INSIGHT_RESPONSES,
)
def serious_risk(
    principal: DashboardViewer,
    session: InsightSession,
    year: Annotated[int, Query(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)],
    through: Annotated[int | None, Query(ge=1, le=12)] = None,
) -> SeriousRiskResponse:
    """PSIF breakdowns from the records designated PSIF."""
    near_misses = _incident_insights(principal)
    through = _through(year, through)
    try:
        return insights.serious_risk(session, year=year, through=through, near_misses=near_misses)
    except SQLAlchemyError:
        raise _database_unavailable() from None


@router.patch(
    "/incidents/metrics",
    response_model=SaveMonthlyMetricsResponse,
    responses={
        401: {"description": "Not signed in"},
        403: {"description": "Missing safetyRecord.edit"},
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
    try:
        outcome = service.save_changes(
            repository,
            metric_set=INCIDENTS_METRIC_SET,
            year=request.year,
            changes=request.changes,
            actor_id=principal.actor_id,
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


@router.get("/incidents/behavior", response_model=BehaviorCountsResponse)
def incident_behavior(
    principal: IncidentViewer,
    behavior: Behavior,
    year: Annotated[int, Query(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)],
) -> BehaviorCountsResponse:
    """Annual Behavior tag counts for one reporting year."""
    try:
        return behavior_service.load_counts(
            behavior, year=year, can_edit=principal.has(Permission.SAFETY_RECORD_EDIT)
        )
    except SQLAlchemyError:
        raise _database_unavailable() from None


@router.patch(
    "/incidents/behavior",
    response_model=SaveBehaviorCountsResponse,
    responses={
        401: {"description": "Not signed in"},
        403: {"description": "Missing safetyRecord.edit"},
        409: {"description": "Stored counts changed since they were loaded; nothing saved"},
        422: {"description": "Invalid request or unknown category; nothing saved"},
        503: {"description": "Database unavailable; nothing saved"},
    },
)
def save_incident_behavior(
    principal: IncidentEditor,
    behavior: Behavior,
    request: SaveBehaviorCountsRequest,
) -> SaveBehaviorCountsResponse:
    """Set or clear annual Behavior counts. All changes are applied together or not at all."""
    try:
        outcome = behavior_service.save_counts(
            behavior,
            year=request.year,
            changes=request.changes,
            actor_id=principal.actor_id,
            now=_now(),
        )
        counts = behavior_service.load_counts(behavior, year=request.year, can_edit=True)
    except UnknownBehaviorCategoryError as error:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "unknown_category",
            "One or more categories are not active Behavior categories.",
            categoryIds=error.category_ids,
        ) from None
    except BehaviorConflictError as error:
        raise _error(
            status.HTTP_409_CONFLICT,
            "edit_conflict",
            "Some counts were changed by someone else since you loaded them. Nothing was saved.",
            conflicts=[c.model_dump(by_alias=True) for c in error.conflicts],
        ) from None
    except SQLAlchemyError:
        behavior.rollback()
        raise _database_unavailable() from None
    return SaveBehaviorCountsResponse(changed_categories=outcome.changed_categories, counts=counts)
