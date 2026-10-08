"""TRIR Experience: the shared rate formula, the history mapping and the live
calculation from Safety Performance hours and Incident & Near Miss recordables.

The Safety Performance fixture data is loaded through the reviewed import
mappings (see test_safety_performance.py); the TRIR history comes from
import_templates/safety_trir_experience_history_lcy_ehs.mapping.json.
"""

import json
import re
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_safety_performance import (
    FIXTURES,
    InMemoryRepository,
    import_hours,
    load_incident_counts,
    load_legacy_counts,
)

from app.core.authorization import UserPrincipal, get_user_principal
from app.core.permissions import Permission
from app.main import create_app
from app.safety import rates
from app.safety.performance.calculations import MonthHours
from app.safety.performance.service import TrirInputs, trir_inputs
from app.safety.trir import legacy_import, service
from app.safety.trir import router as trir_router
from app.safety.trir.models import TrirAnnualFact
from app.safety.trir.schemas import TrirExperienceResponse

API_ROOT = Path(__file__).resolve().parents[1]
MAPPING = API_ROOT / "import_templates" / "safety_trir_experience_history_lcy_ehs.mapping.json"
P = Permission

# The approved history: (recordables, man-hours, legacy displayed TRIR, benchmark).
EXPECTED_HISTORY = {
    2021: (1, Decimal("172301"), Decimal("1.16"), Decimal("2.7")),
    2022: (3, Decimal("176350"), Decimal("3.4"), Decimal("1.9")),
    2023: (1, Decimal("168563"), Decimal("1.19"), Decimal("1.9")),
    2024: (1, Decimal("174706"), Decimal("1.14"), Decimal("1.9")),
    2025: (0, Decimal("191751"), Decimal("0"), Decimal("1.9")),
    2026: (1, Decimal("145194"), Decimal("1.3774673884595783"), Decimal("1.9")),
}


# The shared formula --------------------------------------------------------------


def test_rate_is_full_precision_decimal() -> None:
    rate = rates.incidence_rate(1, Decimal("145194"))

    assert rate is not None
    assert str(rate).startswith("1.37746738845957")
    assert float(rate) == pytest.approx(FIXTURES[("trir", "ytd")], abs=1e-15)
    assert rates.display_rate(rate) == "1.38"


@pytest.mark.parametrize("hours", [None, Decimal(0), Decimal(-5)])
def test_rate_without_positive_hours_is_unavailable_not_zero(hours: Decimal | None) -> None:
    assert rates.incidence_rate(1, hours) is None
    assert rates.incidence_rate(0, hours) is None
    assert rates.formula_text(1, hours) is None


def test_zero_events_with_hours_is_a_real_zero() -> None:
    assert rates.incidence_rate(0, Decimal("191751")) == 0
    assert rates.display_rate(rates.incidence_rate(0, Decimal("191751"))) == "0.00"


def test_formula_text_shows_the_inputs() -> None:
    assert rates.formula_text(1, Decimal("145194")) == "(1 × 200,000) ÷ 145,194"
    assert rates.formula_text(3, Decimal("1234.50")) == "(3 × 200,000) ÷ 1,234.50"


def test_display_rounds_half_up_only_for_display() -> None:
    assert rates.display_rate(Decimal("1.125")) == "1.13"
    assert rates.display_rate(Decimal("1.1249999")) == "1.12"


@pytest.mark.parametrize(
    ("rate", "benchmark", "expected"),
    [
        (Decimal("1.3774"), Decimal("1.9"), "below"),
        (Decimal("3.4023"), Decimal("1.9"), "above"),
        (Decimal("1.9049"), Decimal("1.9"), "equal"),
        (Decimal("1.8951"), Decimal("1.9"), "equal"),
        (Decimal("1.905"), Decimal("1.9"), "above"),
        (None, Decimal("1.9"), "unavailable"),
        (Decimal("1"), None, "unavailable"),
    ],
)
def test_benchmark_comparison_uses_the_documented_tolerance(
    rate: Decimal | None, benchmark: Decimal | None, expected: str
) -> None:
    assert rates.compare(rate, benchmark) == expected


# History mapping -----------------------------------------------------------------


