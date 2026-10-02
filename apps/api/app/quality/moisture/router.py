from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.quality.moisture import service
from app.quality.moisture.repository import MoistureRepository, get_moisture_repository
from app.quality.moisture.schemas import (
    MoistureFilterParams,
    MoistureFiltersResponse,
    MoistureTrendsResponse,
    RecentMoistureParams,
    RecentMoistureResponse,
)

router = APIRouter(prefix="/quality/moisture", tags=["quality: moisture"])

Repository = Annotated[MoistureRepository, Depends(get_moisture_repository)]


@router.get("/recent", response_model=RecentMoistureResponse)
def recent_moisture(
    params: Annotated[RecentMoistureParams, Query()],
    repository: Repository,
) -> RecentMoistureResponse:
    """Newest matching records first."""
    records, total = repository.recent(params, params.limit)
    return RecentMoistureResponse(
        data_source=repository.data_source,
        total_matching=total,
        limit=params.limit,
        records=records,
    )


@router.get("/trends", response_model=MoistureTrendsResponse)
def moisture_trends(
    params: Annotated[MoistureFilterParams, Query()],
    repository: Repository,
) -> MoistureTrendsResponse:
    """Matching records oldest first, with summary statistics."""
    matching = repository.matching(params)
    return MoistureTrendsResponse(
        data_source=repository.data_source,
        summary=service.summarize(matching),
        points=matching,
    )


@router.get("/filters", response_model=MoistureFiltersResponse)
def moisture_filters(repository: Repository) -> MoistureFiltersResponse:
    """Distinct source products and locations, and the source date boundaries."""
    options = repository.filter_options()
    return MoistureFiltersResponse(
        data_source=repository.data_source,
        products=options.products,
        locations=options.locations,
        date_range=options.date_range,
    )
