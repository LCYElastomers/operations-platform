"""Annual Behavior tagging: taxonomy, 2026 mapping, Pareto, saves and the API.

The taxonomy comes from migration 0008 and the counts from the approved 2026
mapping, so no workbook value is retyped here. Uses in-memory repositories
(test doubles only).
"""

import datetime as dt
import importlib.util
import json
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from principals import as_user

from app.core.authorization import UserPrincipal, get_user_principal
from app.core.permissions import Permission
from app.main import create_app
from app.safety import analytics
from app.safety import router as safety_router
from app.safety.behavior import legacy_import as behavior_import
from app.safety.behavior import service
from app.safety.behavior.legacy_import import BehaviorMapping, load_mapping, plan_import
from app.safety.behavior.models import AnnualBehaviorCount
from app.safety.behavior.repository import BehaviorCategoryDefinition
from app.safety.behavior.schemas import BehaviorChange
from app.safety.behavior.service import BehaviorConflictError, UnknownBehaviorCategoryError
from app.safety.legacy_import import LEGACY_IMPORT_ACTOR
from app.safety.repository import CategoryDefinition, SectionDefinition, StoredValues
from app.safety.router import behavior_repository, safety_repository

API_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = API_ROOT / "import_templates"
BEHAVIOR_2026 = TEMPLATES / "safety_behavior_2026_lcy_ehs.mapping.json"
INCIDENTS_2026 = TEMPLATES / "safety_incidents_2026_lcy_ehs.mapping.json"
URL = "/api/v1/safety/incidents/behavior"
ANALYTICS_URL = "/api/v1/safety/incidents/analytics"
NOW = dt.datetime(2026, 10, 8, 15, 0, tzinfo=dt.UTC)


