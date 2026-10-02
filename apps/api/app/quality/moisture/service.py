import math
from collections.abc import Iterable, Sequence

from app.quality.moisture.schemas import (
    DateRange,
    MoistureFilterParams,
    MoistureRecord,
    MoistureSummary,
)


def _matches(record: MoistureRecord, filters: MoistureFilterParams) -> bool:
    # Product and location match exactly; source values are not normalized.
    if filters.product is not None and record.product != filters.product:
        return False
    if filters.location is not None and record.location != filters.location:
        return False
    if filters.start_date is not None and record.date < filters.start_date:
        return False
    if filters.end_date is not None and record.date > filters.end_date:
        return False
    if filters.search is not None:
        term = filters.search.casefold()
        identifiers = (record.lot, record.campaign_no)
        if not any(value is not None and term in value.casefold() for value in identifiers):
            return False
    return True


def filter_records(
    records: Iterable[MoistureRecord], filters: MoistureFilterParams
) -> list[MoistureRecord]:
    """Matching records in chronological order. Same-day records keep source order."""
    matching = [record for record in records if _matches(record, filters)]
    matching.sort(key=lambda record: record.date)
    return matching


def newest_first(records: Sequence[MoistureRecord], limit: int) -> list[MoistureRecord]:
    return list(reversed(records))[:limit]


def _mean(values: Iterable[float | None]) -> tuple[float | None, int]:
    present = [value for value in values if value is not None]
    if not present:
        return None, 0
    return math.fsum(present) / len(present), len(present)


def summarize(records: Sequence[MoistureRecord]) -> MoistureSummary:
    avg_moisture, moisture_count = _mean(record.avg_moisture for record in records)
    avg_color, color_count = _mean(record.avg_color for record in records)
    avg_bd, bd_count = _mean(record.avg_combined_bd for record in records)
    return MoistureSummary(
        record_count=len(records),
        avg_moisture=avg_moisture,
        avg_color=avg_color,
        avg_combined_bd=avg_bd,
        moisture_value_count=moisture_count,
        color_value_count=color_count,
        combined_bd_value_count=bd_count,
    )


def distinct_values(values: Iterable[str | None]) -> list[str]:
    return sorted({value for value in values if value is not None})


def date_range(records: Sequence[MoistureRecord]) -> DateRange:
    if not records:
        return DateRange(min=None, max=None)
    dates = [record.date for record in records]
    return DateRange(min=min(dates), max=max(dates))
