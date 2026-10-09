"""Incident & Near Miss Analytics: calculations and the read-only API.

Section and category definitions come from migration 0003 and the 2026 values
from the approved import mapping, so no workbook value is retyped here and the
workbook is never read. Uses an in-memory repository (test double only).
"""

import datetime as dt
import importlib.util
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, NoReturn

import pytest
from fastapi.testclient import TestClient
from principals import as_user
from sqlalchemy.exc import OperationalError

from app.core.authorization import UserPrincipal, get_user_principal
from app.core.permissions import Permission
from app.main import create_app
from app.safety import analytics
from app.safety import router as safety_router
from app.safety.analytics import MonthNotStartedError, available_years, latest_started_month
from app.safety.behavior.repository import BehaviorCategoryDefinition
from app.safety.legacy_import import load_mapping
from app.safety.repository import CategoryDefinition, SectionDefinition, StoredValues
from app.safety.router import behavior_repository, safety_repository
from app.safety.schemas import IncidentAnalyticsResponse

URL = "/api/v1/safety/incidents/analytics"
API_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_0003 = next((API_ROOT / "alembic" / "versions").glob("*-0003_*.py"))
APPROVED_2026 = API_ROOT / "import_templates" / "safety_incidents_2026_lcy_ehs.mapping.json"

# Baytown is UTC-5 in October (CDT) and UTC-6 in winter (CST).
OCTOBER_8_2026 = dt.datetime(2026, 10, 8, 15, 0, tzinfo=dt.UTC)


def seeded_sections() -> list[SectionDefinition]:
    spec = importlib.util.spec_from_file_location("migration_0003", MIGRATION_0003)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sections = []
    for index, (code, name, categories) in enumerate(module.INCIDENT_SECTIONS, start=1):
        sections.append(
            SectionDefinition(
                id=index,
                code=code,
                name=name,
                categories=tuple(
                    CategoryDefinition(id=index * 100 + row, code=c, name=n)
                    for row, (c, n) in enumerate(categories, start=1)
                ),
            )
        )
    return sections


SECTIONS = seeded_sections()
IDS = {(s.code, c.code): c.id for s in SECTIONS for c in s.categories}


def approved_2026() -> dict[tuple[int, int, int], int]:
    mapping = load_mapping(APPROVED_2026)
    assert mapping.year == 2026
    return {
        (IDS[(s.section, c.category)], 2026, month): value
        for s in mapping.sections
        for c in s.categories
        for month, value in enumerate(c.months, start=1)
        if value is not None
    }