def migration_0008() -> ModuleType:
    path = next((API_ROOT / "alembic" / "versions").glob("*-0008_*.py"))
    spec = importlib.util.spec_from_file_location("migration_0008", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M0008 = migration_0008()
CATEGORIES = [
    BehaviorCategoryDefinition(id=order, code=code, name=name, display_order=order)
    for order, (code, name) in enumerate(M0008.BEHAVIOR_CATEGORIES, start=1)
]
IDS = {c.code: c.id for c in CATEGORIES}
MAPPING = load_mapping(BEHAVIOR_2026)


def incident_months_2026() -> list[int | None]:
    data = json.loads(INCIDENTS_2026.read_text(encoding="utf-8"))
    totals = next(s for s in data["sections"] if s["section"] == "incident_near_miss_totals")
    return next(c["months"] for c in totals["categories"] if c["category"] == "incident")


class InMemoryBehavior:
    """Test double for BehaviorRepository."""

    def __init__(self, stored: dict[tuple[int, int], int] | None = None) -> None:
        self.stored = dict(stored or {})
        self.audit: list[tuple[str, Any]] = []
        self.commits = 0

    def categories(self) -> list[BehaviorCategoryDefinition]:
        return CATEGORIES

    def counts(self, year: int) -> dict[int, int]:
        return {cid: value for (cid, y), value in self.stored.items() if y == year}

    def years_with_counts(self) -> list[int]:
        return sorted({y for _, y in self.stored})

    def lock_year(self, year: int) -> None:
        pass

    def write(
        self, *, year: int, upserts: dict[int, int], deletes: Any, actor_id: str, at: Any
    ) -> None:
        for cid, value in upserts.items():
            self.stored[(cid, year)] = value
        for cid in deletes:
            self.stored.pop((cid, year), None)

    def record_audit(self, *, actor_id: str, change_set_id: Any, at: Any, changes: Any) -> None:
        self.audit.extend((actor_id, change) for change in changes)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass


class IncidentTotals:
    """Test double for SafetyMetricsRepository with only the Incident total."""

    INCIDENT_ID = 1

    def __init__(self, months: dict[int, list[int | None]]) -> None:
        self.months = months

    def sections(self, metric_set: str) -> list[SectionDefinition]:
        if metric_set != "incidents":
            return []
        incident = CategoryDefinition(id=self.INCIDENT_ID, code="incident", name="Incident")
        return [
            SectionDefinition(
                id=1, code="incident_near_miss_totals", name="Totals", categories=(incident,)
            )
        ]

    def values(self, category_ids: Any, year: int) -> StoredValues:
        if self.INCIDENT_ID not in category_ids:
            return {}
        months = self.months.get(year, [])
        return {(self.INCIDENT_ID, m): v for m, v in enumerate(months, start=1) if v is not None}

    def years_with_values(self, category_ids: Any) -> list[int]:
        return sorted(self.months)


def imported_2026() -> InMemoryBehavior:
    repository = InMemoryBehavior()
    plan = plan_import(repository, MAPPING)
    service.save_counts(
        repository, year=2026, changes=plan.changes, actor_id=LEGACY_IMPORT_ACTOR, now=NOW
    )
    return repository


def pareto_2026() -> Any:
    repository = imported_2026()
    return service.build_pareto(
        year=2026,
        categories=CATEGORIES,
        counts=repository.counts(2026),
        incident_months=incident_months_2026(),
    )


# Taxonomy ---------------------------------------------------------------------------


def test_the_full_taxonomy_is_seeded_in_workbook_order() -> None:
    assert [code for code, _ in M0008.BEHAVIOR_CATEGORIES] == [
        "pre_post_job_inspection",
        "communications_of_hazards",
        "eyes_on_path",
        "knowledge_of_task",
        "line_of_fire",
        "pinch_points",
        "energy_isolation",
        "get_assistance",
        "housekeeping",
        "walking_working_surfaces",
        "ppe_eye",
        "ppe_hands",
        "eyes_on_task",
        "hot_work",
        "tool_equipment_selection",
        "ascending_descending",
        "ppe_respiratory",
        "tool_use",
        "lifting_lowering",
        "twisting",
        "pushing_pulling",
        "ppe_body",
        "temp_extreme",
        "confined_space",
    ]


def test_display_names_keep_workbook_labels_and_provenance_keeps_the_originals() -> None:
    names = dict(M0008.BEHAVIOR_CATEGORIES)
    labels = {c.category: c.source_label for c in MAPPING.categories}
    assert names["ppe_respiratory"] == "PPE Respiratory"
    assert labels["ppe_respiratory"] == "PPE Respiritory"
    assert names["pushing_pulling"] == "Pushing & Pulling"
    assert labels["pushing_pulling"] == "Pushing & Pulling "
    # Every other display name is the workbook label as is.
    differs = {code for code, name in names.items() if labels[code] != name}
    assert differs == {"ppe_respiratory", "pushing_pulling"}


def test_storage_is_annual_and_has_no_month() -> None:
    columns = set(AnnualBehaviorCount.__table__.columns.keys())
    assert "reporting_year" in columns
    assert not any("month" in column for column in columns)


# Mapping ----------------------------------------------------------------------------


def test_mapping_covers_every_category_once_for_2026() -> None:
    assert MAPPING.year == 2026
    assert [c.category for c in MAPPING.categories] == list(IDS)
    assert any("2025" in note and "2026" in note for note in MAPPING.notes)
    assert MAPPING.stated_incident_reports is not None
    assert "2025" in MAPPING.stated_incident_reports.stated_in


def test_mapping_holds_the_ten_populated_counts_and_leaves_blanks_null() -> None:
    values = {c.category: c.value for c in MAPPING.categories}
    populated = {code: value for code, value in values.items() if value is not None}
    assert populated == {
        "eyes_on_path": 12,
        "pre_post_job_inspection": 9,
        "communications_of_hazards": 4,
        "knowledge_of_task": 4,
        "energy_isolation": 4,
        "pinch_points": 3,
        "get_assistance": 3,
        "line_of_fire": 2,
        "ppe_hands": 2,
        "ppe_eye": 1,
    }
    assert sum(populated.values()) == 44
    assert MAPPING.expected_total is not None and MAPPING.expected_total.value == 44
    assert sum(1 for value in values.values() if value is None) == 14
    assert 0 not in values.values()


def test_check_passes_and_a_disagreeing_stated_total_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert behavior_import.run("check", BEHAVIOR_2026) == 0

    data = json.loads(BEHAVIOR_2026.read_text(encoding="utf-8"))
    data["expectedTotal"]["value"] = 45
    BehaviorMapping.model_validate(data)
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(data), encoding="utf-8")
    assert behavior_import.run("check", changed) == 1
    assert "DISCREPANCY total: workbook states 45" in capsys.readouterr().out