def test_mapping_matches_the_approved_history_and_recalculates() -> None:
    mapping = legacy_import.load_mapping(MAPPING)

    for entry in mapping.years:
        recordables, hours, legacy, benchmark = EXPECTED_HISTORY[entry.year]
        assert entry.recordable_count.value == recordables
        assert entry.annual_man_hours.value == hours
        assert entry.legacy_displayed_trir.value == legacy
        assert entry.industry_benchmark.value == benchmark
        result = legacy_import.recalculate(entry)
        assert not result.trir_mismatch, entry.year
        assert not result.tir_mismatch, entry.year
    assert {e.year for e in mapping.years} == set(EXPECTED_HISTORY)


def test_mapping_flags_a_legacy_mismatch() -> None:
    mapping = legacy_import.load_mapping(MAPPING)
    entry = mapping.years[0].model_copy(
        update={
            "legacy_displayed_trir": legacy_import.DecimalCell(
                value=Decimal("1.5"), source_cell="H18"
            )
        }
    )
    assert legacy_import.recalculate(entry).trir_mismatch


def test_check_command_passes_and_needs_no_database(capsys: pytest.CaptureFixture[str]) -> None:
    assert legacy_import.run("check", MAPPING) == 0
    out = capsys.readouterr().out
    assert "MISMATCH" not in out
    assert "2022: recordables 3" in out


def _facts(path: Path = MAPPING) -> dict[int, TrirAnnualFact]:
    mapping = legacy_import.load_mapping(path)
    return {
        e.year: TrirAnnualFact(reporting_year=e.year, **legacy_import.year_values(mapping, e))
        for e in mapping.years
    }


def test_plan_inserts_new_years_and_is_idempotent() -> None:
    mapping = legacy_import.load_mapping(MAPPING)

    first = legacy_import.plan_import({}, mapping)
    again = legacy_import.plan_import(_facts(), mapping)

    assert [e.year for e in first.inserts] == sorted(EXPECTED_HISTORY)
    assert (again.inserts, again.differing) == ([], [])
    assert again.unchanged == sorted(EXPECTED_HISTORY)


def test_plan_blocks_a_stored_year_that_differs() -> None:
    stored = _facts()
    stored[2023].annual_man_hours = Decimal("1.00")

    plan = legacy_import.plan_import(stored, legacy_import.load_mapping(MAPPING))

    assert [(d[0], d[1]) for d in plan.differing] == [(2023, "annual_man_hours")]


def test_mapping_has_no_monthly_hours() -> None:
    raw = json.loads(MAPPING.read_text(encoding="utf-8"))
    assert all(
        set(entry)
        <= {
            "year",
            "recordableCount",
            "incidentCount",
            "annualManHours",
            "industryBenchmark",
            "legacyDisplayedTrir",
            "legacyTir",
            "note",
        }
        for entry in raw["years"]
    )


# Live calculation ----------------------------------------------------------------


@pytest.fixture
def performance() -> InMemoryRepository:
    repository = InMemoryRepository()
    import_hours(repository)
    load_legacy_counts(repository)
    load_incident_counts(repository)
    return repository


# Test fixture: synthetic monthly Incident totals (one per month), not source data.
FIXTURE_INCIDENT_TOTALS = {("incident", month): 1 for month in range(1, 9)}


def _experience(
    performance: InMemoryRepository, year: int = 2026, through: int | None = None, **kw: Any
) -> TrirExperienceResponse:
    totals = kw.get("totals", FIXTURE_INCIDENT_TOTALS)
    return service.experience(
        kw.get("facts", _facts()),
        lambda years: trir_inputs(performance, years),
        lambda y: totals if y == 2026 else {},
        year=year,
        through_month=through,
    )


def test_incident_count_is_unknown_while_a_month_is_unreported(
    performance: InMemoryRepository,
) -> None:
    totals = dict(FIXTURE_INCIDENT_TOTALS)
    del totals[("incident", 4)]

    assert _experience(performance).incident_count == 8
    assert _experience(performance, totals=totals).incident_count is None


