"""Safety Performance: rate windows, numerators, hours entry and import tooling.

Runs against an in-memory repository. Database behaviour (constraints, real
SQL, migration) is covered by test_safety_performance_database.py.

The accepted 2026 fixtures are checked two ways: recomputed here from the
source counts and hours (count × 200,000 ÷ hours), and returned by the API from
the same data loaded through the reviewed import mappings.
"""

import datetime as dt
import importlib.util
import json
import uuid
from collections.abc import Collection, Iterator, Sequence
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.audit.recorder import AuditChange
from app.core.authorization import UserPrincipal, get_user_principal
from app.core.permissions import Permission
from app.main import create_app
from app.safety import legacy_import as metrics_import
from app.safety.performance import calculations as calc
from app.safety.performance import legacy_import
from app.safety.performance import router as performance_router
from app.safety.performance.repository import (
    AnnualRecord,
    AnnualValues,
    HoursRecord,
    HoursValues,
    StoredCounts,
)
from app.safety.performance.router import performance_repository

API_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = API_ROOT / "import_templates"
HOURS_MAPPING = TEMPLATES / "safety_performance_hours_lcy_ehs.mapping.json"
LEGACY_MAPPING = TEMPLATES / "safety_performance_legacy_2025_lcy_ehs.mapping.json"
MIGRATION_0006 = API_ROOT / "alembic" / "versions" / "2026_10_07_1530-0006_safety_performance.py"

URL = "/api/v1/safety/performance"
NOW = dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.UTC)
SEEDED = NOW - dt.timedelta(days=1)
P = Permission
TOLERANCE = 1e-9

# Source data -----------------------------------------------------------------------

HOURS_2025 = [15000, 15941, 15785, 16858, 17091, 15833, 14706, 15097, 16918, 16632, 15591, 16299]
HOURS_2026 = [21473, 17654, 18698, 18068, 17366, 17111, 16793, 18031]  # January..August

# Stored Incident & Near Miss 2026 values ({month: value}); absent = no stored value.
# September has counts but no hours, so it must not enter any rate.
INCIDENTS_2026: dict[str, dict[int, int]] = {
    "first_aid": {1: 1, 3: 1, 4: 2, 9: 1},
    "recordable_injury": {8: 1},
    "lopc": {1: 1, 2: 2, 3: 2, 4: 1, 6: 2, 7: 3, 8: 2, 9: 1},
    "property_damage": {1: 1, 2: 1, 5: 2, 7: 2},
    "equipment_damage_failure": {1: 0, 3: 1, 4: 4, 6: 2, 9: 1},
}

# Exactly count × 200,000 ÷ hours for the approved counts and hours.
FIXTURES = {
    "hours": 145194,
    ("trir", "ytd"): 1.3774673884595783,
    ("trir", "rolling"): 0.9495143234235689,
    ("first_aid", "ytd"): 5.509869553838313,
    ("first_aid", "rolling"): 4.747571617117845,
    ("lopc", "ytd"): 17.907076049974517,
    ("lopc", "rolling"): 16.141743498200672,
    ("property_equipment_damage", "ytd"): 17.907076049974517,
    ("property_equipment_damage", "rolling"): 14.242714851353533,
}
DISPLAYED = {
    ("trir", "ytd"): "1.38",
    ("trir", "rolling"): "0.95",
    ("first_aid", "ytd"): "5.51",
    ("first_aid", "rolling"): "4.75",
    ("lopc", "ytd"): "17.91",
    ("lopc", "rolling"): "16.14",
    ("property_equipment_damage", "ytd"): "17.91",
    ("property_equipment_damage", "rolling"): "14.24",
}

# Events in each window, counted by hand from the source data above and the
# 2025 legacy mapping (Sep-Dec 2025 + Jan-Aug 2026 for the 12MRA).
EXPECTED_EVENTS = {
    ("trir", "ytd"): 1,  # recordable injury Aug 2026
    ("trir", "rolling"): 1,  # 2025 Sep-Dec: 0 (TRIR EXP.!L8 states 0 for 2025)
    ("first_aid", "ytd"): 4,  # Jan 1, Mar 1, Apr 2
    ("first_aid", "rolling"): 5,  # + Oct 2025 1, Dec 0; Sep and Nov 2025 blank in source
    ("lopc", "ytd"): 13,
    ("lopc", "rolling"): 17,  # + Sep 2, Oct 1, Nov 0, Dec 1
    ("property_equipment_damage", "ytd"): 13,  # property 6 + equipment 7
    ("property_equipment_damage", "rolling"): 15,  # + Sep 1, Nov 1, Dec 0; Oct 2025 blank
}
# Legacy months whose source cell is blank, which block these 12MRA windows.
UNCONFIRMED_2025 = {"first_aid": [9, 11], "property_equipment_damage": [10]}


YTD_HOURS = sum(HOURS_2026)
ROLLING_HOURS = sum(HOURS_2025[8:]) + YTD_HOURS


def exact_rate(measure: str, window: str) -> float:
    hours = YTD_HOURS if window == "ytd" else ROLLING_HOURS
    return EXPECTED_EVENTS[(measure, window)] * 200000 / hours


def test_fixture_values_are_the_formula_applied_to_the_approved_counts_and_hours() -> None:
    assert FIXTURES["hours"] == YTD_HOURS
    assert ROLLING_HOURS == 210634
    for measure, window in EXPECTED_EVENTS:
        assert exact_rate(measure, window) == pytest.approx(
            FIXTURES[(measure, window)], rel=TOLERANCE
        )
        assert f"{FIXTURES[(measure, window)]:.2f}" == DISPLAYED[(measure, window)]


# In-memory repository --------------------------------------------------------------