def test_import_is_idempotent_and_never_writes_blanks() -> None:
    repository = InMemoryBehavior()
    first = plan_import(repository, MAPPING)
    assert (len(first.changes), first.unchanged, first.unreported) == (10, 0, 14)

    service.save_counts(
        repository, year=2026, changes=first.changes, actor_id=LEGACY_IMPORT_ACTOR, now=NOW
    )
    again = plan_import(repository, MAPPING)
    assert (len(again.changes), again.unchanged, again.unreported, again.differing) == (
        0,
        10,
        14,
        [],
    )
    stored = repository.counts(2026)
    assert len(stored) == 10
    assert sum(stored.values()) == 44
    for code in ("housekeeping", "hot_work", "confined_space"):
        assert IDS[code] not in stored
    assert all(year == 2026 for _, year in repository.stored)
    assert {actor for actor, _ in repository.audit} == {LEGACY_IMPORT_ACTOR}


def test_a_differing_stored_count_blocks_the_import() -> None:
    repository = InMemoryBehavior({(IDS["eyes_on_path"], 2026): 11})
    plan = plan_import(repository, MAPPING)
    assert plan.differing == [("eyes_on_path", 11, 12)]

    blank = InMemoryBehavior({(IDS["housekeeping"], 2026): 0})
    assert plan_import(blank, MAPPING).differing == [("housekeeping", 0, None)]


def test_unknown_categories_are_reported_before_0008() -> None:
    class Before0008(InMemoryBehavior):
        def categories(self) -> list[BehaviorCategoryDefinition]:
            return []

    plan = plan_import(Before0008(), MAPPING)
    assert len(plan.unknown) == 24
    assert plan.changes == []


# Pareto -----------------------------------------------------------------------------


def test_pareto_orders_by_count_then_taxonomy_order() -> None:
    pareto = pareto_2026()
    assert [(row.name, row.count) for row in pareto.categories] == [
        ("Eyes On Path", 12),
        ("Pre & Post Job Inspection", 9),
        ("Communications Of Hazards", 4),
        ("Knowledge of Task", 4),
        ("Energy Isolation", 4),
        ("Pinch Points", 3),
        ("Get Assistance", 3),
        ("Line Of Fire", 2),
        ("PPE Hands", 2),
        ("PPE Eye", 1),
    ]


def test_total_denominator_and_per_incident_are_derived() -> None:
    pareto = pareto_2026()
    assert pareto.available is True
    assert pareto.total_tags == 44
    assert pareto.incident_reports == 41
    assert pareto.incident_reports_months_reported == 9
    assert pareto.behaviors_per_incident_report == pytest.approx(44 / 41)


def test_percentages_are_derived_from_counts() -> None:
    pareto = pareto_2026()
    eyes = pareto.categories[0]
    assert eyes.share_of_tags == pytest.approx(12 / 44)
    assert eyes.share_of_incident_reports == pytest.approx(12 / 41)
    assert eyes.cumulative_share_of_tags == pytest.approx(12 / 44)
    assert pareto.categories[1].cumulative_share_of_tags == pytest.approx(21 / 44)


def test_cumulative_share_reaches_exactly_100_percent() -> None:
    pareto = pareto_2026()
    cumulative = [row.cumulative_share_of_tags for row in pareto.categories]
    assert cumulative == sorted(cumulative)
    assert cumulative[-1] == 1.0
    assert sum(row.share_of_tags for row in pareto.categories) == pytest.approx(1.0)


def test_share_of_incident_reports_may_sum_above_100_percent() -> None:
    pareto = pareto_2026()
    shares = sum(row.share_of_incident_reports for row in pareto.categories)
    assert shares == pytest.approx(44 / 41)
    assert shares > 1


def test_blank_categories_are_listed_as_unreported_not_zero() -> None:
    pareto = pareto_2026()
    assert len(pareto.unreported) == 14
    assert pareto.unreported[:2] == ["Housekeeping", "Walking & Working Surfaces"]
    assert all(row.count > 0 for row in pareto.categories)