def test_current_year_is_live_from_performance_hours(performance: InMemoryRepository) -> None:
    result = _experience(performance)
    current = result.current

    assert result.status.through_month == 8
    assert current.basis == "safety_performance_monthly"
    assert (current.from_month, current.through_month) == (1, 8)
    assert (current.recordables, current.hours) == (1, 145194)
    assert current.rate is not None and current.rate.startswith("1.37746738845957")
    assert current.display == "1.38"
    assert current.formula == "(1 × 200,000) ÷ 145,194"
    assert current.complete and current.missing_months == []
    assert result.comparison.status == "below"
    assert result.comparison.benchmark == "1.9"
    assert result.comparison.difference_display == "-0.52"
    assert result.comparison.statement == "LCY TRIR is below the benchmark."


def test_rolling_twelve_months_spans_2025_and_2026(performance: InMemoryRepository) -> None:
    rolling = _experience(performance).rolling12

    assert rolling.complete
    assert (rolling.from_year, rolling.from_month, rolling.year, rolling.through_month) == (
        2025,
        9,
        2026,
        8,
    )
    assert (rolling.recordables, rolling.hours) == (1, 210634)
    assert float(Decimal(rolling.rate or "0")) == pytest.approx(
        FIXTURES[("trir", "rolling")], abs=1e-12
    )


def test_a_month_without_hours_blocks_the_rate(performance: InMemoryRepository) -> None:
    result = _experience(performance, through=9)

    assert result.current.rate is None and result.current.display is None
    assert not result.current.complete
    assert [(m.month, m.reason) for m in result.current.missing_months] == [(9, "not_reported")]
    assert result.comparison.status == "unavailable"
    assert result.rolling12.rate is None


def test_history_uses_annual_facts_before_monthly_hours(performance: InMemoryRepository) -> None:
    history = {row.year: row for row in _experience(performance).history}

    assert sorted(history) == sorted(EXPECTED_HISTORY)
    for year in (2021, 2022, 2023, 2024):
        row = history[year]
        recordables, hours, legacy, _ = EXPECTED_HISTORY[year]
        assert row.calculation.basis == "historical_annual"
        assert (row.calculation.recordables, row.calculation.hours) == (recordables, float(hours))
        assert row.legacy_trir == str(legacy)
    assert history[2022].calculation.display == "3.40"
    assert history[2022].comparison.status == "above"
    assert history[2021].benchmark is not None and history[2021].benchmark.value == "2.7"
    full_2025 = history[2025]
    assert full_2025.calculation.basis == "safety_performance_monthly"
    assert (full_2025.calculation.recordables, full_2025.calculation.hours) == (0, 191751)
    assert full_2025.calculation.display == "0.00"
    assert not full_2025.partial
    assert history[2026].partial


def test_data_quality_reports_matches_and_source_notes(performance: InMemoryRepository) -> None:
    items = _experience(performance).data_quality

    by_check = {(i.year, i.check): i for i in items}
    for year in EXPECTED_HISTORY:
        assert by_check[(year, "legacy_trir")].status == "ok", year
    assert by_check[(2026, "snapshot")].status == "ok"
    assert by_check[(2025, "snapshot")].status == "ok"
    assert by_check[(2022, "source_note")].status == "warning"
    assert "425,039.90" in by_check[(2022, "source_note")].message


def test_monthly_detail_never_turns_unreported_into_zero(performance: InMemoryRepository) -> None:
    monthly = _experience(performance).monthly

    august, september = monthly[7], monthly[8]
    assert (august.state, august.recordables, august.hours) == ("closed", 1, 18031)
    assert august.ytd_display == "1.38"
    assert (september.state, september.hours, september.ytd_rate) == ("not_reported", None, None)


def test_a_live_year_never_uses_its_history_snapshot_as_the_denominator() -> None:
    empty = TrirInputs(hours={}, counts={}, annual_legacy={})
    result = service.experience(
        _facts(), lambda years: empty, lambda y: {}, year=2026, through_month=None
    )
    history = {row.year: row for row in result.history}

    assert result.current.rate is None and result.current.hours is None
    assert "Safety Performance monthly hours" in (result.current.unavailable_reason or "")
    assert history[2026].legacy_trir == "1.3774673884595783"
    assert history[2025].calculation.basis == "historical_annual"