class ReadOnlyRepository:
    """Serves stored values; any write, lock or audit fails the test."""

    def __init__(self, stored: dict[tuple[int, int, int], int] | None = None) -> None:
        # (category_id, year, month) -> value
        self.stored = dict(stored or {})

    def sections(self, metric_set: str) -> list[SectionDefinition]:
        return SECTIONS if metric_set == "incidents" else []

    def values(self, category_ids: Sequence[int], year: int) -> StoredValues:
        return {
            (category, month): value
            for (category, y, month), value in self.stored.items()
            if y == year and category in category_ids
        }

    def years_with_values(self, category_ids: Sequence[int]) -> list[int]:
        return sorted({y for (category, y, _) in self.stored if category in category_ids})

    def _refuse(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise AssertionError("analytics must not write, lock, audit or commit")

    lock_year = write = record_audit = commit = rollback = _refuse


def cells(year: int, **values: dict[int, int]) -> dict[tuple[int, int, int], int]:
    """values: "section__category" -> {month: value}."""
    stored = {}
    for key, months in values.items():
        section, category = key.split("__")
        for month, value in months.items():
            stored[(IDS[(section, category)], year, month)] = value
    return stored


def load(
    repository: ReadOnlyRepository,
    *,
    year: int = 2026,
    through: int | None = 9,
    now: dt.datetime = OCTOBER_8_2026,
) -> IncidentAnalyticsResponse:
    return analytics.load_analytics(repository, year=year, through_month=through, now=now)


def kpis(result: IncidentAnalyticsResponse) -> dict[str, int | None]:
    return {kpi.key: kpi.value for kpi in result.kpis}


# Approved 2026 values ------------------------------------------------------------


def test_approved_2026_totals_through_september() -> None:
    result = load(ReadOnlyRepository(approved_2026()))

    assert result.through_month == 9
    assert kpis(result) == {
        "incidents": 41,
        "near_misses": 31,
        "lopc": 14,
        "psif": 5,
        "pit": 9,
        "combined_damage": 14,
    }
    assert result.property_damage.total == 6
    assert result.equipment_damage.total == 8
    assert result.combined_damage.total == 14
    assert result.pit.total == 9


def test_incident_may_is_the_approved_platform_value() -> None:
    result = load(ReadOnlyRepository(approved_2026()))

    assert result.incidents.values == [5, 6, 5, 6, 3, 4, 5, 3, 4]


def test_classifications_are_not_forced_to_equal_incidents() -> None:
    result = load(ReadOnlyRepository(approved_2026()))

    classified = sum(row.total or 0 for row in result.classifications)
    assert result.incidents.total == 41
    assert classified != 41

    # One incident carrying two classifications stays one incident.
    one = load(
        ReadOnlyRepository(
            cells(
                2026,
                incident_near_miss_totals__incident={1: 1},
                incident_classification__first_aid={1: 1},
                incident_classification__property_damage={1: 1},
            )
        ),
        through=1,
    )
    assert one.incidents.total == 1
    totals = {row.code: row.total for row in one.classifications}
    assert totals["first_aid"] == totals["property_damage"] == 1


def test_classifications_use_the_configured_categories_and_labels_then_psif() -> None:
    result = load(ReadOnlyRepository(approved_2026()))

    expected = [
        (c.code, c.name)
        for s in SECTIONS
        if s.code == "incident_classification"
        for c in s.categories
    ] + [("psif", "PSIF")]
    assert [(row.code, row.name) for row in result.classifications] == expected
    # The workbook's unused "Recordable " row was never a category.
    assert all(row.name.strip() == row.name for row in result.classifications)
    assert "recordable" not in {row.code for row in result.classifications}


# Duplicates are never added --------------------------------------------------------


def test_lopc_is_the_lopc_series_and_is_not_added_to_spill_release() -> None:
    repository = ReadOnlyRepository(
        cells(2026, lopc__lopc={1: 1}, incident_classification__spill_release={1: 3})
    )

    result = load(repository, through=1)

    assert (result.lopc.section, result.lopc.code, result.lopc.total) == ("lopc", "lopc", 1)
    assert kpis(result)["lopc"] == 1
    spill = next(row for row in result.classifications if row.code == "spill_release")
    assert spill.total == 3


def test_approved_lopc_is_14_not_28() -> None:
    result = load(ReadOnlyRepository(approved_2026()))

    spill = next(row for row in result.classifications if row.code == "spill_release")
    assert (result.lopc.total, spill.total) == (14, 14)
    assert kpis(result)["lopc"] == 14


def test_pit_is_the_pit_accident_classification_and_the_pit_section_is_not_read() -> None:
    repository = ReadOnlyRepository(
        cells(2026, incident_classification__pit_accident={1: 2}, pit__pit={1: 5})
    )

    result = load(repository, through=1)

    assert (result.pit.section, result.pit.code, result.pit.total) == (
        "incident_classification",
        "pit_accident",
        2,
    )
    assert analytics.PIT == ("incident_classification", "pit_accident")
    assert "pit" not in {row.section for row in result.classifications}
    assert kpis(result)["pit"] == 2


def test_approved_pit_kpi_is_9_and_not_doubled_by_the_pit_section() -> None:
    stored = approved_2026()
    pit_section = sum(v for (c, _, m), v in stored.items() if c == IDS[("pit", "pit")] and m <= 9)

    result = load(ReadOnlyRepository(stored))

    pit = next(kpi for kpi in result.kpis if kpi.key == "pit")
    # January, March and August are blank in the approved values.
    assert (pit.value, pit.months_reported, pit.complete, pit.parts) == (9, 6, False, [])
    # Adding the duplicate pit section would give 9 + its own total.
    assert pit_section > 0
    assert pit.value != 9 + pit_section


def damage_kpi(result: IncidentAnalyticsResponse) -> Any:
    return next(kpi for kpi in result.kpis if kpi.key == "combined_damage")


def test_approved_damage_kpi_is_6_property_plus_8_equipment() -> None:
    damage = damage_kpi(load(ReadOnlyRepository(approved_2026())))

    # Both classifications have blank months in the approved values, so the
    # total adds the reported months and is not presented as complete: only
    # January has both parts reported.
    assert damage.model_dump() == {
        "key": "combined_damage",
        "value": 14,
        "months_reported": 1,
        "through_month": 9,
        "complete": False,
        "parts": [
            {
                "code": "property_damage",
                "name": "Property Damage",
                "value": 6,
                "complete": False,
            },
            {
                "code": "equipment_damage_failure",
                "name": "Equipment Damage / Failure",
                "value": 8,
                "complete": False,
            },
        ],
        "prior_year": None,
    }


def test_damage_kpi_ignores_the_stale_property_equipment_damage_section() -> None:
    repository = ReadOnlyRepository(
        cells(
            2026,
            incident_classification__property_damage={1: 1},
            incident_classification__equipment_damage_failure={1: 2},
            property_equipment_damage__property_equipment_damage={1: 50},
        )
    )

    damage = damage_kpi(load(repository, through=1))

    assert (damage.value, damage.complete) == (3, True)
    assert [part.code for part in damage.parts] == ["property_damage", "equipment_damage_failure"]


def test_damage_kpi_is_partial_when_a_component_has_unreported_months() -> None:
    repository = ReadOnlyRepository(
        cells(
            2026,
            incident_classification__property_damage={1: 1, 2: 2},
            incident_classification__equipment_damage_failure={1: 0},
        )
    )

    damage = damage_kpi(load(repository, through=2))

    # The reported months are added but the total is never presented as complete.
    assert (damage.value, damage.months_reported, damage.complete) == (3, 1, False)
    assert [(p.value, p.complete) for p in damage.parts] == [(3, True), (0, False)]


def test_damage_kpi_with_one_component_never_reported() -> None:
    repository = ReadOnlyRepository(
        cells(2026, incident_classification__property_damage={1: 4, 2: 0})
    )

    damage = damage_kpi(load(repository, through=2))

    assert (damage.value, damage.months_reported, damage.complete) == (4, 0, False)
    assert [(p.value, p.complete) for p in damage.parts] == [(4, True), (None, False)]


def test_damage_kpi_reported_zeros_are_zero() -> None:
    repository = ReadOnlyRepository(
        cells(
            2026,
            incident_classification__property_damage={1: 0},
            incident_classification__equipment_damage_failure={1: 0},
        )
    )

    damage = damage_kpi(load(repository, through=1))

    assert (damage.value, damage.complete) == (0, True)


@pytest.mark.parametrize(
    ("through", "pit", "damage", "property_damage", "equipment_damage"),
    [
        # January PIT is blank in the approved values: not reported, not 0.
        (1, None, 1, 1, 0),
        (5, 5, 9, 4, 5),
        (9, 9, 14, 6, 8),
    ],
)
def test_pit_and_damage_kpis_follow_the_through_month(
    through: int,
    pit: int | None,
    damage: int,
    property_damage: int,
    equipment_damage: int,
) -> None:
    result = load(ReadOnlyRepository(approved_2026()), through=through)

    assert kpis(result)["pit"] == pit
    assert kpis(result)["combined_damage"] == damage
    assert [part.value for part in damage_kpi(result).parts] == [
        property_damage,
        equipment_damage,
    ]


def test_combined_damage_is_property_plus_equipment_damage() -> None:
    repository = ReadOnlyRepository(
        cells(
            2026,
            incident_classification__property_damage={1: 1, 2: 3},
            incident_classification__equipment_damage_failure={1: 2, 4: 0},
            # The stale combined section is never read.
            property_equipment_damage__property_equipment_damage={1: 99, 2: 99},
        )
    )

    result = load(repository, through=4)

    assert result.property_damage.values == [1, 3, None, None]
    assert result.equipment_damage.values == [2, None, None, 0]
    assert result.combined_damage.values == [3, 3, None, 0]
    assert result.combined_damage.total == 6
    # A month is reported for combined damage only when both parts are.
    assert result.combined_damage.unreported_months == [2, 3, 4]
    assert result.combined_damage.complete is False


# Null, partial and empty -------------------------------------------------------------


def test_unreported_months_are_null_and_reported_zeros_are_zero() -> None:
    repository = ReadOnlyRepository(cells(2026, psif__psif={2: 0}))

    result = load(repository, through=3)

    assert result.psif.values == [None, 0, None]
    assert result.psif.total == 0
    assert result.psif.months_reported == 1
    assert result.incidents.values == [None, None, None]
    assert result.incidents.total is None
    assert kpis(result) == {
        "incidents": None,
        "near_misses": None,
        "lopc": None,
        "psif": 0,
        "pit": None,
        "combined_damage": None,
    }


def test_partial_year_completeness() -> None:
    result = load(ReadOnlyRepository(approved_2026()))
    by_key = {kpi.key: kpi for kpi in result.kpis}

    assert by_key["incidents"].model_dump() == {
        "key": "incidents",
        "value": 41,
        "months_reported": 9,
        "through_month": 9,
        "complete": True,
        "parts": [],
        "prior_year": None,
    }
    assert (by_key["near_misses"].months_reported, by_key["near_misses"].complete) == (7, False)
    assert result.near_misses.unreported_months == [2, 3]
    assert result.lopc.unreported_months == [5]
    assert by_key["psif"].complete is False


def test_the_current_month_counts_as_unreported_until_entered() -> None:
    result = load(ReadOnlyRepository(approved_2026()), through=None)

    assert (result.through_month, result.latest_month) == (10, 10)
    assert len(result.incidents.values) == 10
    assert result.incidents.values[9] is None
    assert result.incidents.total == 41
    assert result.incidents.complete is False
    assert result.incidents.unreported_months == [10]


def test_an_empty_year_is_null_and_never_borrows_2026() -> None:
    january_2027 = dt.datetime(2027, 1, 15, 18, 0, tzinfo=dt.UTC)

    result = load(ReadOnlyRepository(approved_2026()), year=2027, through=None, now=january_2027)

    assert (result.year, result.through_month, result.latest_month) == (2027, 1, 1)
    assert result.available_years == [2027, 2026]
    assert all(kpi.value is None and kpi.months_reported == 0 for kpi in result.kpis)
    assert all(kpi.complete is False for kpi in result.kpis)
    assert [kpi.key for kpi in result.kpis][-2:] == ["pit", "combined_damage"]
    assert [(p.value, p.complete) for p in damage_kpi(result).parts] == [
        (None, False),
        (None, False),
    ]
    every = [
        result.incidents,
        result.near_misses,
        result.lopc,
        result.psif,
        result.pit,
        result.property_damage,
        result.equipment_damage,
        result.combined_damage,
        *result.classifications,
    ]
    assert all(s.values == [None] and s.total is None for s in every)


def test_a_year_with_no_rows_needs_no_seed_rows() -> None:
    result = load(
        ReadOnlyRepository(), year=2026, through=12, now=dt.datetime(2027, 3, 1, tzinfo=dt.UTC)
    )

    assert result.incidents.values == [None] * 12
    assert result.available_years == [2027, 2026]


# Site calendar ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("instant", "year", "latest"),
    [
        ("2026-11-01T04:59:00+00:00", 2026, 10),  # 23:59 CDT, 31 October
        ("2026-11-01T05:00:00+00:00", 2026, 11),  # 00:00 CDT, 1 November
        ("2027-01-01T05:59:00+00:00", 2026, 12),  # 23:59 CST, 31 December
        ("2027-01-01T05:59:00+00:00", 2027, None),
        ("2027-01-01T06:00:00+00:00", 2027, 1),  # 00:00 CST, 1 January
        ("2027-01-01T06:00:00+00:00", 2026, 12),
    ],
)
def test_months_follow_the_baytown_calendar(instant: str, year: int, latest: int | None) -> None:
    now = dt.datetime.fromisoformat(instant)
    result = load(ReadOnlyRepository(), year=year, through=None, now=now)

    assert result.latest_month == latest
    assert result.through_month == latest