def test_an_explicit_zero_is_reported() -> None:
    repository = imported_2026()
    repository.stored[(IDS["housekeeping"], 2026)] = 0
    pareto = service.build_pareto(
        year=2026,
        categories=CATEGORIES,
        counts=repository.counts(2026),
        incident_months=incident_months_2026(),
    )
    assert pareto.categories[-1].name == "Housekeeping"
    assert pareto.categories[-1].count == 0
    assert "Housekeeping" not in pareto.unreported
    assert pareto.categories[-1].cumulative_share_of_tags == 1.0


def test_a_year_without_behavior_is_empty_not_zero() -> None:
    pareto = service.build_pareto(
        year=2027,
        categories=CATEGORIES,
        counts=imported_2026().counts(2027),
        incident_months=[None] * 12,
    )
    assert pareto.available is False
    assert pareto.categories == []
    assert (pareto.total_tags, pareto.incident_reports, pareto.behaviors_per_incident_report) == (
        None,
        None,
        None,
    )
    assert len(pareto.unreported) == 24


def test_tags_without_an_incident_total_have_no_incident_share() -> None:
    pareto = service.build_pareto(
        year=2026,
        categories=CATEGORIES,
        counts=imported_2026().counts(2026),
        incident_months=[None] * 12,
    )
    assert pareto.total_tags == 44
    assert pareto.incident_reports is None
    assert pareto.behaviors_per_incident_report is None
    assert all(row.share_of_incident_reports is None for row in pareto.categories)
    assert pareto.categories[0].share_of_tags == pytest.approx(12 / 44)


def test_analytics_uses_the_whole_year_incident_total_whatever_the_through_month() -> None:
    result = analytics.load_analytics(
        IncidentTotals({2026: incident_months_2026()}),
        year=2026,
        through_month=3,
        now=NOW,
        behavior=imported_2026(),
    )
    assert result.incidents.total == 16
    assert result.behavior.incident_reports == 41
    assert result.behavior.total_tags == 44


# Saves ------------------------------------------------------------------------------


def test_save_audits_each_changed_category_with_an_annual_key() -> None:
    repository = InMemoryBehavior()
    outcome = service.save_counts(
        repository,
        year=2026,
        changes=[
            BehaviorChange(category_id=IDS["eyes_on_path"], value=12, previous_value=None),
            BehaviorChange(category_id=IDS["housekeeping"], value=0, previous_value=None),
        ],
        actor_id="tester",
        now=NOW,
    )
    assert outcome.changed_categories == 2
    keys = [change.entity_key for _, change in repository.audit]
    assert keys == ["incidents/behavior/eyes_on_path/2026", "incidents/behavior/housekeeping/2026"]
    assert repository.counts(2026) == {IDS["eyes_on_path"]: 12, IDS["housekeeping"]: 0}

    service.save_counts(
        repository,
        year=2026,
        changes=[BehaviorChange(category_id=IDS["housekeeping"], value=None, previous_value=0)],
        actor_id="tester",
        now=NOW,
    )
    assert IDS["housekeeping"] not in repository.counts(2026)
    assert repository.audit[-1][1].action == "delete"


def test_a_stale_previous_value_is_a_conflict_and_nothing_is_written() -> None:
    repository = InMemoryBehavior({(IDS["eyes_on_path"], 2026): 12})
    with pytest.raises(BehaviorConflictError) as error:
        service.save_counts(
            repository,
            year=2026,
            changes=[
                BehaviorChange(category_id=IDS["ppe_eye"], value=1, previous_value=None),
                BehaviorChange(category_id=IDS["eyes_on_path"], value=13, previous_value=11),
            ],
            actor_id="tester",
            now=NOW,
        )
    assert [(c.category_id, c.current_value) for c in error.value.conflicts] == [
        (IDS["eyes_on_path"], 12)
    ]
    assert repository.counts(2026) == {IDS["eyes_on_path"]: 12}


def test_unknown_categories_are_refused() -> None:
    with pytest.raises(UnknownBehaviorCategoryError):
        service.save_counts(
            InMemoryBehavior(),
            year=2026,
            changes=[BehaviorChange(category_id=999, value=1, previous_value=None)],
            actor_id="tester",
            now=NOW,
        )


# API --------------------------------------------------------------------------------


principal = as_user


