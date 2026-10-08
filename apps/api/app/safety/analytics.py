"""Incident & Near Miss Analytics: read-only counts from the stored monthly values.

Everything is calculated from the ``incidents`` metric set on each request;
nothing is stored. Rules:

- A month with no stored value is unreported (null), never zero. A total is
  the sum of the reported months January..through, or null when none are
  reported, and is complete only when every one of those months is reported.
- Months are Baytown site calendar months: a month that has not started is
  never requested or returned.
- Incident Classification categories are not mutually exclusive. They are
  never summed together or compared with Incident.
- LOPC is the ``lopc`` series. The ``spill_release`` classification records
  the same events; the two are never added together.
- PIT is the ``pit_accident`` classification (canonical). The ``pit`` section
  holds the same counts and is not read, so PIT is never counted twice.
- Damage is the ``property_damage`` and ``equipment_damage_failure``
  classifications. Combined damage is their sum, a count of classifications
  rather than of distinct events. The ``property_equipment_damage`` section is
  not read.
- PSIF is shown as recorded; it is not defined, weighted or rated here.
"""

import datetime as dt
from collections.abc import Sequence

from app.safety.repository import SafetyMetricsRepository, SectionDefinition, StoredValues
from app.safety.schemas import (
    AnalyticsKpiKey,
    AnalyticsKpiOut,
    AnalyticsSeriesOut,
    IncidentAnalyticsResponse,
)
from app.safety.service import category_ids, total
from app.safety.site_calendar import site_today

METRIC_SET = "incidents"
# Incident & Near Miss is recorded on the platform from 2026.
FIRST_ANALYTICS_YEAR = 2026

CLASSIFICATION = "incident_classification"
# (section code, category code)
INCIDENTS = ("incident_near_miss_totals", "incident")
NEAR_MISSES = ("incident_near_miss_totals", "near_miss")
LOPC = ("lopc", "lopc")
PSIF = ("psif", "psif")
PIT = (CLASSIFICATION, "pit_accident")
PROPERTY_DAMAGE = (CLASSIFICATION, "property_damage")
EQUIPMENT_DAMAGE = (CLASSIFICATION, "equipment_damage_failure")
COMBINED_DAMAGE_CODE = "property_damage+equipment_damage_failure"


class MonthNotStartedError(ValueError):
    """The requested through month has not started on the site calendar."""

    def __init__(self, latest_month: int | None) -> None:
        super().__init__("month not started")
        self.latest_month = latest_month


def latest_started_month(year: int, today: dt.date) -> int | None:
    """The latest month of ``year`` that has started in Baytown; None for a future year."""
    if year < today.year:
        return 12
    if year == today.year:
        return today.month
    return None


def available_years(today: dt.date, years_with_data: Sequence[int]) -> list[int]:
    """Newest first: every year from 2026 to the current site year, and any later year
    that already has values."""
    years = set(range(FIRST_ANALYTICS_YEAR, today.year + 1))
    years.update(year for year in years_with_data if year >= FIRST_ANALYTICS_YEAR)
    return sorted(years, reverse=True)


def _series(section: str, code: str, name: str, values: list[int | None]) -> AnalyticsSeriesOut:
    unreported = [month for month, value in enumerate(values, start=1) if value is None]
    return AnalyticsSeriesOut(
        section=section,
        code=code,
        name=name,
        values=values,
        total=total(values),
        months_reported=len(values) - len(unreported),
        unreported_months=unreported,
        complete=bool(values) and not unreported,
    )


def _combined(name: str, *parts: AnalyticsSeriesOut) -> AnalyticsSeriesOut:
    """Month by month sum of the parts; null only when no part is reported. A month
    counts as reported only when every part is."""
    values = [total(month_values) for month_values in zip(*(p.values for p in parts), strict=True)]
    unreported = sorted({month for part in parts for month in part.unreported_months})
    return AnalyticsSeriesOut(
        section=CLASSIFICATION,
        code=COMBINED_DAMAGE_CODE,
        name=name,
        values=values,
        total=total(values),
        months_reported=len(values) - len(unreported),
        unreported_months=unreported,
        complete=bool(values) and not unreported,
    )


def _kpi(
    key: AnalyticsKpiKey, series: AnalyticsSeriesOut, through_month: int | None
) -> AnalyticsKpiOut:
    return AnalyticsKpiOut(
        key=key,
        value=series.total,
        months_reported=series.months_reported,
        through_month=through_month,
        complete=series.complete,
    )


def build_analytics(
    *,
    year: int,
    through_month: int | None,
    latest_month: int | None,
    sections: Sequence[SectionDefinition],
    stored: StoredValues,
    years: list[int],
) -> IncidentAnalyticsResponse:
    """Analytics for ``year``, January..``through_month`` (no months when None)."""
    months = range(1, through_month + 1) if through_month is not None else range(0)
    definitions = {
        (section.code, category.code): category
        for section in sections
        for category in section.categories
    }

    def series(key: tuple[str, str]) -> AnalyticsSeriesOut:
        category = definitions.get(key)
        values = [stored.get((category.id, m)) if category else None for m in months]
        return _series(key[0], key[1], category.name if category else key[1], values)

    classification_keys = [
        (section.code, category.code)
        for section in sections
        if section.code == CLASSIFICATION
        for category in section.categories
    ]
    property_damage = series(PROPERTY_DAMAGE)
    equipment_damage = series(EQUIPMENT_DAMAGE)
    incidents, near_misses, lopc, psif = (
        series(INCIDENTS),
        series(NEAR_MISSES),
        series(LOPC),
        series(PSIF),
    )
    return IncidentAnalyticsResponse(
        year=year,
        through_month=through_month,
        latest_month=latest_month,
        available_years=years,
        kpis=[
            _kpi("incidents", incidents, through_month),
            _kpi("near_misses", near_misses, through_month),
            _kpi("lopc", lopc, through_month),
            _kpi("psif", psif, through_month),
        ],
        incidents=incidents,
        near_misses=near_misses,
        classifications=[series(key) for key in classification_keys] + [psif],
        lopc=lopc,
        psif=psif,
        pit=series(PIT),
        property_damage=property_damage,
        equipment_damage=equipment_damage,
        combined_damage=_combined("Combined Damage", property_damage, equipment_damage),
    )


def load_analytics(
    repository: SafetyMetricsRepository,
    *,
    year: int,
    through_month: int | None,
    now: dt.datetime,
) -> IncidentAnalyticsResponse:
    """Analytics through ``through_month``, or by default through the latest month of
    the year that has started in Baytown. Reads only; nothing is written or audited."""
    today = site_today(now)
    latest = latest_started_month(year, today)
    if through_month is not None and (latest is None or through_month > latest):
        raise MonthNotStartedError(latest)
    sections = repository.sections(METRIC_SET)
    ids = category_ids(sections)
    return build_analytics(
        year=year,
        through_month=through_month if through_month is not None else latest,
        latest_month=latest,
        sections=sections,
        stored=repository.values(ids, year),
        years=available_years(today, repository.years_with_values(ids)),
    )