class InMemoryRepository:
    """Holds committed rows; writes become visible only on commit, like a transaction."""

    def __init__(self) -> None:
        self.hour_rows: dict[calc.Period, HoursRecord] = {}
        self.pending: dict[calc.Period, HoursRecord | None] = {}
        self.annual_rows: dict[int, AnnualRecord] = {}
        self.pending_annual: dict[int, AnnualRecord] = {}
        self.incidents: StoredCounts = {}
        self.legacy: StoredCounts = {}
        self.audit: list[tuple[str, uuid.UUID, AuditChange]] = []
        self.pending_audit: list[tuple[str, uuid.UUID, AuditChange]] = []
        self.locks: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail: Exception | None = None

    def _hours(self) -> dict[calc.Period, HoursRecord]:
        merged = {**self.hour_rows, **self.pending}
        return {k: v for k, v in merged.items() if v is not None}

    def hours(self) -> dict[calc.Period, HoursRecord]:
        if self.fail:
            raise self.fail
        return self._hours()

    def get_hours(self, year: int, month: int) -> HoursRecord | None:
        return self._hours().get((year, month))

    def lock_month(self, year: int, month: int) -> None:
        self.locks.append(f"{year}-{month}")

    def insert_hours(
        self, year: int, month: int, values: HoursValues, *, actor_id: str, at: dt.datetime
    ) -> None:
        assert (year, month) not in self._hours()
        self.pending[(year, month)] = HoursRecord(year, month, values, at, actor_id, at, actor_id)

    def update_hours(
        self, year: int, month: int, values: HoursValues, *, actor_id: str, at: dt.datetime
    ) -> None:
        current = self._hours()[(year, month)]
        self.pending[(year, month)] = replace(
            current, values=values, updated_at=at, updated_by=actor_id
        )

    def delete_hours(self, year: int, month: int) -> None:
        self.pending[(year, month)] = None

    def annual_legacy(self) -> dict[int, AnnualRecord]:
        return {**self.annual_rows, **self.pending_annual}

    def lock_annual(self, year: int) -> None:
        self.locks.append(f"annual-{year}")

    def insert_annual(
        self, year: int, values: AnnualValues, *, actor_id: str, at: dt.datetime
    ) -> None:
        self.pending_annual[year] = AnnualRecord(year, values)

    def counts(self, years: Collection[int]) -> tuple[StoredCounts, StoredCounts]:
        if self.fail:
            raise self.fail
        return (
            {p: v for p, v in self.incidents.items() if p[0] in years},
            {p: v for p, v in self.legacy.items() if p[0] in years},
        )

    def record_audit(
        self,
        changes: Sequence[AuditChange],
        *,
        actor_id: str,
        change_set_id: uuid.UUID,
        at: dt.datetime,
    ) -> None:
        self.pending_audit.extend((actor_id, change_set_id, c) for c in changes)

    def commit(self) -> None:
        for period, record in self.pending.items():
            if record is None:
                self.hour_rows.pop(period, None)
            else:
                self.hour_rows[period] = record
        self.annual_rows.update(self.pending_annual)
        self.audit.extend(self.pending_audit)
        self.pending, self.pending_annual, self.pending_audit = {}, {}, []
        self.commits += 1

    def rollback(self) -> None:
        self.pending, self.pending_annual, self.pending_audit = {}, {}, []
        self.rollbacks += 1


def set_hours(
    repository: InMemoryRepository, year: int, month: int, total: float, *, closed: bool = True
) -> None:
    repository.hour_rows[(year, month)] = HoursRecord(
        year,
        month,
        HoursValues(Decimal(str(total)).quantize(Decimal("0.01")), None, None, closed),
        SEEDED,
        "seed",
        SEEDED,
        "seed",
    )


def load_legacy_counts(repository: InMemoryRepository) -> None:
    """2025 counts exactly as the reviewed performance_legacy mapping lists them."""
    mapping = metrics_import.load_mapping(LEGACY_MAPPING)
    for cell in metrics_import.cells(mapping):
        if cell.value is not None:
            repository.legacy.setdefault((mapping.year, cell.month), {})[cell.category] = cell.value


def load_incident_counts(repository: InMemoryRepository) -> None:
    for name, months in INCIDENTS_2026.items():
        for month, value in months.items():
            repository.incidents.setdefault((2026, month), {})[name] = value


def import_hours(repository: InMemoryRepository) -> None:
    mapping = legacy_import.load_mapping(HOURS_MAPPING)
    plan = legacy_import.plan_import(repository, mapping, today=NOW.date())
    assert plan.blocking == []
    legacy_import.apply_plan(repository, plan, now=SEEDED)


@pytest.fixture
def repository() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def accepted(repository: InMemoryRepository) -> InMemoryRepository:
    """The accepted fixture data, loaded through the reviewed import mappings."""
    import_hours(repository)
    load_legacy_counts(repository)
    load_incident_counts(repository)
    return repository


def principal(*permissions: Permission) -> UserPrincipal:
    return UserPrincipal("tester", authenticated=True, granted=frozenset(permissions))


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(performance_router, "_now", lambda: NOW)


def make_client(repository: InMemoryRepository, user: UserPrincipal | None) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[performance_repository] = lambda: repository
    if user is not None:
        app.dependency_overrides[get_user_principal] = lambda: user
    with TestClient(app) as client:
        yield client


@pytest.fixture
def editor(repository: InMemoryRepository) -> Iterator[TestClient]:
    yield from make_client(repository, principal(P.SAFETY_PERFORMANCE_EDIT))


@pytest.fixture
def viewer(repository: InMemoryRepository) -> Iterator[TestClient]:
    yield from make_client(repository, principal(P.SAFETY_PERFORMANCE_VIEW))


def dashboard(client: TestClient, year: int = 2026, **params: Any) -> dict[str, Any]:
    response = client.get(URL + "/dashboard", params={"year": year, **params})
    assert response.status_code == 200, response.text
    return response.json()


def kpi(data: dict[str, Any], measure: str) -> dict[str, Any]:
    return next(k for k in data["kpis"] if k["measure"] == measure)


# Accepted fixtures -----------------------------------------------------------------


def assert_fixture(rate: dict[str, Any], measure: str, window: str) -> None:
    assert rate["available"] is True
    assert rate["ineligibleMonths"] == []
    assert rate["events"] == EXPECTED_EVENTS[(measure, window)]
    assert rate["rate"] == pytest.approx(FIXTURES[(measure, window)], rel=TOLERANCE)


