"""TRIR Experience: LCY's Total Recordable Incident Rate against the industry benchmark.

    TRIR = recordable cases × 200,000 ÷ worked hours      (app.safety.rates)

Sources, each read from its owner and never copied:

- Hours: Safety Performance monthly ``total_hours`` ("Monthly Hours Worked
  (Total)", hourly + salary), through ``performance.service.trir_inputs``.
- Recordables: the TRIR numerator Safety Performance uses, i.e. Incident &
  Near Miss recordable injuries + occupational illnesses (from 2026), or the
  pre-platform workbook recordable counts (before 2026).
- Benchmark and history: ``safety.trir_annual_facts`` (reviewed import).

A year with monthly hours in Safety Performance is calculated live, January
through the cutoff month; every month in the window must be closed with hours
above zero and confirmed counts, otherwise the rate is unavailable and the
blocking months are listed (an unreported month is never zero). A year without
monthly hours uses its imported annual recordables and man-hours.
"""

import datetime as dt
from collections.abc import Callable, Mapping
from decimal import Decimal

from app.safety.performance.calculations import (
    FIRST_INCIDENT_YEAR,
    Measure,
    MonthCounts,
    MonthHours,
    Period,
    WindowResult,
    ineligible_reason,
    latest_ytd_month,
    rolling_window,
    window_rate,
    ytd_window,
)
from app.safety.performance.service import TrirInputs
from app.safety.rates import (
    COMPARISON_TOLERANCE,
    DISPLAY_PLACES,
    RATE_BASE,
    compare,
    display_rate,
    formula_text,
    incidence_rate,
)
from app.safety.trir.models import TrirAnnualFact
from app.safety.trir.schemas import (
    BenchmarkOut,
    CalculationOut,
    ComparisonOut,
    DataQualityItemOut,
    HistoryRowOut,
    MethodologyOut,
    MissingMonthOut,
    MonthDetailOut,
    TrirExperienceResponse,
    TrirStatusOut,
)

NUMERATOR_SOURCE = {
    "incidents": "Incident & Near Miss: Recordable Injury + Occupational Illness",
    "performance_legacy": "Pre-platform workbook monthly recordable counts (Safety Performance)",
    "historical": "TRIR history: annual recordable count",
}
DENOMINATOR_SOURCE = {
    "monthly": "Safety Performance: Monthly Hours Worked (Total)",
    "historical": "TRIR history: annual man-hours",
}

METHODOLOGY = MethodologyOut(
    formula="TRIR = recordable cases × 200,000 ÷ worked hours",
    rate_base=RATE_BASE,
    numerator=(
        "OSHA-recordable cases: from 2026, Incident & Near Miss Recordable Injury plus "
        "Occupational Illness (Lost Time Injury is part of Recordable Injury and is not added "
        "again); before 2026, the recordable counts of the pre-platform workbook. Incidents "
        "that are not recordable (first aid, near misses, property damage) are never counted."
    ),
    denominator=(
        "Safety Performance 'Monthly Hours Worked (Total)': the total worked hours entered for "
        "each month (hourly plus salary hours where the split is recorded). It is the only "
        "complete hours measure in the platform and the one the source workbook's TRIR uses. "
        "TRIR Experience stores no hours of its own."
    ),
    contractor_hours=(
        "The platform has no contractor-hours field and the source does not state whether "
        "contractor hours are included in the monthly totals. Contractor hours are therefore "
        "not added. Confirm the hours population before relying on the comparison."
    ),
    benchmark=(
        "Industry average TRIR from the Bureau of Labor Statistics, as recorded in the "
        "approved TRIR history for each year. The industry classification is not stated in "
        "the source. When a year has no benchmark the latest earlier one is shown and labelled "
        "with its year."
    ),
    cutoff=(
        "Year to date runs from January through the selected Through month (by default the "
        "latest month for which every month from January is closed in Safety Performance). "
        "The rolling 12-month rate covers the 12 months ending at the Through month and is "
        "shown only when every one of them is complete."
    ),
    rounding=(
        f"Calculated at full precision; displayed rounded half-up to {DISPLAY_PLACES} decimals."
    ),
    comparison_tolerance=(
        f"LCY equals the benchmark when they differ by less than {COMPARISON_TOLERANCE} "
        "(the same value at two decimals); otherwise LCY is below or above it."
    ),
    historical_years=(
        "Years before monthly hours were recorded use the annual recordable count and annual "
        "man-hours of the approved TRIR history, which is annual: each value belongs to the "
        "year of its column, with no month or day. Their legacy displayed TRIR is shown beside "
        "the recalculated value. From 2026 the history row is a legacy snapshot kept for "
        "reconciliation; the rate always comes from Safety Performance monthly hours."
    ),
    unreported_months=(
        "A month without hours, still open, with zero hours or with unconfirmed counts is "
        "never treated as zero: any rate whose window includes it is unavailable, and the "
        "month is listed."
    ),
    legacy_tir=(
        "The source workbook also shows 'TIR' = Incident count × 200,000 ÷ hours, an "
        "all-incident rate. It is not TRIR and is shown only as a legacy figure."
    ),
)