def test_a_future_year_has_no_months() -> None:
    result = load(
        ReadOnlyRepository(approved_2026()),
        year=2027,
        through=None,
        now=dt.datetime(2027, 1, 1, 5, 59, tzinfo=dt.UTC),
    )

    assert result.through_month is None
    assert result.incidents.values == []
    assert result.incidents.total is None
    assert result.available_years == [2026]


def test_a_through_month_that_has_not_started_is_refused() -> None:
    with pytest.raises(MonthNotStartedError) as error:
        load(ReadOnlyRepository(), through=11)
    assert error.value.latest_month == 10

    with pytest.raises(MonthNotStartedError):
        load(ReadOnlyRepository(), year=2027, through=1)


def test_available_years_start_in_2026_and_include_the_site_year() -> None:
    assert available_years(dt.date(2026, 10, 8), [2025, 2026]) == [2026]
    assert available_years(dt.date(2028, 1, 1), [2026]) == [2028, 2027, 2026]
    assert latest_started_month(2025, dt.date(2026, 1, 1)) == 12


# API -----------------------------------------------------------------------------


principal = as_user
DASHBOARD = (Permission.SAFETY_RECORD_VIEW, Permission.SAFETY_DASHBOARD_VIEW)


class NoBehavior:
    """A Behavior repository with no categories or counts; reads only."""

    def categories(self) -> list[BehaviorCategoryDefinition]:
        return []

    def counts(self, year: int) -> dict[int, int]:
        return {}