def test_dashboard_returns_the_2026_through_august_fixtures(
    accepted: InMemoryRepository, viewer: TestClient
) -> None:
    data = dashboard(viewer)

    assert data["throughMonth"] == 8
    assert data["ytdHours"] == FIXTURES["hours"]
    for measure in ("trir", "first_aid", "lopc", "property_equipment_damage"):
        assert_fixture(kpi(data, measure)["ytd"], measure, "ytd")
    for measure in ("trir", "lopc"):
        assert_fixture(kpi(data, measure)["rolling"], measure, "rolling")


def test_blank_2025_source_counts_make_their_12mra_unavailable(
    accepted: InMemoryRepository, viewer: TestClient
) -> None:
    data = dashboard(viewer)

    for measure, months in UNCONFIRMED_2025.items():
        rolling = kpi(data, measure)["rolling"]
        assert rolling["available"] is False
        assert (rolling["rate"], rolling["events"]) == (None, None)
        assert rolling["ineligibleMonths"] == [
            {"year": 2025, "month": m, "reason": "count_not_confirmed"} for m in months
        ]


def test_12mra_once_the_blank_2025_counts_are_confirmed_matches_the_formula(
    accepted: InMemoryRepository, viewer: TestClient
) -> None:
    for measure, months in UNCONFIRMED_2025.items():
        for month in months:
            accepted.legacy[(2025, month)][measure] = 0

    data = dashboard(viewer)

    for measure in UNCONFIRMED_2025:
        assert_fixture(kpi(data, measure)["rolling"], measure, "rolling")


def test_windows_are_january_to_through_month_and_the_twelve_months_ending_it(
    accepted: InMemoryRepository, viewer: TestClient
) -> None:
    trir = kpi(dashboard(viewer), "trir")

    assert (trir["ytd"]["start"], trir["ytd"]["end"]) == (
        {"year": 2026, "month": 1},
        {"year": 2026, "month": 8},
    )
    assert trir["ytd"]["hours"] == 145194
    assert (trir["rolling"]["start"], trir["rolling"]["end"]) == (
        {"year": 2025, "month": 9},
        {"year": 2026, "month": 8},
    )
    assert trir["rolling"]["hours"] == 210634


def test_september_counts_without_hours_never_enter_a_rate(
    accepted: InMemoryRepository, viewer: TestClient
) -> None:
    data = dashboard(viewer)

    # Sep 2026 has First Aid, LOPC and damage counts but no hours.
    assert data["throughMonth"] == 8
    september = data["months"][8]
    assert september["status"] == "not_reported"
    assert september["countsConfirmed"] is False
    assert september["counts"]["lopc"] == 1

    explicit = dashboard(viewer, throughMonth=9)
    lopc = kpi(explicit, "lopc")
    assert lopc["ytd"]["available"] is False
    assert lopc["ytd"]["rate"] is None
    assert lopc["ytd"]["ineligibleMonths"] == [{"year": 2026, "month": 9, "reason": "not_reported"}]


def test_damage_keeps_property_and_equipment_counts_where_available(
    accepted: InMemoryRepository, viewer: TestClient
) -> None:
    accepted.legacy[(2025, 10)]["property_equipment_damage"] = 0
    damage = kpi(dashboard(viewer), "property_equipment_damage")

    assert (damage["ytd"]["propertyDamage"], damage["ytd"]["equipmentDamageFailure"]) == (6, 7)
    assert damage["ytd"]["events"] == 6 + 7
    # The 12MRA includes 2025 months, whose workbook counts are combined only.
    assert damage["rolling"]["events"] == 15
    assert damage["rolling"]["propertyDamage"] is None
    assert damage["rolling"]["equipmentDamageFailure"] is None
    assert kpi(dashboard(viewer), "lopc")["ytd"]["propertyDamage"] is None


def test_monthly_trends_follow_the_same_windows(
    accepted: InMemoryRepository, viewer: TestClient
) -> None:
    trends = {t["measure"]: t for t in dashboard(viewer)["trends"]}

    trir = trends["trir"]
    assert trir["ytd"][7] == pytest.approx(FIXTURES[("trir", "ytd")], abs=TOLERANCE)
    assert trir["rolling"][7] == pytest.approx(FIXTURES[("trir", "rolling")], abs=TOLERANCE)
    assert trir["ytd"][0] == 0.0  # January 2026: no recordables, 21473 hours
    assert trir["ytd"][8:] == [None, None, None, None]
    assert trir["rolling"][8:] == [None, None, None, None]
    # February 2026 12MRA: March 2025 - February 2026, all closed.
    lopc_feb = (
        (sum([1, 1, 1, 1, 1, 1, 2, 1, 0, 1]) + 1 + 2)
        * 200000
        / (sum(HOURS_2025[2:]) + sum(HOURS_2026[:2]))
    )
    assert trends["lopc"]["rolling"][1] == pytest.approx(lopc_feb, abs=TOLERANCE)


def test_annual_trir_history(accepted: InMemoryRepository, viewer: TestClient) -> None:
    annual = {a["year"]: a for a in dashboard(viewer)["annualTrir"]}

    assert sorted(annual) == [2021, 2022, 2023, 2024, 2025, 2026]
    assert annual[2021]["basis"] == "annual_legacy"
    assert annual[2021]["rate"] == pytest.approx(200000 / 172301, abs=TOLERANCE)
    assert annual[2022] == {
        "year": 2022,
        "basis": None,
        "partial": False,
        "throughMonth": None,
        "events": None,
        "hours": None,
        "rate": None,
    }
    assert annual[2023]["rate"] == pytest.approx(200000 / 168563, abs=TOLERANCE)
    assert annual[2024]["rate"] == pytest.approx(200000 / 174706, abs=TOLERANCE)
    assert annual[2025]["basis"] == "monthly"
    assert annual[2025]["partial"] is False
    assert (annual[2025]["events"], annual[2025]["hours"], annual[2025]["rate"]) == (
        0,
        191751,
        0.0,
    )
    assert annual[2026]["partial"] is True
    assert annual[2026]["throughMonth"] == 8
    assert annual[2026]["rate"] == pytest.approx(FIXTURES[("trir", "ytd")], abs=TOLERANCE)


def test_annual_history_stops_at_the_selected_year(
    accepted: InMemoryRepository, viewer: TestClient
) -> None:
    annual = dashboard(viewer, year=2025)["annualTrir"]

    assert [a["year"] for a in annual] == [2021, 2022, 2023, 2024, 2025]