def _str(value: Decimal | None) -> str | None:
    # Fixed-point, never exponent notation ("0E+2", "-8.05E-17").
    return None if value is None else format(value, "f")


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _missing(result: WindowResult) -> list[MissingMonthOut]:
    return [
        MissingMonthOut(year=m.period[0], month=m.period[1], reason=m.reason)
        for m in result.ineligible
    ]


def _monthly_calculation(
    year: int,
    window: WindowResult,
    source: str,
    *,
    from_year: int,
    from_month: int,
    through_month: int,
) -> CalculationOut:
    rate = incidence_rate(window.events, window.hours)
    unavailable = None
    if window.ineligible:
        unavailable = "Not every month in the period is complete in Safety Performance."
    elif rate is None:
        unavailable = "The period has no worked hours."
    return CalculationOut(
        year=year,
        basis="safety_performance_monthly",
        from_year=from_year,
        from_month=from_month,
        through_month=through_month,
        recordables=window.events,
        hours=_float(window.hours),
        rate=_str(rate),
        display=display_rate(rate),
        formula=formula_text(window.events, window.hours),
        numerator_source=NUMERATOR_SOURCE[source],
        denominator_source=DENOMINATOR_SOURCE["monthly"],
        complete=not window.ineligible,
        missing_months=_missing(window),
        unavailable_reason=unavailable,
    )


def _historical_calculation(year: int, fact: TrirAnnualFact | None) -> CalculationOut:
    events = fact.recordable_count if fact else None
    hours = fact.annual_man_hours if fact else None
    rate = incidence_rate(events, hours)
    reason = None
    if fact is None:
        reason = "No monthly hours and no TRIR history for this year."
    elif rate is None:
        reason = "The TRIR history for this year lacks the recordable count or the man-hours."
    return CalculationOut(
        year=year,
        basis="historical_annual" if fact else None,
        from_year=year if fact else None,
        from_month=1 if fact else None,
        through_month=12 if fact else None,
        recordables=events,
        hours=_float(hours),
        rate=_str(rate),
        display=display_rate(rate),
        formula=formula_text(events, hours),
        numerator_source=NUMERATOR_SOURCE["historical"],
        denominator_source=DENOMINATOR_SOURCE["historical"],
        complete=rate is not None,
        missing_months=[],
        unavailable_reason=reason,
    )


def _count_source(counts: Mapping[Period, MonthCounts], year: int) -> str:
    month = counts.get((year, 1))
    return month.source if month else "incidents"