def make_client(repository: ReadOnlyRepository, user: UserPrincipal | None) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[safety_repository] = lambda: repository
    app.dependency_overrides[behavior_repository] = NoBehavior
    if user is not None:
        app.dependency_overrides[get_user_principal] = lambda: user
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(safety_router, "_now", lambda: OCTOBER_8_2026)


@pytest.fixture
def viewer() -> Iterator[TestClient]:
    yield from make_client(ReadOnlyRepository(approved_2026()), principal(*DASHBOARD))


def test_get_returns_typed_analytics(viewer: TestClient) -> None:
    response = viewer.get(URL, params={"year": 2026, "through": 9})

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "year",
        "throughMonth",
        "latestMonth",
        "availableYears",
        "kpis",
        "incidents",
        "nearMisses",
        "classifications",
        "lopc",
        "psif",
        "pit",
        "propertyDamage",
        "equipmentDamage",
        "combinedDamage",
        "incidentsByArea",
        "nearMissesByArea",
        "incidentAreaMonthly",
        "nearMissAreaMonthly",
        "areaReconciliation",
        "priorYear",
        "incidentsPriorYearMonthly",
        "incidentsPriorYearAvailable",
        "lopcPriorYearMonthly",
        "lopcPriorYearAvailable",
        "lopcContributingFactors",
        "lopcFactorReconciliation",
        "nearMissPotential",
        "nearMissCause",
        "injuryCause",
        "bodyPart",
        "injuryReconciliation",
        "behavior",
    }
    assert (data["year"], data["throughMonth"], data["latestMonth"]) == (2026, 9, 10)
    assert data["availableYears"] == [2026]
    assert data["kpis"][0] == {
        "key": "incidents",
        "value": 41,
        "monthsReported": 9,
        "throughMonth": 9,
        "complete": True,
        "parts": [],
        "priorYear": None,
    }
    # No Behavior counts are stored here; the denominator is still the full-year total.
    behavior = data["behavior"]
    assert (behavior["available"], behavior["categories"], behavior["totalTags"]) == (
        False,
        [],
        None,
    )
    assert behavior["incidentReports"] == 41
    assert data["incidentsPriorYearAvailable"] is False
    assert [kpi["key"] for kpi in data["kpis"]] == [
        "incidents",
        "near_misses",
        "lopc",
        "psif",
        "pit",
        "combined_damage",
    ]
    assert data["kpis"][4]["value"] == 9
    damage = data["kpis"][5]
    assert (damage["value"], damage["monthsReported"], damage["complete"]) == (14, 1, False)
    assert [(p["code"], p["value"]) for p in damage["parts"]] == [
        ("property_damage", 6),
        ("equipment_damage_failure", 8),
    ]
    assert data["nearMisses"]["values"][1] is None
    assert data["pit"]["total"] == 9


