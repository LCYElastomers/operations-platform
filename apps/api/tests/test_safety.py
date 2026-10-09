"""Safety monthly metrics: calculations, saves, authorization, and API validation.

Uses an in-memory repository (test double only); PostgreSQL behaviour is
covered by test_safety_database.py.
"""

import datetime as dt
import logging
import uuid
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from principals import TESTER, as_user

from app.audit.recorder import AuditChange
from app.core.authorization import UserPrincipal, get_user_principal
from app.core.permissions import Permission
from app.db.session import DatabaseNotConfiguredError
from app.main import create_app
from app.safety import router as safety_router
from app.safety import service
from app.safety.repository import (
    CategoryDefinition,
    Cell,
    SectionDefinition,
    StoredValues,
)
from app.safety.router import safety_repository
from app.safety.schemas import CellChange
from app.safety.service import EditConflictError, UnknownCategoryError

URL = "/api/v1/safety/incidents/metrics"
NOW = dt.datetime(2026, 10, 6, 12, 0, tzinfo=dt.UTC)

SECTIONS = [
    SectionDefinition(
        id=1,
        code="incident_classification",
        name="Incident Classification",
        categories=(
            CategoryDefinition(id=11, code="first_aid", name="First Aid"),
            CategoryDefinition(id=12, code="recordable_injury", name="Recordable Injury"),
        ),
    ),
    SectionDefinition(
        id=2,
        code="incident_near_miss_totals",
        name="Incident & Near Miss Totals",
        categories=(
            CategoryDefinition(id=21, code="near_miss", name="Near Miss"),
            CategoryDefinition(id=22, code="incident", name="Incident"),
        ),
    ),
]


class InMemoryRepository:
    def __init__(self, stored: dict[tuple[int, int, int], int] | None = None) -> None:
        # (category_id, year, month) -> value
        self.stored = dict(stored or {})
        self.pending: dict[tuple[int, int, int], int | None] = {}
        self.audit: list[tuple[str, uuid.UUID, AuditChange]] = []
        self.pending_audit: list[tuple[str, uuid.UUID, AuditChange]] = []
        self.locks: list[tuple[str, int]] = []
        self.commits = 0

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

    def lock_year(self, metric_set: str, year: int) -> None:
        self.locks.append((metric_set, year))

    def write(
        self,
        *,
        year: int,
        upserts: dict[Cell, int],
        deletes: Sequence[Cell],
        actor_id: str,
        at: dt.datetime,
    ) -> None:
        for (category, month), value in upserts.items():
            self.pending[(category, year, month)] = value
        for category, month in deletes:
            self.pending[(category, year, month)] = None

    def record_audit(
        self,
        *,
        actor_id: str,
        change_set_id: uuid.UUID,
        at: dt.datetime,
        changes: Sequence[AuditChange],
    ) -> None:
        self.pending_audit.extend((actor_id, change_set_id, c) for c in changes)

    def commit(self) -> None:
        for key, value in self.pending.items():
            if value is None:
                self.stored.pop(key, None)
            else:
                self.stored[key] = value
        self.audit.extend(self.pending_audit)
        self.pending, self.pending_audit = {}, []
        self.commits += 1

    def rollback(self) -> None:
        self.pending, self.pending_audit = {}, []


def change(category_id: int, month: int, value: int | None, previous: int | None) -> CellChange:
    return CellChange(category_id=category_id, month=month, value=value, previous_value=previous)


def save(repository: InMemoryRepository, *changes: CellChange) -> service.SaveOutcome:
    return service.save_changes(
        repository,
        metric_set="incidents",
        year=2026,
        changes=list(changes),
        actor_id="tester",
        now=NOW,
    )


# Calculations --------------------------------------------------------------------


def test_total_distinguishes_unreported_from_zero() -> None:
    assert service.total([None, None]) is None
    assert service.total([0, None]) == 0
    assert service.total([1, None, 2]) == 3


def test_metrics_grid_has_twelve_months_and_calculated_ytd() -> None:
    repository = InMemoryRepository(
        {(11, 2026, 1): 2, (11, 2026, 3): 0, (12, 2026, 1): 1, (21, 2026, 2): 4, (11, 2025, 1): 9}
    )

    metrics = service.load_metrics(repository, metric_set="incidents", year=2026, can_edit=False)

    classification, totals = metrics.sections
    first_aid, recordable = classification.categories
    near_miss, incident = totals.categories
    assert first_aid.values == [2, None, 0] + [None] * 9
    assert first_aid.ytd == 2
    assert recordable.ytd == 1
    assert near_miss.ytd == 4
    assert metrics.years_with_data == [2025, 2026]