def _year_calculation(
    year: int,
    through: int | None,
    inputs: TrirInputs,
    facts: Mapping[int, TrirAnnualFact],
) -> CalculationOut:
    if not any(period[0] == year for period in inputs.hours):
        if year < FIRST_INCIDENT_YEAR:
            return _historical_calculation(year, facts.get(year))
        # From 2026 the history row is only a legacy snapshot (e.g. 2026 hours
        # are January-August), never an annual denominator.
        return CalculationOut(
            year=year,
            basis=None,
            from_year=None,
            from_month=None,
            through_month=None,
            recordables=None,
            hours=None,
            rate=None,
            display=None,
            formula=None,
            numerator_source=NUMERATOR_SOURCE["incidents"],
            denominator_source=DENOMINATOR_SOURCE["monthly"],
            complete=False,
            missing_months=[],
            unavailable_reason=(
                f"From {FIRST_INCIDENT_YEAR}, TRIR is calculated from Safety Performance "
                "monthly hours, and none are recorded for this year."
            ),
        )
    source = _count_source(inputs.counts, year)
    if through is None:
        first = window_rate(Measure.TRIR, [(year, 1)], inputs.hours, inputs.counts)
        return CalculationOut(
            year=year,
            basis="safety_performance_monthly",
            from_year=year,
            from_month=1,
            through_month=None,
            recordables=None,
            hours=None,
            rate=None,
            display=None,
            formula=None,
            numerator_source=NUMERATOR_SOURCE[source],
            denominator_source=DENOMINATOR_SOURCE["monthly"],
            complete=False,
            missing_months=_missing(first),
            unavailable_reason="January is not complete in Safety Performance.",
        )
    window = window_rate(Measure.TRIR, ytd_window((year, through)), inputs.hours, inputs.counts)
    return _monthly_calculation(
        year, window, source, from_year=year, from_month=1, through_month=through
    )


def _benchmark(year: int, facts: Mapping[int, TrirAnnualFact]) -> tuple[int, TrirAnnualFact] | None:
    for candidate in sorted((y for y in facts if y <= year), reverse=True):
        if facts[candidate].industry_benchmark is not None:
            return candidate, facts[candidate]
    return None


def _comparison(rate: str | None, year: int, facts: Mapping[int, TrirAnnualFact]) -> ComparisonOut:
    found = _benchmark(year, facts)
    benchmark = found[1].industry_benchmark if found else None
    exact = Decimal(rate) if rate is not None else None
    status = compare(exact, benchmark)
    difference = exact - benchmark if exact is not None and benchmark is not None else None
    statement = {
        "below": "LCY TRIR is below the benchmark.",
        "equal": "LCY TRIR equals the benchmark.",
        "above": "LCY TRIR is above the benchmark.",
        "unavailable": (
            "No benchmark is recorded for this year."
            if exact is not None
            else "LCY TRIR is not available, so it cannot be compared."
        ),
    }[status]
    if found and found[0] != year and status != "unavailable":
        statement += f" (Benchmark from {found[0]}; none is recorded for {year}.)"
    return ComparisonOut(
        benchmark_year=found[0] if found else None,
        benchmark=_str(benchmark),
        difference=_str(difference),
        difference_display=display_rate(difference) if difference is not None else None,
        status=status,
        statement=statement,
    )


def _month_state(
    period: Period, hours: Mapping[Period, MonthHours], counts: Mapping[Period, MonthCounts]
) -> str:
    reason = ineligible_reason(hours.get(period))
    if reason is not None:
        return reason
    if counts[period].trir is None:
        return "count_not_confirmed"
    return "closed"


def _monthly_detail(year: int, inputs: TrirInputs) -> list[MonthDetailOut]:
    rows = []
    for month in range(1, 13):
        period = (year, month)
        hours = inputs.hours.get(period)
        counts = inputs.counts.get(period)
        ytd = window_rate(Measure.TRIR, ytd_window(period), inputs.hours, inputs.counts)
        rate = incidence_rate(ytd.events, ytd.hours)
        rows.append(
            MonthDetailOut(
                month=month,
                state=_month_state(period, inputs.hours, inputs.counts),  # type: ignore[arg-type]
                recordables=counts.trir if counts else None,
                hours=_float(hours.total_hours) if hours else None,
                ytd_recordables=ytd.events,
                ytd_hours=_float(ytd.hours),
                ytd_rate=_str(rate),
                ytd_display=display_rate(rate),
            )
        )
    return rows