def make_client(behavior: InMemoryBehavior, user: UserPrincipal) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[safety_repository] = lambda: IncidentTotals(
        {2026: incident_months_2026()}
    )
    app.dependency_overrides[behavior_repository] = lambda: behavior
    app.dependency_overrides[get_user_principal] = lambda: user
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(safety_router, "_now", lambda: NOW)


@pytest.fixture
def behavior() -> InMemoryBehavior:
    return imported_2026()


@pytest.fixture
def editor(behavior: InMemoryBehavior) -> Iterator[TestClient]:
    yield from make_client(
        behavior, principal(Permission.SAFETY_RECORD_VIEW, Permission.SAFETY_RECORD_EDIT)
    )


@pytest.fixture
def viewer(behavior: InMemoryBehavior) -> Iterator[TestClient]:
    yield from make_client(behavior, principal(Permission.SAFETY_RECORD_VIEW))


def test_get_returns_every_category_with_blanks_as_null(viewer: TestClient) -> None:
    data = viewer.get(URL, params={"year": 2026}).json()
    assert data["canEdit"] is False
    assert len(data["categories"]) == 24
    assert data["total"] == 44
    by_code = {row["code"]: row["value"] for row in data["categories"]}
    assert by_code["eyes_on_path"] == 12
    assert by_code["housekeeping"] is None
    assert data["yearsWithData"] == [2026]


def test_analytics_returns_the_behavior_pareto(behavior: InMemoryBehavior) -> None:
    dashboard = principal(Permission.SAFETY_RECORD_VIEW, Permission.SAFETY_DASHBOARD_VIEW)
    for viewer in make_client(behavior, dashboard):
        data = viewer.get(ANALYTICS_URL, params={"year": 2026, "through": 9}).json()["behavior"]
    assert (data["available"], data["totalTags"], data["incidentReports"]) == (True, 44, 41)
    assert data["categories"][0] == {
        "code": "eyes_on_path",
        "name": "Eyes On Path",
        "count": 12,
        "shareOfTags": pytest.approx(12 / 44),
        "shareOfIncidentReports": pytest.approx(12 / 41),
        "cumulativeShareOfTags": pytest.approx(12 / 44),
    }
    assert data["categories"][-1]["cumulativeShareOfTags"] == 1.0


def test_viewer_cannot_save(viewer: TestClient, behavior: InMemoryBehavior) -> None:
    change = {"categoryId": IDS["housekeeping"], "value": 1, "previousValue": None}
    response = viewer.patch(URL, json={"year": 2026, "changes": [change]})
    assert response.status_code == 403
    assert IDS["housekeeping"] not in behavior.counts(2026)


def test_editor_saves_and_conflicts_are_409(editor: TestClient, behavior: InMemoryBehavior) -> None:
    change = {"categoryId": IDS["housekeeping"], "value": 0, "previousValue": None}
    response = editor.patch(URL, json={"year": 2026, "changes": [change]})
    assert response.status_code == 200
    assert response.json()["changedCategories"] == 1
    assert behavior.counts(2026)[IDS["housekeeping"]] == 0

    stale = {"categoryId": IDS["eyes_on_path"], "value": 13, "previousValue": 11}
    response = editor.patch(URL, json={"year": 2026, "changes": [stale]})
    assert response.status_code == 409
    assert response.json()["detail"]["conflicts"] == [
        {"categoryId": IDS["eyes_on_path"], "currentValue": 12}
    ]


@pytest.mark.parametrize(
    "change",
    [
        {"categoryId": 1, "value": -1, "previousValue": 9},
        {"categoryId": 1, "value": 1.5, "previousValue": 9},
        {"categoryId": 1, "value": "3", "previousValue": 9},
        {"categoryId": 1, "value": 3, "previousValue": 9, "month": 12},
    ],
)
def test_invalid_counts_are_rejected(editor: TestClient, change: dict[str, Any]) -> None:
    assert editor.patch(URL, json={"year": 2026, "changes": [change]}).status_code == 422


def test_unknown_category_is_422(editor: TestClient) -> None:
    change = {"categoryId": 999, "value": 1, "previousValue": None}
    response = editor.patch(URL, json={"year": 2026, "changes": [change]})
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "unknown_category"
