from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.quality.moisture import service
from app.quality.moisture.schemas import (
    DataSourceInfo,
    MoistureFilterParams,
    MoistureFiltersResponse,
    MoistureRecord,
    MoistureTrendsResponse,
    RecentMoistureParams,
    RecentMoistureResponse,
)
from app.quality.moisture.source import get_moisture_data_source, get_moisture_records

router = APIRouter(prefix="/quality/moisture", tags=["quality: moisture"])

Records = Annotated[tuple[MoistureRecord, ...], Depends(get_moisture_records)]
DataSource = Annotated[DataSourceInfo, Depends(get_moisture_data_source)]


@router.get("/recent", response_model=RecentMoistureResponse)
def recent_moisture(
    params: Annotated[RecentMoistureParams, Query()],
    records: Records,
    data_source: DataSource,
) -> RecentMoistureResponse:
    """Newest matching records first."""
    matching = service.filter_records(records, params)
    return RecentMoistureResponse(
        data_source=data_source,
        total_matching=len(matching),
        limit=params.limit,
        records=service.newest_first(matching, params.limit),
    )


@router.get("/trends", response_model=MoistureTrendsResponse)
def moisture_trends(
    params: Annotated[MoistureFilterParams, Query()],
    records: Records,
    data_source: DataSource,
) -> MoistureTrendsResponse:
    """Matching records oldest first, with summary statistics."""
    matching = service.filter_records(records, params)
    return MoistureTrendsResponse(
        data_source=data_source,
        summary=service.summarize(matching),
        points=matching,
    )


@router.get("/filters", response_model=MoistureFiltersResponse)
def moisture_filters(records: Records, data_source: DataSource) -> MoistureFiltersResponse:
    """Distinct source products and locations, and the source date boundaries."""
    return MoistureFiltersResponse(
        data_source=data_source,
        products=service.distinct_values(record.product for record in records),
        locations=service.distinct_values(record.location for record in records),
        date_range=service.date_range(records),
    )