def _incident_count(
    year: int, through: int | None, totals: Mapping[tuple[str, int], int]
) -> int | None:
    """Stored monthly Incident totals January..through; None while any is unreported."""
    if through is None:
        return None
    values = [totals.get(("incident", month)) for month in range(1, through + 1)]
    if any(value is None for value in values):
        return None
    return sum(v for v in values if v is not None)


def _row_incidents(
    year: int,
    calculation: CalculationOut,
    fact: TrirAnnualFact | None,
    incident_totals: Callable[[int], Mapping[tuple[str, int], int]],
) -> int | None:
    """Live Incident count for a platform year; the recorded count otherwise."""
    if calculation.basis == "safety_performance_monthly" and year >= FIRST_INCIDENT_YEAR:
        return _incident_count(year, calculation.through_month, incident_totals(year))
    return fact.incident_count if fact else None


def _shown(value: int | None) -> str:
    return "unknown" if value is None else str(value)


def _hours_text(value: float | Decimal | None) -> str:
    return "unknown" if value is None else f"{value:,.2f}".removesuffix(".00")


def _same(a: Decimal | None, b: Decimal | None) -> bool:
    return a is not None and b is not None and abs(a - b) < COMPARISON_TOLERANCE


def _data_quality(
    facts: Mapping[int, TrirAnnualFact],
    inputs: TrirInputs,
    history: list[HistoryRowOut],
) -> list[DataQualityItemOut]:
    items: list[DataQualityItemOut] = []
    rows = {row.year: row for row in history}
    for year, fact in facts.items():
        row = rows.get(year)
        if fact.legacy_displayed_trir is not None and row and row.calculation.rate is not None:
            calculated = Decimal(row.calculation.rate)
            ok = _same(calculated, fact.legacy_displayed_trir)
            items.append(
                DataQualityItemOut(
                    year=year,
                    check="legacy_trir",
                    status="ok" if ok else "warning",
                    message=(
                        f"Calculated TRIR {display_rate(calculated)} "
                        + ("matches" if ok else "differs from")
                        + f" the legacy figure {fact.legacy_displayed_trir}."
                    ),
                )
            )
        if row and row.calculation.basis == "safety_performance_monthly":
            live = row.calculation
            same_hours = (
                live.hours is not None
                and fact.annual_man_hours is not None
                and Decimal(str(live.hours)) == fact.annual_man_hours
            )
            same_events = live.recordables == fact.recordable_count
            period = (
                "full year"
                if live.through_month == 12
                else f"January-{dt.date(2000, live.through_month or 1, 1):%B}"
            )
            items.append(
                DataQualityItemOut(
                    year=year,
                    check="snapshot",
                    status="ok" if same_hours and same_events else "warning",
                    message=(
                        f"Live {period}: {_shown(live.recordables)} recordables, "
                        f"{_hours_text(live.hours)} hours. Legacy snapshot: "
                        f"{_shown(fact.recordable_count)} recordables, "
                        f"{_hours_text(fact.annual_man_hours)} hours."
                        + ("" if same_hours and same_events else " They differ.")
                    ),
                )
            )
        legacy = inputs.annual_legacy.get(year)
        if legacy is not None:
            same = (
                legacy.recordables == fact.recordable_count
                and fact.annual_man_hours is not None
                and legacy.total_hours == fact.annual_man_hours
            )
            items.append(
                DataQualityItemOut(
                    year=year,
                    check="performance_annual",
                    status="ok" if same else "warning",
                    message=(
                        "Safety Performance annual figures "
                        f"({legacy.recordables} recordables, "
                        f"{_hours_text(legacy.total_hours)} hours) "
                        + ("match" if same else "differ from")
                        + " the TRIR history."
                    ),
                )
            )
        if fact.note:
            items.append(
                DataQualityItemOut(
                    year=year, check="source_note", status="warning", message=fact.note
                )
            )
        if fact.industry_benchmark is None:
            items.append(
                DataQualityItemOut(
                    year=year,
                    check="benchmark",
                    status="warning",
                    message="No industry benchmark is recorded for this year.",
                )
            )
    return items