def test_incident_total_is_the_explicit_metric_not_a_sum_of_classifications() -> None:
    # Classifications are not mutually exclusive: one incident may carry two.
    repository = InMemoryRepository({(11, 2026, 1): 1, (12, 2026, 1): 1, (22, 2026, 1): 1})

    metrics = service.load_metrics(repository, metric_set="incidents", year=2026, can_edit=False)

    incident = metrics.sections[1].categories[1]
    assert (incident.code, incident.values[0], incident.ytd) == ("incident", 1, 1)
    assert "monthly_totals" not in type(metrics.sections[0]).model_fields
    assert "ytd" not in type(metrics.sections[0]).model_fields


def test_incident_without_classifications_is_still_reported() -> None:
    repository = InMemoryRepository({(22, 2026, 2): 3})

    metrics = service.load_metrics(repository, metric_set="incidents", year=2026, can_edit=False)

    assert metrics.sections[1].categories[1].ytd == 3
    assert all(row.ytd is None for row in metrics.sections[0].categories)


def test_metrics_for_an_unreported_year_are_null_not_zero() -> None:
    metrics = service.load_metrics(
        InMemoryRepository(), metric_set="incidents", year=2026, can_edit=True
    )

    for section in metrics.sections:
        assert all(row.values == [None] * 12 and row.ytd is None for row in section.categories)


# Saves ---------------------------------------------------------------------------


def test_save_creates_updates_and_clears_with_audit_events() -> None:
    repository = InMemoryRepository({(11, 2026, 1): 2, (11, 2026, 2): 5})

    outcome = save(
        repository,
        change(11, 1, 3, 2),
        change(11, 2, None, 5),
        change(21, 1, 0, None),
    )

    assert outcome.changed_cells == 3
    assert repository.stored == {(11, 2026, 1): 3, (21, 2026, 1): 0}
    assert repository.locks == [("incidents", 2026)]
    events = {
        c.entity_key: (actor, c.action, c.old_value, c.new_value)
        for actor, _, c in repository.audit
    }
    assert events == {
        "incidents/incident_classification/first_aid/2026-01": (
            "tester",
            "update",
            {"value": 2},
            {"value": 3},
        ),
        "incidents/incident_classification/first_aid/2026-02": (
            "tester",
            "delete",
            {"value": 5},
            None,
        ),
        "incidents/incident_near_miss_totals/near_miss/2026-01": (
            "tester",
            "create",
            None,
            {"value": 0},
        ),
    }
    assert len({change_set for _, change_set, _ in repository.audit}) == 1


def test_unchanged_cells_are_not_written_or_audited() -> None:
    repository = InMemoryRepository({(11, 2026, 1): 2})

    outcome = save(repository, change(11, 1, 2, 2), change(11, 2, None, None))

    assert outcome.changed_cells == 0
    assert repository.commits == 0
    assert repository.audit == []


def test_conflicting_save_writes_nothing() -> None:
    repository = InMemoryRepository({(11, 2026, 1): 4})

    with pytest.raises(EditConflictError) as error:
        save(repository, change(11, 1, 3, 2), change(21, 1, 1, None))

    assert [(c.category_id, c.month, c.current_value) for c in error.value.conflicts] == [
        (11, 1, 4)
    ]
    assert repository.stored == {(11, 2026, 1): 4}
    assert repository.audit == []


def test_unknown_category_is_rejected_before_locking() -> None:
    repository = InMemoryRepository()

    with pytest.raises(UnknownCategoryError) as error:
        save(repository, change(99, 1, 1, None))

    assert error.value.category_ids == [99]
    assert repository.locks == []


# API -----------------------------------------------------------------------------


principal = as_user


@pytest.fixture
def repository() -> InMemoryRepository:
    return InMemoryRepository({(11, 2026, 1): 2})


def make_client(repository: InMemoryRepository, user: UserPrincipal | None) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[safety_repository] = lambda: repository
    if user is not None:
        app.dependency_overrides[get_user_principal] = lambda: user
    with TestClient(app) as client:
        yield client


@pytest.fixture
def editor(repository: InMemoryRepository) -> Iterator[TestClient]:
    yield from make_client(
        repository, principal(Permission.SAFETY_RECORD_VIEW, Permission.SAFETY_RECORD_EDIT)
    )


@pytest.fixture
def viewer(repository: InMemoryRepository) -> Iterator[TestClient]:
    yield from make_client(repository, principal(Permission.SAFETY_RECORD_VIEW))


def body(*changes: dict[str, Any], year: Any = 2026) -> dict[str, Any]:
    return {"year": year, "changes": list(changes)}


def cell(**overrides: Any) -> dict[str, Any]:
    return {"categoryId": 11, "month": 1, "value": 3, "previousValue": 2, **overrides}


def test_anonymous_requests_are_refused_by_default(repository: InMemoryRepository) -> None:
    for client in make_client(repository, None):
        assert client.get(URL, params={"year": 2026}).status_code == 401
        response = client.patch(URL, json=body(cell()))
        assert response.status_code == 401
        assert response.json()["detail"]["error"] == "authentication_required"
    assert repository.stored == {(11, 2026, 1): 2}