def test_a_year_without_any_data_is_unavailable() -> None:
    empty = TrirInputs(hours={}, counts={}, annual_legacy={})
    result = service.experience(
        {}, lambda years: empty, lambda y: {}, year=2030, through_month=None
    )

    assert result.current.rate is None
    assert result.current.unavailable_reason is not None
    assert result.history == []
    assert result.comparison.status == "unavailable"


def test_benchmark_falls_back_to_the_latest_earlier_year_and_says_so(
    performance: InMemoryRepository,
) -> None:
    facts = _facts()
    facts[2026].industry_benchmark = None

    comparison = _experience(performance, facts=facts).comparison

    assert comparison.benchmark_year == 2025
    assert "Benchmark from 2025" in comparison.statement


def test_zero_hours_month_is_not_a_zero_rate() -> None:
    inputs = TrirInputs(
        hours={(2030, 1): MonthHours(Decimal(0), True)}, counts={}, annual_legacy={}
    )
    from app.safety.performance.calculations import month_counts

    inputs.counts.update(
        {(2030, m): month_counts("incidents", {}, closed=m == 1) for m in range(1, 13)}
    )

    result = service.experience({}, lambda years: inputs, lambda y: {}, year=2030, through_month=1)

    assert result.current.rate is None
    assert [m.reason for m in result.current.missing_months] == ["zero_hours"]


# API ----------------------------------------------------------------------------


class _Session:
    """Stands in for the request session; the repositories it would build are patched."""


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, performance: InMemoryRepository) -> Iterator[Any]:
    facts = _facts()

    def experience(session: Any, year: int | None, through: int | None) -> TrirExperienceResponse:
        return _experience(performance, year or 2026, through, facts=facts)

    monkeypatch.setattr(trir_router, "_experience", experience)

    def make(*permissions: Permission) -> TestClient:
        app = create_app()
        app.dependency_overrides[trir_router.trir_session] = _Session
        app.dependency_overrides[get_user_principal] = lambda: UserPrincipal(
            "tester", authenticated=True, granted=frozenset(permissions)
        )
        return TestClient(app)

    yield make


def test_trir_requires_its_own_view_permission(api: Any) -> None:
    url = "/api/v1/safety/trir/experience"
    assert api(P.SAFETY_TRIR_VIEW).get(url).status_code == 200
    assert api(P.SAFETY_VIEW).get(url).status_code == 200
    assert api(P.SAFETY_PERFORMANCE_VIEW).get(url).status_code == 403
    assert api(P.SAFETY_INCIDENTS_EDIT).get(url).status_code == 403
    assert api().get(url).status_code == 403


@pytest.mark.parametrize(
    "path",
    ["experience", "current", "calculation", "history", "monthly", "benchmarks", "status",
     "reconciliation", "methodology"],
)  # fmt: skip
def test_responses_carry_no_workbook_cell_coordinates(api: Any, path: str) -> None:
    response = api(P.SAFETY_TRIR_VIEW).get(f"/api/v1/safety/trir/{path}")
    assert response.status_code == 200, response.text
    body = response.text
    assert "sourceCell" not in body and "sourceReference" not in body
    assert not re.search(r"\b[A-Z]{1,2}[0-9]{1,3}\b", body), re.findall(
        r"\b[A-Z]{1,2}[0-9]{1,3}\b", body
    )
    assert "!" not in body.replace("LCY", "")


def test_experience_json_shape(api: Any) -> None:
    body = api(P.SAFETY_TRIR_VIEW).get("/api/v1/safety/trir/experience").json()

    assert body["current"]["formula"] == "(1 × 200,000) ÷ 145,194"
    assert body["current"]["rate"].startswith("1.37746738845957")
    assert body["comparison"]["status"] == "below"
    assert body["methodology"]["rateBase"] == 200000
    assert [row["year"] for row in body["history"]] == sorted(EXPECTED_HISTORY)
    decimals = [body["current"]["rate"], body["comparison"]["difference"]]
    decimals += [m["ytdRate"] for m in body["monthly"]]
    decimals += [row["legacyDifference"] for row in body["history"]]
    decimals += [row["calculation"]["rate"] for row in body["history"]]
    assert not [d for d in decimals if d is not None and "E" in d.upper()]
    assert body["monthly"][0]["ytdRate"] == "0"