def experience(
    facts: Mapping[int, TrirAnnualFact],
    inputs_for: Callable[[list[int]], TrirInputs],
    incident_totals: Callable[[int], Mapping[tuple[str, int], int]],
    *,
    year: int,
    through_month: int | None,
) -> TrirExperienceResponse:
    first_year = min([*facts, year])
    years = list(range(first_year, year + 1))
    inputs = inputs_for(years)
    latest = latest_ytd_month(year, inputs.hours)
    has_monthly = any(period[0] == year for period in inputs.hours)
    through = through_month if through_month is not None else latest
    if not has_monthly:
        through = None

    current = _year_calculation(year, through, inputs, facts)
    rolling: CalculationOut
    if has_monthly and through is not None:
        rolling_result = window_rate(
            Measure.TRIR, rolling_window((year, through)), inputs.hours, inputs.counts
        )
        rolling = _monthly_calculation(
            year,
            rolling_result,
            _count_source(inputs.counts, year),
            from_year=rolling_result.start[0],
            from_month=rolling_result.start[1],
            through_month=through,
        )
        if rolling_result.start[0] != year:
            rolling = rolling.model_copy(
                update={
                    "numerator_source": "Recordables of the 12 months (each year's own source)",
                }
            )
    else:
        rolling = current.model_copy(
            update={
                "basis": None,
                "rate": None,
                "display": None,
                "formula": None,
                "complete": False,
                "unavailable_reason": "A rolling 12-month rate needs monthly hours.",
            }
        )

    history: list[HistoryRowOut] = []
    for history_year in years:
        if history_year == year:
            calculation = current
        else:
            year_through = latest_ytd_month(history_year, inputs.hours)
            calculation = _year_calculation(history_year, year_through, inputs, facts)
        fact = facts.get(history_year)
        if calculation.basis is None and fact is None:
            continue
        legacy = fact.legacy_displayed_trir if fact else None
        rate = Decimal(calculation.rate) if calculation.rate is not None else None
        found = _benchmark(history_year, facts)
        partial = calculation.basis == "safety_performance_monthly" and (
            calculation.through_month != 12
        )
        history.append(
            HistoryRowOut(
                year=history_year,
                calculation=calculation,
                incident_count=_row_incidents(history_year, calculation, fact, incident_totals),
                legacy_trir=_str(legacy),
                legacy_tir=_str(fact.legacy_tir) if fact else None,
                legacy_difference=_str(rate - legacy)
                if rate is not None and legacy is not None
                else None,
                benchmark=BenchmarkOut(
                    year=found[0],
                    value=_str(found[1].industry_benchmark),
                    source=found[1].benchmark_source,
                )
                if found
                else None,
                comparison=_comparison(calculation.rate, history_year, facts),
                partial=partial,
                note=fact.note if fact else None,
            )
        )

    current_incidents = _row_incidents(year, current, facts.get(year), incident_totals)
    benchmarks = [
        BenchmarkOut(year=y, value=_str(f.industry_benchmark), source=f.benchmark_source)
        for y, f in sorted(facts.items())
    ]
    return TrirExperienceResponse(
        year=year,
        status=TrirStatusOut(
            year=year,
            latest_complete_month=latest if has_monthly else None,
            through_month=through,
            complete=current.complete,
            history_years=[row.year for row in history],
        ),
        current=current,
        comparison=_comparison(current.rate, year, facts),
        rolling12=rolling,
        incident_count=current_incidents,
        history=history,
        monthly=_monthly_detail(year, inputs) if has_monthly else [],
        benchmarks=benchmarks,
        data_quality=_data_quality(facts, inputs, history),
        methodology=METHODOLOGY,
    )
