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
- Breakdowns (area, near-miss potential and cause, LOPC contributing factor,
  injury cause, body part) are supporting dimensions. The Incident, Near
  Miss and LOPC totals stay authoritative; a breakdown is only compared with
  them (``MonthReconciliationOut``), never used to replace or fill them, and a
  blank breakdown cell is never treated as zero. Potential, cause, injury
  cause and body part are tags and may total more than the events.
- The prior year covers the same months. Incidents are read from the
  ``incidents`` set; LOPC from the set Safety Performance reads for that year
  (``count_source``: ``performance_legacy`` before 2026), so it is never stored
  twice.
- Behavior is recorded as annual tag counts (``app.safety.behavior``), so the
  through month does not apply to it. Its denominator is the stored Incident
  total for the whole year; tags may outnumber incidents and are never
  reconciled with them.
"""

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.safety.behavior.repository import BehaviorCategoryDefinition, BehaviorRepository
from app.safety.behavior.service import build_pareto
from app.safety.performance.calculations import count_source
from app.safety.repository import SafetyMetricsRepository, SectionDefinition, StoredValues
from app.safety.schemas import (
    AnalyticsBreakdownOut,
    AnalyticsCategoryOut,
    AnalyticsCumulativeOut,
    AnalyticsKpiKey,
    AnalyticsKpiOut,
    AnalyticsKpiPartOut,
    AnalyticsPriorYearOut,
    AnalyticsSeriesOut,
    AreaReconciliationOut,
    IncidentAnalyticsResponse,
    InjuryReconciliationOut,
    LopcFactorsOut,
    MonthReconciliationOut,
    ReconciliationStatus,
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
FIRST_AID = (CLASSIFICATION, "first_aid")
RECORDABLE_INJURY = (CLASSIFICATION, "recordable_injury")

INCIDENTS_BY_AREA = "incidents_by_area"
NEAR_MISSES_BY_AREA = "near_misses_by_area"
NEAR_MISS_POTENTIAL = "near_miss_potential"
NEAR_MISS_CAUSE = "near_miss_cause"
LOPC_FACTOR = "lopc_contributing_factor"
INJURY_CAUSE = "injury_cause"
BODY_PART = "body_part"


@dataclass(frozen=True)
class PriorYearValues:
    """Prior-year monthly values, January..through month; empty when not loaded."""

    incidents: Sequence[int | None] = ()
    lopc: Sequence[int | None] = ()


NO_PRIOR_YEAR = PriorYearValues()


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
    key: AnalyticsKpiKey,
    series: AnalyticsSeriesOut,
    through_month: int | None,
    parts: Sequence[AnalyticsSeriesOut] = (),
    prior: AnalyticsSeriesOut | None = None,
    prior_year: int | None = None,
) -> AnalyticsKpiOut:
    prior_out = None
    if prior is not None and prior_year is not None and prior.months_reported > 0:
        prior_out = AnalyticsPriorYearOut(
            year=prior_year,
            value=prior.total,
            months_reported=prior.months_reported,
            complete=prior.complete,
            delta=(
                series.total - prior.total
                if series.total is not None and prior.total is not None
                else None
            ),
        )
    return AnalyticsKpiOut(
        key=key,
        value=series.total,
        months_reported=series.months_reported,
        through_month=through_month,
        complete=series.complete,
        parts=[
            AnalyticsKpiPartOut(
                code=part.code, name=part.name, value=part.total, complete=part.complete
            )
            for part in parts
        ],
        prior_year=prior_out,
    )


def reconcile(
    dimension: Sequence[int | None], authoritative: Sequence[int | None]
) -> list[MonthReconciliationOut]:
    """Compare a breakdown's monthly sums with an authoritative monthly total."""
    months = []
    for month, (part, whole) in enumerate(zip(dimension, authoritative, strict=True), start=1):
        status: ReconciliationStatus
        if whole is None:
            status = "no_authoritative_total"
        elif part is None:
            status = "no_dimension_data"
        elif part == whole:
            status = "reconciled"
        elif part < whole:
            status = "below_total"
        else:
            status = "above_total"
        months.append(
            MonthReconciliationOut(
                month=month,
                dimension_total=part,
                authoritative_total=whole,
                difference=part - whole if part is not None and whole is not None else None,
                status=status,
            )
        )
    return months


