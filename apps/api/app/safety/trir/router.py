"""TRIR Experience endpoints (read-only; ``safetyRecord.view`` and
``safetyDashboard.view``).

``/experience`` returns everything the module shows; the other endpoints are
narrower views of the same calculation.
"""

import datetime as dt
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.authorization import UserPrincipal, require_all_permissions
from app.core.permissions import Permission
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.safety.models import MAX_REPORTING_YEAR, MIN_REPORTING_YEAR
from app.safety.performance.repository import DatabasePerformanceRepository
from app.safety.performance.service import trir_inputs
from app.safety.records.repository import RecordRepository
from app.safety.site_calendar import site_today
from app.safety.trir import service
from app.safety.trir.repository import TrirRepository
from app.safety.trir.schemas import (
    BenchmarkOut,
    CalculationOut,
    DataQualityItemOut,
    HistoryRowOut,
    MethodologyOut,
    MonthDetailOut,
    TrirExperienceResponse,
    TrirStatusOut,
)

router = APIRouter(prefix="/safety/trir", tags=["safety"])


def _database_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error": "database_unavailable",
            "message": "TRIR data is unavailable because the database could not be reached.",
        },
    )


def trir_session() -> Iterator[Session]:
    try:
        sessions = get_sessionmaker()
    except DatabaseNotConfiguredError:
        raise _database_unavailable() from None
    with sessions() as session:
        yield session


SessionDep = Annotated[Session, Depends(trir_session)]
Viewer = Annotated[
    UserPrincipal,
    Depends(
        require_all_permissions(Permission.SAFETY_RECORD_VIEW, Permission.SAFETY_DASHBOARD_VIEW)
    ),
]
Year = Annotated[int | None, Query(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)]
Through = Annotated[int | None, Query(ge=1, le=12)]

RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not signed in"},
    403: {"description": "Missing safetyRecord.view or safetyDashboard.view"},
    503: {"description": "Database unavailable"},
}


def _experience(session: Session, year: int | None, through: int | None) -> TrirExperienceResponse:
    selected = year if year is not None else site_today(dt.datetime.now(dt.UTC)).year
    performance = DatabasePerformanceRepository(session)
    records = RecordRepository(session)
    try:
        return service.experience(
            TrirRepository(session).facts(),
            lambda years: trir_inputs(performance, years),
            records.monthly_totals,
            year=selected,
            through_month=through,
        )
    except SQLAlchemyError:
        raise _database_unavailable() from None


@router.get("/experience", response_model=TrirExperienceResponse, responses=RESPONSES)
def experience(
    principal: Viewer, session: SessionDep, year: Year = None, through: Through = None
) -> TrirExperienceResponse:
    """LCY TRIR for ``year`` (default: this year) through ``through`` (default: the
    latest month complete from January), with history, benchmark and data quality."""
    return _experience(session, year, through)


@router.get("/current", response_model=CalculationOut, responses=RESPONSES)
def current(
    principal: Viewer, session: SessionDep, year: Year = None, through: Through = None
) -> CalculationOut:
    return _experience(session, year, through).current


@router.get("/calculation", response_model=dict[str, CalculationOut], responses=RESPONSES)
def calculation(
    principal: Viewer, session: SessionDep, year: Year = None, through: Through = None
) -> dict[str, CalculationOut]:
    """Calculation detail for the year-to-date and rolling 12-month TRIR."""
    result = _experience(session, year, through)
    return {"ytd": result.current, "rolling12": result.rolling12}


@router.get("/history", response_model=list[HistoryRowOut], responses=RESPONSES)
def history(
    principal: Viewer, session: SessionDep, year: Year = None, through: Through = None
) -> list[HistoryRowOut]:
    return _experience(session, year, through).history


@router.get("/monthly", response_model=list[MonthDetailOut], responses=RESPONSES)
def monthly(principal: Viewer, session: SessionDep, year: Year = None) -> list[MonthDetailOut]:
    return _experience(session, year, None).monthly


@router.get("/benchmarks", response_model=list[BenchmarkOut], responses=RESPONSES)
def benchmarks(principal: Viewer, session: SessionDep) -> list[BenchmarkOut]:
    return _experience(session, None, None).benchmarks


@router.get("/status", response_model=TrirStatusOut, responses=RESPONSES)
def trir_status(
    principal: Viewer, session: SessionDep, year: Year = None, through: Through = None
) -> TrirStatusOut:
    return _experience(session, year, through).status


@router.get("/reconciliation", response_model=list[DataQualityItemOut], responses=RESPONSES)
def reconciliation(
    principal: Viewer, session: SessionDep, year: Year = None, through: Through = None
) -> list[DataQualityItemOut]:
    """Recalculated against legacy figures, live against the legacy snapshot, and
    Safety Performance annual rows against the TRIR history. Warnings only."""
    return _experience(session, year, through).data_quality


@router.get("/methodology", response_model=MethodologyOut, responses=RESPONSES)
def methodology(principal: Viewer) -> MethodologyOut:
    return service.METHODOLOGY
