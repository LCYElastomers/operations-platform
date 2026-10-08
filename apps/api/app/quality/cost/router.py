"""Cost of Quality endpoints (read-only; ``quality.cost.view``).

``/summary`` returns the Cost of Poor Quality and Cost of Quality Matrix
figures for a period; ``/estimator`` and ``/estimate`` are the incident cost
estimator, which stores nothing.
"""

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.authorization import UserPrincipal, require_permission
from app.core.permissions import Permission
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.quality.cost import estimator, service
from app.quality.cost.models import MAX_REPORTING_YEAR, MIN_REPORTING_YEAR
from app.quality.cost.repository import CostRepository
from app.quality.cost.schemas import (
    CostSummaryResponse,
    EstimateRequest,
    EstimateResponse,
    EstimatorReferenceResponse,
)

router = APIRouter(prefix="/quality/cost", tags=["quality"])


def _database_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error": "database_unavailable",
            "message": "Cost of Quality data is unavailable because the database could not be "
            "reached.",
        },
    )


def cost_session() -> Iterator[Session]:
    try:
        sessions = get_sessionmaker()
    except DatabaseNotConfiguredError:
        raise _database_unavailable() from None
    with sessions() as session:
        yield session


SessionDep = Annotated[Session, Depends(cost_session)]
Viewer = Annotated[UserPrincipal, Depends(require_permission(Permission.QUALITY_COST_VIEW))]
Year = Annotated[int | None, Query(ge=MIN_REPORTING_YEAR, le=MAX_REPORTING_YEAR)]
Month = Annotated[int | None, Query(ge=1, le=12)]

RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not signed in"},
    403: {"description": "Missing quality.cost.view"},
}


@router.get(
    "/summary",
    response_model=CostSummaryResponse,
    responses={**RESPONSES, 503: {"description": "Database unavailable"}},
)
def summary(
    principal: Viewer,
    session: SessionDep,
    year: Year = None,
    from_month: Annotated[int | None, Query(alias="from", ge=1, le=12)] = None,
    through: Month = None,
) -> CostSummaryResponse:
    """Months of ``year`` (default: the latest year with figures) and the totals for
    ``from`` (default January) through ``through`` (default the latest reported month)."""
    try:
        stored = [
            service.MonthInputs.from_row(row) for row in CostRepository(session).facts().values()
        ]
    except SQLAlchemyError:
        raise _database_unavailable() from None
    return service.summary(stored, year=year, from_month=from_month, through_month=through)


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