def cumulative(values: Sequence[int | None]) -> list[int | None]:
    """Running total of reported values: carried through unreported months, null before
    the first reported month."""
    running: int | None = None
    out: list[int | None] = []
    for value in values:
        if value is not None:
            running = (running or 0) + value
        out.append(running)
    return out


def _breakdown(
    section_code: str,
    sections: Sequence[SectionDefinition],
    stored: StoredValues,
    months: range,
    *,
    is_tag: bool,
) -> AnalyticsBreakdownOut:
    section = next((s for s in sections if s.code == section_code), None)
    rows = []
    for category in section.categories if section else ():
        values = [stored.get((category.id, m)) for m in months]
        rows.append(
            AnalyticsCategoryOut(
                code=category.code,
                name=category.name,
                description=category.description,
                area_kind=category.area_kind,
                values=values,
                total=total(values),
                months_reported=sum(1 for value in values if value is not None),
            )
        )
    # Highest total first, unreported last; display order breaks ties.
    ranked = sorted(
        enumerate(rows),
        key=lambda item: (item[1].total is None, -(item[1].total or 0), item[0]),
    )
    monthly_totals = [total(row.values[index] for row in rows) for index in range(len(months))]
    return AnalyticsBreakdownOut(
        section=section_code,
        name=section.name if section else section_code,
        is_tag=is_tag,
        categories=[row for _, row in ranked],
        rows=rows,
        monthly_totals=monthly_totals,
        total=total(monthly_totals),
    )


def _reported_only(breakdown: AnalyticsBreakdownOut) -> list[AnalyticsCategoryOut]:
    return [row for row in breakdown.categories if row.total is not None]


def build_analytics(
    *,
    year: int,
    through_month: int | None,
    latest_month: int | None,
    sections: Sequence[SectionDefinition],
    stored: StoredValues,
    years: list[int],
    prior: PriorYearValues = NO_PRIOR_YEAR,
    behavior_categories: Sequence[BehaviorCategoryDefinition] = (),
    behavior_counts: Mapping[int, int] | None = None,
) -> IncidentAnalyticsResponse:
    """Analytics for ``year``, January..``through_month`` (no months when None).
    Behavior covers the whole year."""
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
    combined_damage = _combined("Combined Damage", property_damage, equipment_damage)
    incidents, near_misses, lopc, psif, pit = (
        series(INCIDENTS),
        series(NEAR_MISSES),
        series(LOPC),
        series(PSIF),
        series(PIT),
    )

    def padded(values: Sequence[int | None]) -> list[int | None]:
        return [values[m - 1] if m <= len(values) else None for m in months]

    prior_year = year - 1
    prior_incidents = _series(INCIDENTS[0], INCIDENTS[1], incidents.name, padded(prior.incidents))
    prior_lopc = _series(LOPC[0], LOPC[1], lopc.name, padded(prior.lopc))

    incident_areas = _breakdown(INCIDENTS_BY_AREA, sections, stored, months, is_tag=False)
    near_miss_areas = _breakdown(NEAR_MISSES_BY_AREA, sections, stored, months, is_tag=False)
    factors = _breakdown(LOPC_FACTOR, sections, stored, months, is_tag=False)
    injury_cause = _breakdown(INJURY_CAUSE, sections, stored, months, is_tag=True)
    body_part = _breakdown(BODY_PART, sections, stored, months, is_tag=True)
    injuries = [
        total(pair)
        for pair in zip(series(FIRST_AID).values, series(RECORDABLE_INJURY).values, strict=True)
    ]
    incident_category = definitions.get(INCIDENTS)
    incident_year = [
        stored.get((incident_category.id, m)) if incident_category else None for m in range(1, 13)
    ]

    return IncidentAnalyticsResponse(
        year=year,
        through_month=through_month,
        latest_month=latest_month,
        available_years=years,
        kpis=[
            _kpi(
                "incidents", incidents, through_month, prior=prior_incidents, prior_year=prior_year
            ),
            _kpi("near_misses", near_misses, through_month),
            _kpi("lopc", lopc, through_month, prior=prior_lopc, prior_year=prior_year),
            _kpi("psif", psif, through_month),
            _kpi("pit", pit, through_month),
            _kpi(
                "combined_damage",
                combined_damage,
                through_month,
                parts=(property_damage, equipment_damage),
            ),
        ],
        incidents=incidents,
        near_misses=near_misses,
        classifications=[series(key) for key in classification_keys] + [psif],
        lopc=lopc,
        psif=psif,
        pit=pit,
        property_damage=property_damage,
        equipment_damage=equipment_damage,
        combined_damage=combined_damage,
        incidents_by_area=_reported_only(incident_areas),
        near_misses_by_area=_reported_only(near_miss_areas),
        incident_area_monthly=incident_areas.rows,
        near_miss_area_monthly=near_miss_areas.rows,
        area_reconciliation=AreaReconciliationOut(
            incidents=reconcile(incident_areas.monthly_totals, incidents.values),
            near_misses=reconcile(near_miss_areas.monthly_totals, near_misses.values),
        ),
        prior_year=prior_year,
        incidents_prior_year_monthly=prior_incidents,
        incidents_prior_year_available=prior_incidents.months_reported > 0,
        lopc_prior_year_monthly=prior_lopc,
        lopc_prior_year_available=prior_lopc.months_reported > 0,
        lopc_contributing_factors=LopcFactorsOut(
            breakdown=factors,
            cumulative=[
                AnalyticsCumulativeOut(code=row.code, name=row.name, values=cumulative(row.values))
                for row in factors.rows
            ],
            cumulative_total=cumulative(factors.monthly_totals),
        ),
        lopc_factor_reconciliation=reconcile(factors.monthly_totals, lopc.values),
        near_miss_potential=_breakdown(NEAR_MISS_POTENTIAL, sections, stored, months, is_tag=True),
        near_miss_cause=_breakdown(NEAR_MISS_CAUSE, sections, stored, months, is_tag=True),
        injury_cause=injury_cause,
        body_part=body_part,
        injury_reconciliation=InjuryReconciliationOut(
            injuries=injuries,
            injury_cause=reconcile(injury_cause.monthly_totals, injuries),
            body_part=reconcile(body_part.monthly_totals, injuries),
        ),
        behavior=build_pareto(
            year=year,
            categories=behavior_categories,
            counts=behavior_counts or {},
            incident_months=incident_year,
        ),
    )


