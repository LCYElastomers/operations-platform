from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.quality.moisture import service
from app.quality.moisture.repository import MoistureRepository, get_moisture_repository
from app.quality.moisture.schemas import (
    MoistureFilterParams,
    MoistureFiltersResponse,
    MoistureLotsResponse,
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
    """Newest matching location-level records first."""
    records, total = repository.recent(params, params.limit)
    return RecentMoistureResponse(
        data_source=repository.data_source,
        total_matching=total,
        limit=params.limit,
        records=records,
    )


@router.get("/lots", response_model=MoistureLotsResponse)
def moisture_lots(
    params: Annotated[RecentMoistureParams, Query()],
    repository: Repository,
) -> MoistureLotsResponse:
    """Most recently measured Product + Lot master rows first, with their location records."""
    lots, total = service.newest_lots(repository.matching(params), params.limit)
    return MoistureLotsResponse(
        data_source=repository.data_source,
        total_matching=total,
        limit=params.limit,
        lots=lots,
    )


@router.get("/trends", response_model=MoistureTrendsResponse)
def moisture_trends(
    params: Annotated[MoistureFilterParams, Query()],
    repository: Repository,
) -> MoistureTrendsResponse:
    """Matching Product + Lot master rows oldest first, with summary statistics."""
    matching = repository.matching(params)
    lots = service.group_lots(matching)
    return MoistureTrendsResponse(
        data_source=repository.data_source,
        summary=service.summarize(matching, lot_count=len(lots)),
        lots=lots,
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