def test_changes_are_attributed_to_the_session_user(
    editor: TestClient, repository: InMemoryRepository
) -> None:
    response = editor.patch(URL, json=body(cell()))

    assert response.status_code == 200
    assert repository.audit[0][0] == TESTER


def test_viewer_reads_but_cannot_edit(viewer: TestClient, repository: InMemoryRepository) -> None:
    response = viewer.get(URL, params={"year": 2026})
    assert response.status_code == 200
    assert response.json()["canEdit"] is False

    response = viewer.patch(URL, json=body(cell()))
    assert response.status_code == 403
    assert response.json()["detail"] == {
        "error": "permission_denied",
        "message": "You do not have permission to perform this action.",
    }
    assert repository.stored == {(11, 2026, 1): 2}


def test_get_returns_the_monthly_grid(editor: TestClient) -> None:
    response = editor.get(URL, params={"year": 2026})

    assert response.status_code == 200
    data = response.json()
    assert data["canEdit"] is True
    assert data["year"] == 2026
    first_aid = data["sections"][0]["categories"][0]
    assert first_aid == {
        "id": 11,
        "code": "first_aid",
        "name": "First Aid",
        "description": None,
        "areaKind": None,
        "values": [2] + [None] * 11,
        "ytd": 2,
    }
    assert set(data["sections"][1]) == {"id", "code", "name", "categories"}
    assert data["sections"][1]["categories"][1]["ytd"] is None


@pytest.mark.parametrize("year", ["", "abc", 1999, 2101])
def test_get_rejects_invalid_years(editor: TestClient, year: Any) -> None:
    assert editor.get(URL, params={"year": year}).status_code == 422


def test_get_requires_a_year(editor: TestClient) -> None:
    assert editor.get(URL).status_code == 422


def test_save_returns_the_refreshed_grid(
    editor: TestClient, repository: InMemoryRepository
) -> None:
    response = editor.patch(
        URL, json=body(cell(), cell(categoryId=21, value=0, previousValue=None))
    )

    assert response.status_code == 200
    data = response.json()
    assert data["changedCells"] == 2
    assert data["metrics"]["sections"][0]["categories"][0]["values"][0] == 3
    assert data["metrics"]["sections"][1]["categories"][0]["ytd"] == 0
    assert repository.stored == {(11, 2026, 1): 3, (21, 2026, 1): 0}


@pytest.mark.parametrize(
    "bad",
    [
        cell(value=-1),
        cell(value=1.5),
        cell(value="3"),
        cell(value=True),
        cell(value=100_001),
        cell(month=0),
        cell(month=13),
        cell(categoryId=0),
        cell(previousValue=-1),
        {"categoryId": 11, "month": 1, "value": 3},
        cell(extra="x"),
    ],
)
def test_save_rejects_invalid_cells(
    editor: TestClient, repository: InMemoryRepository, bad: dict[str, Any]
) -> None:
    response = editor.patch(URL, json=body(bad))

    assert response.status_code == 422
    assert repository.stored == {(11, 2026, 1): 2}


@pytest.mark.parametrize(
    "payload",
    [
        body(),
        body(cell(), cell(value=4)),
        body(cell(), year=1999),
        body(cell(), year="2026"),
        {"changes": [cell()]},
    ],
)
def test_save_rejects_invalid_requests(editor: TestClient, payload: dict[str, Any]) -> None:
    assert editor.patch(URL, json=payload).status_code == 422


def test_save_rejects_unknown_categories(editor: TestClient) -> None:
    response = editor.patch(URL, json=body(cell(categoryId=99, previousValue=None)))

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "unknown_category"
    assert response.json()["detail"]["categoryIds"] == [99]


def test_save_reports_conflicts(editor: TestClient, repository: InMemoryRepository) -> None:
    response = editor.patch(URL, json=body(cell(previousValue=None)))

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "edit_conflict"
    assert detail["conflicts"] == [{"categoryId": 11, "month": 1, "currentValue": 2}]
    assert repository.stored == {(11, 2026, 1): 2}


def test_missing_database_is_reported_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def not_configured() -> None:
        raise DatabaseNotConfiguredError("DATABASE_URL is not set")

    monkeypatch.setattr(safety_router, "get_sessionmaker", not_configured)
    app = create_app()
    app.dependency_overrides[get_user_principal] = lambda: principal(Permission.SAFETY_RECORD_VIEW)
    with TestClient(app) as client:
        response = client.get(URL, params={"year": 2026})

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "database_unavailable"


def test_saves_are_logged_without_values(
    editor: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    editor.patch(URL, json=body(cell(value=777)))

    line = next(
        r.getMessage() for r in caplog.records if "event=safety_metrics_saved" in r.getMessage()
    )
    assert f"user={TESTER}" in line
    assert "updated=1" in line
    assert "777" not in caplog.text