def test_annual_legacy_row_is_ignored_for_a_year_with_monthly_hours(
    repository: InMemoryRepository, viewer: TestClient
) -> None:
    set_hours(repository, 2025, 1, 1000)
    repository.legacy[(2025, 1)] = {"recordable": 0}
    repository.annual_rows[2025] = AnnualRecord(2025, AnnualValues(9, Decimal(1000), "test"))

    annual = {a["year"]: a for a in dashboard(viewer, year=2025)["annualTrir"]}

    assert annual[2025]["basis"] == "monthly"
    assert annual[2025]["events"] == 0


# Eligibility -----------------------------------------------------------------------


def test_open_month_is_excluded_not_treated_as_zero(
    accepted: InMemoryRepository, viewer: TestClient
) -> None:
    accepted.hour_rows[(2026, 8)] = replace(
        accepted.hour_rows[(2026, 8)],
        values=replace(accepted.hour_rows[(2026, 8)].values, month_closed=False),
    )

    data = dashboard(viewer)
    assert data["throughMonth"] == 7
    assert data["months"][7]["status"] == "reported"
    assert data["months"][7]["eligible"] is False
    assert data["months"][7]["ineligibleReason"] == "open"

    august = kpi(dashboard(viewer, throughMonth=8), "trir")
    for window in ("ytd", "rolling"):
        assert august[window]["available"] is False
        assert august[window]["events"] is None
        assert august[window]["hours"] is None
        assert august[window]["ineligibleMonths"] == [{"year": 2026, "month": 8, "reason": "open"}]


def test_rolling_average_needs_all_twelve_months(
    accepted: InMemoryRepository, viewer: TestClient
) -> None:
    del accepted.hour_rows[(2025, 9)]

    lopc = kpi(dashboard(viewer), "lopc")

    assert lopc["ytd"]["available"] is True
    assert lopc["rolling"]["available"] is False
    assert lopc["rolling"]["ineligibleMonths"] == [
        {"year": 2025, "month": 9, "reason": "not_reported"}
    ]


def test_rolling_average_unavailable_without_prior_year(
    repository: InMemoryRepository, viewer: TestClient
) -> None:
    for month, hours in enumerate(HOURS_2026, start=1):
        set_hours(repository, 2026, month, hours)

    trir = kpi(dashboard(viewer), "trir")

    assert trir["ytd"]["available"] is True
    assert [m["month"] for m in trir["rolling"]["ineligibleMonths"]] == [9, 10, 11, 12]
    assert {m["reason"] for m in trir["rolling"]["ineligibleMonths"]} == {"not_reported"}


def test_zero_hour_month_is_ineligible(repository: InMemoryRepository, viewer: TestClient) -> None:
    set_hours(repository, 2026, 1, 0)

    data = dashboard(viewer)

    assert data["throughMonth"] is None
    assert data["kpis"] == []
    assert data["ytdHours"] is None
    assert data["months"][0]["ineligibleReason"] == "zero_hours"
    explicit = kpi(dashboard(viewer, throughMonth=1), "trir")["ytd"]
    assert explicit["ineligibleMonths"] == [{"year": 2026, "month": 1, "reason": "zero_hours"}]


def test_closing_confirms_absent_counts_as_zero_only_for_closed_months(
    repository: InMemoryRepository, viewer: TestClient
) -> None:
    set_hours(repository, 2026, 1, 1000, closed=True)
    set_hours(repository, 2026, 2, 1000, closed=False)

    months = dashboard(viewer)["months"]

    assert months[0]["countsConfirmed"] is True
    assert set(months[0]["counts"].values()) == {0}
    assert months[1]["countsConfirmed"] is False
    assert set(months[1]["counts"].values()) == {None}
    assert months[2]["status"] == "not_reported"
    assert set(months[2]["counts"].values()) == {None}


def test_empty_year_has_no_kpis_and_no_history(
    repository: InMemoryRepository, viewer: TestClient
) -> None:
    data = dashboard(viewer)

    assert data["throughMonth"] is None
    assert data["kpis"] == []
    assert data["annualTrir"] == []
    assert data["yearsWithData"] == []
    assert all(m["status"] == "not_reported" for m in data["months"])


# Numerators ------------------------------------------------------------------------


def test_trir_numerator_is_recordable_injury_plus_occupational_illness() -> None:
    counts = calc.month_counts(
        calc.INCIDENTS,
        {"recordable_injury": 2, "occupational_illness": 1, "first_aid": 4},
        closed=True,
    )

    assert counts.trir == 3
    assert counts.numerator(calc.Measure.FIRST_AID) == 4
    # Lost Time Injury is a subset of recordable injuries and is never read.
    read = {key for key in calc.INCIDENT_CATEGORIES.values()}
    assert ("incident_classification", "lost_time_injury") not in read


def test_numerator_category_mappings() -> None:
    assert calc.INCIDENT_CATEGORIES == {
        "recordable_injury": ("incident_classification", "recordable_injury"),
        "occupational_illness": ("incident_classification", "occupational_illness"),
        "first_aid": ("incident_classification", "first_aid"),
        "lopc": ("lopc", "lopc"),
        "property_damage": ("incident_classification", "property_damage"),
        "equipment_damage_failure": ("incident_classification", "equipment_damage_failure"),
    }
    # The Incident module's combined "property_equipment_damage" section is not a source.
    assert ("property_equipment_damage", "property_equipment_damage") not in (
        calc.INCIDENT_CATEGORIES.values()
    )


def test_damage_numerator_adds_property_and_equipment() -> None:
    counts = calc.month_counts(
        calc.INCIDENTS, {"property_damage": 2, "equipment_damage_failure": 3}, closed=True
    )

    assert counts.property_equipment_damage == 5
    assert (counts.property_damage, counts.equipment_damage_failure) == (2, 3)


def test_open_month_counts_stay_unreported() -> None:
    counts = calc.month_counts(calc.INCIDENTS, {"lopc": 2}, closed=False)

    assert counts.lopc == 2
    assert counts.trir is None
    assert counts.first_aid is None


