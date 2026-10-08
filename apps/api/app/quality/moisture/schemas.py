import datetime as dt
from typing import Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.core.schemas import CamelModel


class MoistureRecord(CamelModel):
    """One row of the moisture source query, with application-friendly names.

    Identifiers (campaign number, lot, product) are strings and never used for
    arithmetic. Measurements are passed through at source precision; ``None``
    means the source value was missing and is distinct from ``0``.
    """

    date: dt.date
    campaign_no: str | None
    lot: str | None
    location: str | None
    product: str | None
    avg_moisture: float | None
    avg_color: float | None
    avg_combined_bd: float | None

    @field_validator("campaign_no", "lot", "product", mode="before")
    @classmethod
    def _identifier_as_text(cls, value: object) -> object:
        # Access may type identifiers as numbers; keep them as their exact text.
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        return value


class DataSourceInfo(CamelModel):
    kind: Literal["development-fixture", "database"]
    is_fixture: bool
    label: str


class MoistureFilterParams(CamelModel):
    """Query parameters shared by the moisture endpoints."""

    model_config = ConfigDict(extra="forbid")

    product: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, min_length=1, max_length=200)
    search: str | None = Field(
        default=None,
        max_length=100,
        description="Case-insensitive substring match against lot or campaign number.",
    )
    start_date: dt.date | None = None
    end_date: dt.date | None = None

    @field_validator("search")
    @classmethod
    def _blank_search_is_unset(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def _date_range_is_ordered(self) -> Self:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("startDate must be on or before endDate")
        return self


class RecentMoistureParams(MoistureFilterParams):
    limit: int = Field(default=50, ge=1, le=500)


class RecentMoistureResponse(CamelModel):
    data_source: DataSourceInfo
    total_matching: int
    limit: int
    records: list[MoistureRecord]


class MoistureLot(CamelModel):
    """One Product + Lot master row, aggregated across every matching location record.

    Location is not part of the key. Means are unweighted over the non-null
    values of the underlying location records (the finest grain the source
    provides) and are null when no values exist. A record without a lot cannot
    be attributed to a lot, so it forms its own master row instead of being
    merged with other lot-less records.
    """

    product: str | None
    lot: str | None
    first_date: dt.date
    last_date: dt.date
    campaign_nos: list[str] = Field(description="Distinct non-null campaign numbers, sorted.")
    locations: list[str] = Field(description="Distinct non-null locations, sorted.")
    record_count: int = Field(description="Location-level records in this lot.")
    avg_moisture: float | None
    avg_color: float | None
    avg_combined_bd: float | None
    moisture_value_count: int
    color_value_count: int
    combined_bd_value_count: int


class MoistureLotDetail(MoistureLot):
    records: list[MoistureRecord] = Field(description="Location-level records, oldest first.")


class MoistureLotsResponse(CamelModel):
    data_source: DataSourceInfo
    total_matching: int = Field(description="Matching Product + Lot master rows.")
    limit: int
    lots: list[MoistureLotDetail] = Field(description="Most recently measured lots first.")


class MoistureSummary(CamelModel):
    """Unweighted means of non-null location-level values. A mean is null when no values exist."""

    lot_count: int = Field(description="Product + Lot master rows.")
    record_count: int = Field(description="Location-level records.")
    avg_moisture: float | None
    avg_color: float | None
    avg_combined_bd: float | None
    moisture_value_count: int
    color_value_count: int
    combined_bd_value_count: int


class MoistureTrendsResponse(CamelModel):
    data_source: DataSourceInfo
    summary: MoistureSummary
    lots: list[MoistureLot] = Field(
        description="Matching lots by latest measurement date, oldest first."
    )


class DateRange(CamelModel):
    min: dt.date | None
    max: dt.date | None


class MoistureFiltersResponse(CamelModel):
    data_source: DataSourceInfo
    products: list[str]
    locations: list[str]
    date_range: DateRange