def _prior_year_values(
    repository: SafetyMetricsRepository,
    sections: Sequence[SectionDefinition],
    prior_year: int,
    through_month: int | None,
) -> PriorYearValues:
    if through_month is None:
        return PriorYearValues()
    months = range(1, through_month + 1)

    def values(
        source_sections: Sequence[SectionDefinition], key: tuple[str, str]
    ) -> list[int | None]:
        category = next(
            (
                c
                for s in source_sections
                if s.code == key[0]
                for c in s.categories
                if c.code == key[1]
            ),
            None,
        )
        if category is None:
            return [None for _ in months]
        stored = repository.values([category.id], prior_year)
        return [stored.get((category.id, m)) for m in months]

    lopc_set = count_source(prior_year)
    lopc_sections = sections if lopc_set == METRIC_SET else repository.sections(lopc_set)
    return PriorYearValues(incidents=values(sections, INCIDENTS), lopc=values(lopc_sections, LOPC))


def load_analytics(
    repository: SafetyMetricsRepository,
    *,
    year: int,
    through_month: int | None,
    now: dt.datetime,
    behavior: BehaviorRepository | None = None,
) -> IncidentAnalyticsResponse:
    """Analytics through ``through_month``, or by default through the latest month of
    the year that has started in Baytown. Reads only; nothing is written or audited."""
    today = site_today(now)
    latest = latest_started_month(year, today)
    if through_month is not None and (latest is None or through_month > latest):
        raise MonthNotStartedError(latest)
    through = through_month if through_month is not None else latest
    sections = repository.sections(METRIC_SET)
    ids = category_ids(sections)
    return build_analytics(
        year=year,
        through_month=through,
        latest_month=latest,
        sections=sections,
        stored=repository.values(ids, year),
        years=available_years(today, repository.years_with_values(ids)),
        prior=_prior_year_values(repository, sections, year - 1, through),
        behavior_categories=behavior.categories() if behavior else (),
        behavior_counts=behavior.counts(year) if behavior else None,
    )