def test_years_before_2026_read_legacy_counts() -> None:
    assert calc.count_source(2025) == calc.PERFORMANCE_LEGACY
    assert calc.count_source(2026) == calc.INCIDENTS
    legacy = calc.month_counts(
        calc.PERFORMANCE_LEGACY, {"recordable": 1, "property_equipment_damage": 2}, closed=True
    )
    assert (legacy.trir, legacy.property_equipment_damage) == (1, 2)
    assert legacy.property_damage is None
    assert legacy.recordable_injury is None


def test_closing_a_legacy_month_does_not_turn_blank_counts_into_zero() -> None:
    partial = calc.month_counts(calc.PERFORMANCE_LEGACY, {"recordable": 0, "lopc": 1}, closed=True)
    assert (partial.trir, partial.lopc) == (0, 1)
    assert (partial.first_aid, partial.property_equipment_damage) == (None, None)
    assert partial.confirmed is False

    stored = {name: 0 for name in calc.LEGACY_CATEGORIES}
    assert calc.month_counts(calc.PERFORMANCE_LEGACY, stored, closed=True).confirmed is True
    assert calc.month_counts(calc.PERFORMANCE_LEGACY, stored, closed=False).confirmed is False


def test_a_blank_legacy_count_blocks_only_its_own_measure() -> None:
    period = (2025, 6)
    hours = {period: calc.MonthHours(Decimal(1000), True)}
    counts = {
        period: calc.month_counts(
            calc.PERFORMANCE_LEGACY, {"recordable": 0, "first_aid": 1, "lopc": 2}, closed=True
        )
    }

    damage = calc.window_rate(calc.Measure.PROPERTY_EQUIPMENT_DAMAGE, [period], hours, counts)
    lopc = calc.window_rate(calc.Measure.LOPC, [period], hours, counts)

    assert damage.rate is None
    assert damage.ineligible == (calc.IneligibleMonth(period, "count_not_confirmed"),)
    assert lopc.rate == pytest.approx(2 * 200000 / 1000, rel=TOLERANCE)


def test_rolling_window_crosses_the_year() -> None:
    assert calc.rolling_window((2026, 8))[0] == (2025, 9)
    assert calc.rolling_window((2026, 12)) == [(2026, m) for m in range(1, 13)]
    assert len(calc.rolling_window((2026, 1))) == 12
    assert calc.ytd_window((2026, 3)) == [(2026, 1), (2026, 2), (2026, 3)]


# Data entry ------------------------------------------------------------------------


def save(client: TestClient, year: int, month: int, **body: Any) -> Any:
    payload = {"totalHours": 1000, "monthClosed": False, "expectedUpdatedAt": None, **body}
    return client.put(f"{URL}/months/{year}/{month}", json=payload)


def test_year_view_shows_status_counts_and_entry_rules(
    accepted: InMemoryRepository, editor: TestClient
) -> None:
    data = editor.get(URL + "/months", params={"year": 2026}).json()

    assert data["countSource"] == "incidents"
    assert data["canEdit"] is True
    assert data["yearsWithData"] == [2026, 2025]
    august, september, october, november = data["months"][7:11]
    assert august["status"] == "closed"
    assert august["hours"]["totalHours"] == 18031
    assert august["hours"]["hourlyHours"] is None
    assert august["counts"]["trir"] == 1
    assert august["counts"]["recordableInjury"] == 1
    assert august["counts"]["occupationalIllness"] == 0
    assert september["status"] == "not_reported"
    assert september["counts"]["firstAid"] == 1
    assert (september["canEnter"], september["canClose"]) == (True, True)
    # Today (Baytown) is 7 October 2026.
    assert (october["canEnter"], october["canClose"]) == (True, False)
    assert (november["canEnter"], november["canClose"]) == (False, False)

    legacy = editor.get(URL + "/months", params={"year": 2025}).json()
    assert legacy["countSource"] == "performance_legacy"
    assert legacy["months"][9]["counts"]["firstAid"] == 1
    assert legacy["months"][9]["counts"]["propertyDamage"] is None


def test_viewer_sees_months_without_edit(accepted: InMemoryRepository, viewer: TestClient) -> None:
    assert viewer.get(URL + "/months", params={"year": 2026}).json()["canEdit"] is False


def test_save_creates_a_month_and_audits_it(
    repository: InMemoryRepository, editor: TestClient
) -> None:
    response = save(
        editor,
        2026,
        9,
        totalHours=17000.5,
        hourlyHours=12000.25,
        salaryHours=5000.25,
        monthClosed=True,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["totalHours"] == 17000.5
    assert body["monthClosed"] is True
    assert body["updatedBy"] == "tester"
    [(actor, _, change)] = repository.audit
    assert actor == "tester"
    assert (change.action, change.entity_type, change.entity_key) == (
        "create",
        "safety.performance_hours",
        "performance-hours/2026-09",
    )
    assert change.old_value is None
    assert change.new_value == {
        "total_hours": "17000.50",
        "hourly_hours": "12000.25",
        "salary_hours": "5000.25",
        "month_closed": True,
    }


def test_closing_a_month_is_an_audited_update(
    repository: InMemoryRepository, editor: TestClient
) -> None:
    set_hours(repository, 2026, 9, 17000, closed=False)

    response = save(
        editor,
        2026,
        9,
        totalHours=17000,
        monthClosed=True,
        expectedUpdatedAt=SEEDED.isoformat(),
    )

    assert response.status_code == 200, response.text
    [(_, _, change)] = repository.audit
    assert change.action == "update"
    assert change.old_value is not None and change.old_value["month_closed"] is False
    assert change.new_value is not None and change.new_value["month_closed"] is True
    assert repository.hour_rows[(2026, 9)].updated_by == "tester"


def test_unchanged_save_writes_nothing(repository: InMemoryRepository, editor: TestClient) -> None:
    set_hours(repository, 2026, 9, 17000, closed=False)

    response = save(editor, 2026, 9, totalHours=17000, expectedUpdatedAt=SEEDED.isoformat())

    assert response.status_code == 200
    assert response.json()["updatedAt"] == SEEDED.isoformat().replace("+00:00", "Z")
    assert repository.audit == []
    assert repository.commits == 0


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (True, None),  # someone else created the month
        (True, "2026-01-01T00:00:00Z"),  # someone else changed it
        (False, "2026-10-06T12:00:00Z"),  # someone else cleared it
    ],
)
def test_save_refuses_stale_edits(
    repository: InMemoryRepository, editor: TestClient, stored: bool, expected: str | None
) -> None:
    if stored:
        set_hours(repository, 2026, 9, 17000, closed=False)

    response = save(editor, 2026, 9, totalHours=1, expectedUpdatedAt=expected)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "edit_conflict"
    assert (detail["current"] is not None) is stored
    if stored:
        assert detail["current"]["totalHours"] == 17000
        assert repository.hour_rows[(2026, 9)].values.total_hours == Decimal("17000.00")
    assert repository.audit == []
    assert repository.rollbacks == 1


