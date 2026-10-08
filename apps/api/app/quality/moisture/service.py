import math
from collections.abc import Hashable, Iterable, Sequence

from app.quality.moisture.schemas import (
    DateRange,
    MoistureFilterParams,
    MoistureLot,
    MoistureLotDetail,
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


def summarize(records: Sequence[MoistureRecord], lot_count: int) -> MoistureSummary:
    avg_moisture, moisture_count = _mean(record.avg_moisture for record in records)
    avg_color, color_count = _mean(record.avg_color for record in records)
    avg_bd, bd_count = _mean(record.avg_combined_bd for record in records)
    return MoistureSummary(
        lot_count=lot_count,
        record_count=len(records),
        avg_moisture=avg_moisture,
        avg_color=avg_color,
        avg_combined_bd=avg_bd,
        moisture_value_count=moisture_count,
        color_value_count=color_count,
        combined_bd_value_count=bd_count,
    )


def _lot(records: Sequence[MoistureRecord]) -> MoistureLot:
    avg_moisture, moisture_count = _mean(record.avg_moisture for record in records)
    avg_color, color_count = _mean(record.avg_color for record in records)
    avg_bd, bd_count = _mean(record.avg_combined_bd for record in records)
    return MoistureLot(
        product=records[0].product,
        lot=records[0].lot,
        first_date=records[0].date,
        last_date=records[-1].date,
        campaign_nos=distinct_values(record.campaign_no for record in records),
        locations=distinct_values(record.location for record in records),
        record_count=len(records),
        avg_moisture=avg_moisture,
        avg_color=avg_color,
        avg_combined_bd=avg_bd,
        moisture_value_count=moisture_count,
        color_value_count=color_count,
        combined_bd_value_count=bd_count,
    )


def _lot_groups(records: Sequence[MoistureRecord]) -> list[list[MoistureRecord]]:
    """Records grouped by Product + Lot, by latest measurement, oldest first.

    Location is not part of the key. Lots last measured on the same day keep
    the source order of their latest record.
    """
    groups: dict[Hashable, list[MoistureRecord]] = {}
    last_index: dict[Hashable, int] = {}
    for index, record in enumerate(records):
        # Lot-less records are never merged: nothing shows they belong together.
        key = (record.product, record.lot) if record.lot is not None else ("no-lot", index)
        groups.setdefault(key, []).append(record)
        last_index[key] = index
    ordered = sorted(groups, key=lambda key: last_index[key])
    return [groups[key] for key in ordered]


def group_lots(records: Sequence[MoistureRecord]) -> list[MoistureLot]:
    """Product + Lot master rows from chronological records, oldest first."""
    return [_lot(group) for group in _lot_groups(records)]


def newest_lots(
    records: Sequence[MoistureRecord], limit: int
) -> tuple[list[MoistureLotDetail], int]:
    """Most recently measured lots first, with their location records, and the lot total."""
    groups = _lot_groups(records)
    newest = list(reversed(groups))[:limit]
    details = [
        MoistureLotDetail(**_lot(group).model_dump(), records=list(group)) for group in newest
    ]
    return details, len(groups)


def distinct_values(values: Iterable[str | None]) -> list[str]:
    return sorted({value for value in values if value is not None})


def date_range(records: Sequence[MoistureRecord]) -> DateRange:
    if not records:
        return DateRange(min=None, max=None)
    dates = [record.date for record in records]
    return DateRange(min=min(dates), max=max(dates))