def test_get_defaults_to_the_latest_started_month(viewer: TestClient) -> None:
    data = viewer.get(URL, params={"year": 2026}).json()

    assert data["throughMonth"] == 10
    assert len(data["incidents"]["values"]) == 10


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"year": ""},
        {"year": "abc"},
        {"year": 1999},
        {"year": 2101},
        {"year": 2026, "through": 0},
        {"year": 2026, "through": 13},
        {"year": 2026, "through": "x"},
        {"year": 2026, "through": 1.5},
    ],
)
def test_get_rejects_invalid_parameters(viewer: TestClient, params: dict[str, Any]) -> None:
    assert viewer.get(URL, params=params).status_code == 422


def test_get_refuses_a_through_month_that_has_not_started(viewer: TestClient) -> None:
    response = viewer.get(URL, params={"year": 2026, "through": 11})

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "error": "month_not_started",
        "message": "Analytics cannot run through a month that has not started.",
        "latestMonth": 10,
    }


def test_a_future_year_without_through_is_empty_not_an_error(viewer: TestClient) -> None:
    data = viewer.get(URL, params={"year": 2027}).json()

    assert (data["throughMonth"], data["latestMonth"]) == (None, None)
    assert data["incidents"]["values"] == []


def test_view_permission_is_required() -> None:
    repository = ReadOnlyRepository(approved_2026())
    for client in make_client(repository, None):
        assert client.get(URL, params={"year": 2026}).status_code == 401
    for client in make_client(repository, principal(Permission.SAFETY_RECORD_VIEW)):
        response = client.get(URL, params={"year": 2026})
        assert response.status_code == 403
        assert response.json()["detail"]["error"] == "permission_denied"


def test_the_get_writes_and_audits_nothing(viewer: TestClient) -> None:
    # ReadOnlyRepository fails on any lock, write, audit, commit or rollback.
    assert viewer.get(URL, params={"year": 2026}).status_code == 200


def test_database_errors_are_reported_as_unavailable() -> None:
    class Unavailable(ReadOnlyRepository):
        def sections(self, metric_set: str) -> list[SectionDefinition]:
            raise OperationalError("SELECT", {}, Exception("down"))

    for client in make_client(Unavailable(), principal(*DASHBOARD)):
        response = client.get(URL, params={"year": 2026})
        assert response.status_code == 503
        assert response.json()["detail"]["error"] == "database_unavailable"