def test_clear_returns_a_month_to_not_reported(
    repository: InMemoryRepository, editor: TestClient
) -> None:
    set_hours(repository, 2026, 9, 17000)

    stale = editor.delete(
        f"{URL}/months/2026/9", params={"expectedUpdatedAt": "2026-01-01T00:00:00Z"}
    )
    assert stale.status_code == 409
    assert (2026, 9) in repository.hour_rows

    response = editor.delete(
        f"{URL}/months/2026/9", params={"expectedUpdatedAt": SEEDED.isoformat()}
    )

    assert response.status_code == 204
    assert (2026, 9) not in repository.hour_rows
    [(_, _, change)] = repository.audit
    assert (change.action, change.new_value) == ("delete", None)
    assert change.old_value is not None and change.old_value["month_closed"] is True


@pytest.mark.parametrize(
    "body",
    [
        {"totalHours": -1},
        {"totalHours": "1000"},
        {"totalHours": True},
        {"totalHours": None},
        {"totalHours": 10.123},
        {"totalHours": 1_000_001},
        {"totalHours": 100, "hourlyHours": 60, "salaryHours": 30},
        {"totalHours": 100, "hourlyHours": -1},
        {"monthClosed": "yes"},
        {"monthClosed": None},
        {"totalHours": 100, "hourlyHours": 50, "salaryHours": 49.99},
    ],
)
def test_invalid_hours_are_rejected(
    repository: InMemoryRepository, editor: TestClient, body: dict[str, Any]
) -> None:
    response = save(editor, 2026, 9, **body)

    assert response.status_code == 422
    assert repository.hour_rows == {}
    assert repository.audit == []


def test_breakdown_may_be_partial_or_absent(
    repository: InMemoryRepository, editor: TestClient
) -> None:
    assert save(editor, 2026, 7, totalHours=100, hourlyHours=60).status_code == 200
    assert (
        save(editor, 2026, 8, totalHours=100.5, hourlyHours=60.25, salaryHours=40.25).status_code
        == 200
    )
    assert repository.hour_rows[(2026, 7)].values.salary_hours is None


@pytest.mark.parametrize(
    ("year", "month", "closed", "error"),
    [
        (2026, 11, False, "month_not_started"),
        (2027, 1, False, "month_not_started"),
        (2026, 10, True, "month_not_ended"),
    ],
)
def test_months_follow_the_site_calendar(
    repository: InMemoryRepository,
    editor: TestClient,
    year: int,
    month: int,
    closed: bool,
    error: str,
) -> None:
    response = save(editor, year, month, monthClosed=closed)

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == error
    assert repository.hour_rows == {}


def test_current_month_can_be_entered_but_not_closed(
    repository: InMemoryRepository, editor: TestClient
) -> None:
    assert save(editor, 2026, 10).status_code == 200


def test_site_calendar_is_baytown_not_utc(
    repository: InMemoryRepository, editor: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1 November 03:00 UTC is still 31 October in Baytown: October has not ended.
    monkeypatch.setattr(
        performance_router, "_now", lambda: dt.datetime(2026, 11, 1, 3, 0, tzinfo=dt.UTC)
    )

    response = save(editor, 2026, 10, monthClosed=True)

    assert response.json()["detail"]["error"] == "month_not_ended"


# Calendar-year rollover (Baytown is UTC-6 in winter)

LAST_SECOND_OF_2026 = dt.datetime(2027, 1, 1, 5, 59, 59, tzinfo=dt.UTC)
BAYTOWN_NEW_YEAR = dt.datetime(2027, 1, 1, 6, 0, tzinfo=dt.UTC)
LAST_SECOND_OF_JANUARY_2027 = dt.datetime(2027, 2, 1, 5, 59, 59, tzinfo=dt.UTC)
BAYTOWN_FEBRUARY_2027 = dt.datetime(2027, 2, 1, 6, 0, tzinfo=dt.UTC)


def at(monkeypatch: pytest.MonkeyPatch, instant: dt.datetime) -> None:
    monkeypatch.setattr(performance_router, "_now", lambda: instant)


def test_december_2026_closes_at_baytown_midnight(
    editor: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    at(monkeypatch, LAST_SECOND_OF_2026)
    assert save(editor, 2026, 12, monthClosed=True).json()["detail"]["error"] == "month_not_ended"

    at(monkeypatch, BAYTOWN_NEW_YEAR)
    assert save(editor, 2026, 12, monthClosed=True).status_code == 200


def test_january_2027_opens_at_baytown_midnight_and_closes_on_1_february(
    editor: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    at(monkeypatch, LAST_SECOND_OF_2026)
    assert save(editor, 2027, 1).json()["detail"]["error"] == "month_not_started"

    at(monkeypatch, BAYTOWN_NEW_YEAR)
    assert save(editor, 2027, 1).status_code == 200
    months = editor.get(URL + "/months", params={"year": 2027}).json()["months"]
    assert (months[0]["canEnter"], months[0]["canClose"]) == (True, False)
    assert (months[1]["canEnter"], months[1]["canClose"]) == (False, False)

    at(monkeypatch, LAST_SECOND_OF_JANUARY_2027)
    response = save(editor, 2027, 1, monthClosed=True)
    assert response.json()["detail"]["error"] == "month_not_ended"

    at(monkeypatch, BAYTOWN_FEBRUARY_2027)
    updated_at = editor.get(URL + "/months", params={"year": 2027}).json()["months"][0]
    response = save(
        editor, 2027, 1, monthClosed=True, expectedUpdatedAt=updated_at["hours"]["updatedAt"]
    )
    assert response.status_code == 200, response.text


def test_rolling_window_for_january_2027_spans_february_2026() -> None:
    assert calc.rolling_window((2027, 1)) == [(2026, m) for m in range(2, 13)] + [(2027, 1)]
    assert calc.ytd_window((2027, 1)) == [(2027, 1)]


def test_january_2027_12mra_uses_the_eligible_2026_months(
    repository: InMemoryRepository, viewer: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for month in range(1, 13):
        set_hours(repository, 2026, month, 1000)
    set_hours(repository, 2027, 1, 1000)
    # January 2026 falls outside the window ending January 2027.
    for period in [(2026, 1), (2026, 6), (2027, 1)]:
        repository.incidents.setdefault(period, {})["recordable_injury"] = 1
    at(monkeypatch, BAYTOWN_FEBRUARY_2027)

    data = dashboard(viewer, 2027)

    assert data["throughMonth"] == 1
    trir = kpi(data, "trir")
    assert trir["ytd"]["rate"] == pytest.approx(1 * 200000 / 1000, rel=TOLERANCE)
    assert trir["rolling"]["available"] is True
    assert trir["rolling"]["ineligibleMonths"] == []
    assert trir["rolling"]["events"] == 2
    assert trir["rolling"]["rate"] == pytest.approx(2 * 200000 / 12000, rel=TOLERANCE)


def test_empty_2027_has_no_ytd_kpi_and_copies_nothing_from_2026(
    accepted: InMemoryRepository, editor: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    at(monkeypatch, BAYTOWN_NEW_YEAR)

    data = dashboard(editor, 2027)
    assert data["throughMonth"] is None
    assert data["kpis"] == []
    assert data["ytdHours"] is None
    assert 2027 not in data["yearsWithData"]

    view = editor.get(URL + "/months", params={"year": 2027}).json()
    assert view["countSource"] == "incidents"
    assert all(m["status"] == "not_reported" for m in view["months"])
    assert all(m["hours"] is None for m in view["months"])
    assert all(set(m["counts"].values()) == {None} for m in view["months"])
    assert (view["months"][0]["canEnter"], view["months"][0]["canClose"]) == (True, False)
    assert accepted.hour_rows.keys().isdisjoint({(2027, m) for m in range(1, 13)})


@pytest.mark.parametrize(("year", "month"), [(2026, 0), (2026, 13), (1999, 1), (2101, 1)])
def test_invalid_periods_are_rejected(editor: TestClient, year: int, month: int) -> None:
    assert save(editor, year, month).status_code == 422


# Authorization and availability -----------------------------------------------------


@pytest.mark.parametrize(
    ("permissions", "read", "write"),
    [
        ((P.SAFETY_PERFORMANCE_VIEW,), 200, 403),
        ((P.SAFETY_PERFORMANCE_EDIT,), 200, 200),
        ((P.SAFETY_VIEW,), 200, 403),
        ((P.SAFETY_EDIT,), 200, 200),
        ((P.SAFETY_INCIDENTS_EDIT,), 403, 403),
        ((P.SAFETY_CONTACTS_EDIT,), 403, 403),
        ((), 403, 403),
    ],
)
def test_permissions_are_enforced_server_side(
    repository: InMemoryRepository,
    permissions: tuple[Permission, ...],
    read: int,
    write: int,
) -> None:
    for client in make_client(repository, principal(*permissions)):
        assert client.get(URL + "/months", params={"year": 2026}).status_code == read
        assert client.get(URL + "/dashboard", params={"year": 2026}).status_code == read
        assert save(client, 2026, 9).status_code == write
        assert client.delete(
            f"{URL}/months/2026/9", params={"expectedUpdatedAt": NOW.isoformat()}
        ).status_code == (write if write == 403 else 204)


def test_anonymous_requests_are_refused(repository: InMemoryRepository) -> None:
    for client in make_client(repository, None):
        assert client.get(URL + "/dashboard", params={"year": 2026}).status_code == 401
        assert save(client, 2026, 9).status_code == 401


def test_database_failure_is_a_503(repository: InMemoryRepository, viewer: TestClient) -> None:
    repository.fail = OperationalError("SELECT 1", {}, Exception("down"))

    assert viewer.get(URL + "/dashboard", params={"year": 2026}).status_code == 503
    assert viewer.get(URL + "/months", params={"year": 2026}).status_code == 503


def test_missing_database_is_a_503(viewer: TestClient) -> None:
    viewer.app.dependency_overrides.pop(performance_repository)  # type: ignore[attr-defined]

    assert viewer.get(URL + "/dashboard", params={"year": 2026}).status_code == 503


# Import tooling --------------------------------------------------------------------


def _migration_0006() -> Any:
    spec = importlib.util.spec_from_file_location("migration_0006", MIGRATION_0006)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_metric_set_matches_the_calculation_mapping() -> None:
    migration = _migration_0006()

    assert migration.LEGACY_METRIC_SET == calc.PERFORMANCE_LEGACY
    seeded = {
        (section, category)
        for section, _, categories in migration.LEGACY_SECTIONS
        for category, _ in categories
    }
    assert seeded == set(calc.LEGACY_CATEGORIES.values())


def test_hours_mapping_passes_check_and_excludes_2022(capsys: pytest.CaptureFixture[str]) -> None:
    mapping = legacy_import.load_mapping(HOURS_MAPPING)

    assert legacy_import.hours_discrepancies(mapping) == []
    assert legacy_import.run("check", HOURS_MAPPING) == 0
    assert [h.total_hours for h in mapping.hours if h.year == 2025] == HOURS_2025
    assert [h.total_hours for h in mapping.hours if h.year == 2026] == HOURS_2026
    assert {(a.year, a.recordables, a.total_hours) for a in mapping.annual} == {
        (2021, 1, 172301),
        (2023, 1, 168563),
        (2024, 1, 174706),
    }
    years = {h.year for h in mapping.hours} | {a.year for a in mapping.annual}
    assert 2022 not in years
    assert [e.year for e in mapping.excluded_years] == [2022]
    assert all(h.hourly_hours is None and h.salary_hours is None for h in mapping.hours)
    assert "Excluded 2022" in capsys.readouterr().out
    assert all(h.closed_basis for h in mapping.hours if h.month_closed)
    assert all(h.year != 2026 or h.month <= 8 for h in mapping.hours)
    january = next(h for h in mapping.hours if (h.year, h.month) == (2025, 1))
    assert (january.total_hours, january.stated_in) == (15000, "Rates!M17")
    notes = " ".join(mapping.notes).lower()
    assert "estimat" not in notes
    assert "employee + contractor" not in notes


def test_legacy_counts_mapping_passes_check_and_matches_seeded_categories() -> None:
    mapping = metrics_import.load_mapping(LEGACY_MAPPING)

    assert mapping.metric_set == calc.PERFORMANCE_LEGACY
    assert mapping.year == 2025
    assert metrics_import.total_discrepancies(mapping) == []
    listed = {(s.section, c.category) for s in mapping.sections for c in s.categories}
    assert listed == set(calc.LEGACY_CATEGORIES.values())
    assert metrics_import.run("check", LEGACY_MAPPING) == 0


def test_legacy_counts_keep_source_blanks_unconfirmed() -> None:
    mapping = metrics_import.load_mapping(LEGACY_MAPPING)
    months = {c.category: c.months for s in mapping.sections for c in s.categories}

    # TRIR EXP.!L8 types 0 recordables for 2025, so every month is a proven zero.
    assert months["recordable"] == [0] * 12
    assert months["first_aid"] == [None, None, 1, 2, None, 1, 1, 1, None, 1, None, 0]
    assert months["lopc"] == [3, 0, 1, 1, 1, 1, 1, 1, 2, 1, 0, 1]
    # Rates!I28 (December equipment failure = 1) is excluded: December stays the typed 0.
    assert months["property_equipment_damage"] == [2, None, 2, 1, 1, 1, 3, 2, 1, None, 1, 0]
    assert any("EXCLUDED" in note and "Rates!I28" in note for note in mapping.notes)


def test_plan_and_apply_insert_once_and_audit(repository: InMemoryRepository) -> None:
    mapping = legacy_import.load_mapping(HOURS_MAPPING)

    plan = legacy_import.plan_import(repository, mapping, today=NOW.date())
    assert (len(plan.hours), len(plan.annual), plan.blocking) == (20, 3, [])
    change_set = legacy_import.apply_plan(repository, plan, now=SEEDED)

    assert len(repository.hour_rows) == 20
    assert all(r.values.month_closed for r in repository.hour_rows.values())
    assert sorted(repository.annual_rows) == [2021, 2023, 2024]
    assert len(repository.audit) == 23
    assert {(actor, cs) for actor, cs, _ in repository.audit} == {("legacy-import", change_set)}
    keys = {c.entity_key for _, _, c in repository.audit}
    assert "performance-hours/2026-08" in keys
    assert "performance-annual-legacy/2021" in keys
    january = next(c for _, _, c in repository.audit if c.entity_key == "performance-hours/2025-01")
    assert january.new_value is not None
    assert january.new_value["stated_in"] == "Rates!M17"
    assert str(january.new_value["closed_basis"]).startswith("2025 hours final")

    again = legacy_import.plan_import(repository, mapping, today=NOW.date())
    assert (again.hours, again.annual, again.unchanged, again.blocking) == ([], [], 23, [])


def test_plan_blocks_on_differing_rows_and_never_overwrites(
    repository: InMemoryRepository,
) -> None:
    set_hours(repository, 2026, 8, 18000)
    set_hours(repository, 2024, 1, 100)
    mapping = legacy_import.load_mapping(HOURS_MAPPING)

    plan = legacy_import.plan_import(repository, mapping, today=NOW.date())

    assert len(plan.blocking) == 2
    assert plan.blocking[0].startswith("2026-08: stored")
    assert plan.blocking[1].startswith("2024: monthly hours are stored")
    assert repository.hour_rows[(2026, 8)].values.total_hours == Decimal("18000.00")


def test_plan_blocks_closing_a_month_that_has_not_ended(
    repository: InMemoryRepository,
) -> None:
    mapping = legacy_import.PerformanceMapping.model_validate(
        {
            "source": "test",
            "hours": [
                {
                    "year": 2026,
                    "month": 10,
                    "totalHours": 1,
                    "monthClosed": True,
                    "statedIn": "x",
                    "closedBasis": "x",
                }
            ],
        }
    )

    plan = legacy_import.plan_import(repository, mapping, today=NOW.date())

    assert plan.blocking == ["2026-10: closed in the file but the month has not ended"]


CLOSED_ENTRY = {
    "year": 2025,
    "month": 1,
    "totalHours": 10,
    "monthClosed": True,
    "statedIn": "x",
    "closedBasis": "x",
}


def _mapping(**overrides: Any) -> dict[str, Any]:
    return {"source": "test", "hours": [CLOSED_ENTRY], **overrides}


@pytest.mark.parametrize(
    "data",
    [
        _mapping(hours=[_mapping()["hours"][0], _mapping()["hours"][0]]),
        _mapping(annual=[{"year": 2025, "recordables": 0, "totalHours": 1, "source": "x"}]),
        _mapping(excludedYears=[{"year": 2025, "reason": "x"}]),
        _mapping(annual=[{"year": 2024, "recordables": -1, "totalHours": 1, "source": "x"}]),
        _mapping(annual=[{"year": 2024, "recordables": 0, "totalHours": 0, "source": "x"}]),
        _mapping(hours=[{**CLOSED_ENTRY, "hourlyHours": 6, "salaryHours": 5}]),
        _mapping(hours=[{k: v for k, v in CLOSED_ENTRY.items() if k != "closedBasis"}]),
        _mapping(hours=[{**CLOSED_ENTRY, "monthClosed": False}]),
        _mapping(unexpected=True),
    ],
)
def test_invalid_hours_mappings_are_rejected(data: dict[str, Any], tmp_path: Path) -> None:
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    assert legacy_import.run("check", path) == 2


def test_check_reports_stated_total_discrepancies(tmp_path: Path) -> None:
    data = _mapping(
        expectedHours=[{"year": 2025, "throughMonth": 2, "totalHours": 10, "statedIn": "x"}]
    )
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    assert legacy_import.run("check", path) == 1
