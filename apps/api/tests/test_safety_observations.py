"""Safety Observations: service rules and API behaviour against an in-memory repository.

Database behaviour (constraints, seeds, real SQL) is covered by
test_safety_observations_database.py.
"""

import datetime as dt
import logging
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.audit.recorder import AuditChange
from app.core.authorization import UserPrincipal, get_user_principal
from app.core.config import Settings, get_settings
from app.core.permissions import Permission
from app.db.session import DatabaseNotConfiguredError
from app.main import create_app
from app.safety.observations import router as observations_router
from app.safety.observations import service
from app.safety.observations.repository import (
    CategoryDefinition,
    CountRow,
    ObservationFilter,
    ObservationRecord,
    ObservationValues,
)
from app.safety.observations.router import observation_repository

URL = "/api/v1/safety/observations"
NOW = dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.UTC)
P = Permission

CATEGORIES = [
    CategoryDefinition(1, "housekeeping", "Housekeeping", True),
    CategoryDefinition(2, "ppe", "PPE", True),
    CategoryDefinition(3, "fire", "Fire", True),
    CategoryDefinition(4, "fire_system", "Fire System", True),
    CategoryDefinition(9, "retired", "Retired Category", False),
]


class InMemoryRepository:
    """Holds committed records; writes become visible only on commit, like a transaction."""

    def __init__(self) -> None:
        self.records: dict[int, ObservationRecord] = {}
        self.pending: dict[int, ObservationRecord | None] = {}
        self.audit: list[tuple[str, uuid.UUID, AuditChange]] = []
        self.pending_audit: list[tuple[str, uuid.UUID, AuditChange]] = []
        self.next_id = 1
        self.commits = 0
        self.rollbacks = 0
        self.locked: list[int] = []
        self.fail: Exception | None = None

    def _category(self, category_id: int) -> CategoryDefinition:
        return next(c for c in CATEGORIES if c.id == category_id)

    def _visible(self) -> dict[int, ObservationRecord]:
        merged: dict[int, ObservationRecord | None] = {**self.records, **self.pending}
        return {k: v for k, v in merged.items() if v is not None}

    def categories(self) -> list[CategoryDefinition]:
        if self.fail:
            raise self.fail
        return list(CATEGORIES)

    def _matching(self, criteria: ObservationFilter) -> list[ObservationRecord]:
        def keep(r: ObservationRecord) -> bool:
            v = r.values
            return (
                (criteria.observed_from is None or v.observed_on >= criteria.observed_from)
                and (criteria.observed_to is None or v.observed_on <= criteria.observed_to)
                and (criteria.outcome is None or v.outcome == criteria.outcome)
                and (criteria.kind is None or v.kind == criteria.kind)
                and (criteria.category_id is None or v.category_id == criteria.category_id)
            )

        return [r for r in self._visible().values() if keep(r)]

    def search(
        self, criteria: ObservationFilter, *, limit: int, offset: int
    ) -> tuple[list[ObservationRecord], int]:
        if self.fail:
            raise self.fail
        rows = sorted(
            self._matching(criteria), key=lambda r: (r.values.observed_on, r.id), reverse=True
        )
        return rows[offset : offset + limit], len(rows)

    def get(self, observation_id: int, *, for_update: bool = False) -> ObservationRecord | None:
        if for_update:
            self.locked.append(observation_id)
        return self._visible().get(observation_id)

    def insert(self, values: ObservationValues, *, actor_id: str, at: dt.datetime) -> int:
        if self.fail:
            raise self.fail
        observation_id, self.next_id = self.next_id, self.next_id + 1
        category = self._category(values.category_id)
        self.pending[observation_id] = ObservationRecord(
            observation_id, values, category.code, category.name, at, actor_id, at, actor_id
        )
        return observation_id

    def update(
        self, observation_id: int, values: ObservationValues, *, actor_id: str, at: dt.datetime
    ) -> None:
        current = self._visible()[observation_id]
        category = self._category(values.category_id)
        self.pending[observation_id] = replace(
            current,
            values=values,
            category_code=category.code,
            category_name=category.name,
            updated_at=at,
            updated_by=actor_id,
        )

    def delete(self, observation_id: int) -> None:
        self.pending[observation_id] = None

    def counts(self, criteria: ObservationFilter) -> list[CountRow]:
        tally: dict[tuple[int, int, str, str], int] = {}
        for r in self._matching(criteria):
            v = r.values
            key = (v.observed_on.month, v.category_id, v.outcome, v.kind)
            tally[key] = tally.get(key, 0) + 1
        return [CountRow(m, c, o, k, n) for (m, c, o, k), n in tally.items()]

    def years_with_observations(self) -> list[int]:
        return sorted({r.values.observed_on.year for r in self._visible().values()})

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
        for key, record in self.pending.items():
            if record is None:
                self.records.pop(key, None)
            else:
                self.records[key] = record
        self.audit.extend(self.pending_audit)
        self.pending, self.pending_audit = {}, []
        self.commits += 1

    def rollback(self) -> None:
        self.pending, self.pending_audit = {}, []
        self.rollbacks += 1


def values(**overrides: Any) -> ObservationValues:
    base: dict[str, Any] = {
        "observed_on": dt.date(2026, 10, 6),
        "outcome": "unsafe",
        "kind": "condition",
        "category_id": 1,
        "area_location": "Packaging line 2",
        "description": "Pallet wrap on walkway",
        "corrective_action": None,
    }
    return ObservationValues(**{**base, **overrides})


def seed(repository: InMemoryRepository, *items: ObservationValues) -> list[int]:
    ids = [repository.insert(v, actor_id="seed", at=NOW - dt.timedelta(days=1)) for v in items]
    repository.commit()
    repository.audit.clear()
    repository.commits = 0
    return ids


# Counts --------------------------------------------------------------------------


def row(month: int, category_id: int, outcome: str, kind: str, count: int) -> CountRow:
    return CountRow(month, category_id, outcome, kind, count)


ROWS = [
    row(1, 1, "safe", "act", 2),
    row(1, 1, "unsafe", "condition", 3),
    row(2, 2, "unsafe", "act", 1),
    row(3, 3, "safe", "condition", 4),
]


def test_counts_are_all_derived_from_the_same_rows() -> None:
    counts = service.count_summary(ROWS)

    assert counts.model_dump() == {
        "total": 10,
        "safe": 6,
        "unsafe": 4,
        "safe_act": 2,
        "safe_condition": 4,
        "unsafe_act": 1,
        "unsafe_condition": 3,
    }
    assert counts.safe + counts.unsafe == counts.total
    assert counts.safe_act + counts.safe_condition == counts.safe
    assert counts.unsafe_act + counts.unsafe_condition == counts.unsafe


def test_counts_of_no_rows_are_zero() -> None:
    assert service.count_summary([]).total == 0


@pytest.mark.parametrize(("year", "expected"), [(2025, 12), (2026, 10), (2027, 0)])
def test_started_months(year: int, expected: int) -> None:
    assert service.started_months(year, NOW.date()) == expected


def test_dashboard_months_not_started_are_null_and_started_empty_months_are_zero() -> None:
    dashboard = service.build_dashboard(
        year=2026, today=NOW.date(), categories=CATEGORIES, rows=ROWS, years_with_data=[2026]
    )

    assert dashboard.through_month == 10
    assert dashboard.counts.total == 10
    assert dashboard.unsafe_share == pytest.approx(0.4)
    assert [m.counts.total if m.counts else None for m in dashboard.months] == [
        5, 1, 4, 0, 0, 0, 0, 0, 0, 0, None, None,
    ]  # fmt: skip
    housekeeping = next(c for c in dashboard.categories if c.code == "housekeeping")
    assert (housekeeping.total, housekeeping.safe, housekeeping.unsafe) == (5, 2, 3)
    assert housekeeping.monthly == [5, 0, 0, 0, 0, 0, 0, 0, 0, 0, None, None]
    assert sum(c.total for c in dashboard.categories) == dashboard.counts.total


def test_dashboard_without_observations_has_no_unsafe_share() -> None:
    dashboard = service.build_dashboard(
        year=2026, today=NOW.date(), categories=CATEGORIES, rows=[], years_with_data=[]
    )

    assert dashboard.counts.total == 0
    assert dashboard.unsafe_share is None
    assert dashboard.months[0].counts is not None
    assert dashboard.months[11].counts is None


def test_dashboard_shows_a_future_month_that_has_records() -> None:
    dashboard = service.build_dashboard(
        year=2026,
        today=dt.date(2026, 3, 31),
        categories=CATEGORIES,
        rows=[row(4, 1, "safe", "act", 1)],
        years_with_data=[2026],
    )

    assert dashboard.months[3].counts is not None
    assert dashboard.months[4].counts is None


def test_retired_categories_appear_only_when_they_have_counts() -> None:
    codes = [
        c.code
        for c in service.build_dashboard(
            year=2026, today=NOW.date(), categories=CATEGORIES, rows=ROWS, years_with_data=[]
        ).categories
    ]
    assert "retired" not in codes

    codes = [
        c.code
        for c in service.build_dashboard(
            year=2026,
            today=NOW.date(),
            categories=CATEGORIES,
            rows=[*ROWS, row(1, 9, "safe", "act", 1)],
            years_with_data=[],
        ).categories
    ]
    assert "retired" in codes


def test_fire_and_fire_system_are_counted_separately() -> None:
    rows = [row(1, 3, "safe", "act", 1), row(1, 4, "unsafe", "condition", 2)]
    summary = {
        c.code: c.total
        for c in service.build_dashboard(
            year=2026, today=NOW.date(), categories=CATEGORIES, rows=rows, years_with_data=[]
        ).categories
    }

    assert summary["fire"] == 1
    assert summary["fire_system"] == 2


@pytest.mark.parametrize(
    ("month", "start", "end"),
    [
        (None, dt.date(2026, 1, 1), dt.date(2026, 12, 31)),
        (2, dt.date(2026, 2, 1), dt.date(2026, 2, 28)),
        (12, dt.date(2026, 12, 1), dt.date(2026, 12, 31)),
    ],
)
def test_period_covers_whole_months(month: int | None, start: dt.date, end: dt.date) -> None:
    criteria = service.period(2026, month)
    assert (criteria.observed_from, criteria.observed_to) == (start, end)


# API -----------------------------------------------------------------------------


def principal(*permissions: Permission) -> UserPrincipal:
    return UserPrincipal("tester", authenticated=True, granted=frozenset(permissions))


@pytest.fixture
def repository() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(observations_router, "_now", lambda: NOW)


def make_client(repository: InMemoryRepository, user: UserPrincipal | None) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[observation_repository] = lambda: repository
    if user is not None:
        app.dependency_overrides[get_user_principal] = lambda: user
    with TestClient(app) as client:
        yield client


@pytest.fixture
def editor(repository: InMemoryRepository) -> Iterator[TestClient]:
    yield from make_client(repository, principal(P.SAFETY_OBSERVATIONS_EDIT))


@pytest.fixture
def viewer(repository: InMemoryRepository) -> Iterator[TestClient]:
    yield from make_client(repository, principal(P.SAFETY_OBSERVATIONS_VIEW))


def payload(**overrides: Any) -> dict[str, Any]:
    return {
        "observedOn": "2026-10-06",
        "outcome": "unsafe",
        "kind": "condition",
        "categoryId": 1,
        "areaLocation": "Packaging line 2",
        "description": "Pallet wrap on walkway",
        "correctiveAction": None,
        **overrides,
    }


def created(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post(URL, json=payload(**overrides))
    assert response.status_code == 201, response.text
    return dict(response.json())


# Authorization


def test_anonymous_requests_are_refused(repository: InMemoryRepository) -> None:
    seed(repository, values())
    for client in make_client(repository, None):
        for method, path in [
            ("get", ""),
            ("get", "/categories"),
            ("get", "/summary?year=2026"),
            ("get", "/dashboard?year=2026"),
        ]:
            assert getattr(client, method)(URL + path).status_code == 401
        assert client.post(URL, json=payload()).status_code == 401
        assert client.delete(f"{URL}/1").status_code == 401
    assert len(repository.records) == 1
    assert repository.audit == []


def test_viewer_reads_but_cannot_write(viewer: TestClient, repository: InMemoryRepository) -> None:
    [observation_id] = seed(repository, values())

    for path in ("", "/categories", "/summary?year=2026", "/dashboard?year=2026"):
        assert viewer.get(URL + path).status_code == 200
    assert viewer.get(URL).json()["canEdit"] is False
    assert viewer.get(URL + "/categories").json()["canEdit"] is False

    response = viewer.post(URL, json=payload())
    assert response.status_code == 403
    assert response.json()["detail"]["permission"] == "safety.observations.edit"
    put = payload(expectedUpdatedAt=(NOW - dt.timedelta(days=1)).isoformat())
    assert viewer.put(f"{URL}/{observation_id}", json=put).status_code == 403
    assert viewer.delete(f"{URL}/{observation_id}").status_code == 403
    assert list(repository.records) == [observation_id]
    assert repository.audit == []


@pytest.mark.parametrize(
    ("granted", "can_view", "can_edit"),
    [
        (P.SAFETY_VIEW, True, False),
        (P.SAFETY_EDIT, True, True),
        (P.SAFETY_OBSERVATIONS_VIEW, True, False),
        (P.SAFETY_OBSERVATIONS_EDIT, True, True),
        (P.SAFETY_INCIDENTS_EDIT, False, False),
    ],
)
def test_module_grants_cover_observations(
    repository: InMemoryRepository, granted: Permission, can_view: bool, can_edit: bool
) -> None:
    for client in make_client(repository, principal(granted)):
        response = client.get(URL)
        assert response.status_code == (200 if can_view else 403)
        if can_view:
            assert response.json()["canEdit"] is can_edit
        assert client.post(URL, json=payload()).status_code == (201 if can_edit else 403)


def test_development_mode_creates_as_the_development_user(
    repository: InMemoryRepository,
) -> None:
    app = create_app()
    app.dependency_overrides[observation_repository] = lambda: repository
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, user_auth_mode="development-unauthenticated"
    )
    with TestClient(app) as client:
        response = client.post(URL, json=payload())

    assert response.status_code == 201
    assert response.json()["createdBy"] == "development-user"
    assert repository.audit[0][0] == "development-user"


# Categories


def test_categories_lists_only_active_categories_in_order(editor: TestClient) -> None:
    response = editor.get(URL + "/categories")

    assert response.status_code == 200
    data = response.json()
    assert data["canEdit"] is True
    assert [c["code"] for c in data["categories"]] == ["housekeeping", "ppe", "fire", "fire_system"]
    assert data["categories"][0] == {"id": 1, "code": "housekeeping", "name": "Housekeeping"}


# Create


def test_create_returns_the_record_and_audits_it(
    editor: TestClient, repository: InMemoryRepository
) -> None:
    data = created(editor, correctiveAction="Cleared and briefed the crew")

    assert data == {
        "id": 1,
        "observedOn": "2026-10-06",
        "outcome": "unsafe",
        "kind": "condition",
        "categoryId": 1,
        "categoryCode": "housekeeping",
        "categoryName": "Housekeeping",
        "areaLocation": "Packaging line 2",
        "description": "Pallet wrap on walkway",
        "correctiveAction": "Cleared and briefed the crew",
        "createdAt": "2026-10-07T12:00:00Z",
        "createdBy": "tester",
        "updatedAt": "2026-10-07T12:00:00Z",
        "updatedBy": "tester",
    }
    assert repository.commits == 1
    [(actor, _, change)] = repository.audit
    assert actor == "tester"
    assert change.action == "create"
    assert change.entity_type == "safety.observation"
    assert change.entity_key == "observations/1"
    assert change.old_value is None
    assert change.new_value == {
        "observed_on": "2026-10-06",
        "outcome": "unsafe",
        "kind": "condition",
        "category": "housekeeping",
        "area_location": "Packaging line 2",
        "description": "Pallet wrap on walkway",
        "corrective_action": "Cleared and briefed the crew",
    }


def test_create_needs_only_the_required_fields(editor: TestClient) -> None:
    data = created(
        editor,
        **{"areaLocation": None, "description": None, "correctiveAction": None},
    )
    assert (data["areaLocation"], data["description"], data["correctiveAction"]) == (
        None,
        None,
        None,
    )

    response = editor.post(
        URL, json={"observedOn": "2026-10-06", "outcome": "safe", "kind": "act", "categoryId": 2}
    )
    assert response.status_code == 201


def test_create_trims_text_and_stores_blank_as_null(editor: TestClient) -> None:
    data = created(editor, areaLocation="  Dock 3  ", description="   ", correctiveAction="")

    assert data["areaLocation"] == "Dock 3"
    assert data["description"] is None
    assert data["correctiveAction"] is None


@pytest.mark.parametrize(
    "bad",
    [
        {"observedOn": "06/10/2026"},
        {"observedOn": "2026-02-30"},
        {"observedOn": "1999-12-31"},
        {"observedOn": 20261006},
        {"observedOn": None},
        {"outcome": "Safe"},
        {"outcome": "at_risk"},
        {"outcome": None},
        {"kind": "behaviour"},
        {"kind": None},
        {"categoryId": 0},
        {"categoryId": "1"},
        {"categoryId": 1.5},
        {"categoryId": True},
        {"areaLocation": "x" * 201},
        {"description": "x" * 2001},
        {"correctiveAction": "x" * 2001},
        {"description": 7},
        {"person": "Someone"},
    ],
)
def test_create_rejects_invalid_fields(
    editor: TestClient, repository: InMemoryRepository, bad: dict[str, Any]
) -> None:
    response = editor.post(URL, json=payload(**bad))

    assert response.status_code == 422, bad
    assert repository.records == {}
    assert repository.audit == []


@pytest.mark.parametrize("missing", ["observedOn", "outcome", "kind", "categoryId"])
def test_create_requires_classification(editor: TestClient, missing: str) -> None:
    body = payload()
    del body[missing]
    assert editor.post(URL, json=body).status_code == 422


def test_create_accepts_the_maximum_text_lengths(editor: TestClient) -> None:
    data = created(editor, areaLocation="a" * 200, description="d" * 2000)
    assert len(data["description"]) == 2000


@pytest.mark.parametrize("category_id", [99, 9])
def test_create_rejects_unknown_and_retired_categories(
    editor: TestClient, repository: InMemoryRepository, category_id: int
) -> None:
    response = editor.post(URL, json=payload(categoryId=category_id))

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "unknown_category"
    assert response.json()["detail"]["categoryId"] == category_id
    assert repository.records == {}


def test_create_rejects_future_dates_but_accepts_today(editor: TestClient) -> None:
    response = editor.post(URL, json=payload(observedOn="2026-10-08"))
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "error": "observed_on_in_future",
        "message": "The observed date cannot be in the future.",
        "today": "2026-10-07",
    }

    assert editor.post(URL, json=payload(observedOn="2026-10-07")).status_code == 201


@pytest.mark.parametrize(
    ("instant", "today", "started"),
    [
        (dt.datetime(2027, 1, 1, 0, 0, tzinfo=dt.UTC), "2026-12-31", 0),  # 18:00 CST, UTC midnight
        (dt.datetime(2027, 1, 1, 5, 59, 59, tzinfo=dt.UTC), "2026-12-31", 0),  # 23:59:59 CST
        (dt.datetime(2027, 1, 1, 6, 0, tzinfo=dt.UTC), "2027-01-01", 1),  # 00:00 CST
    ],
)
def test_observations_roll_over_at_baytown_midnight(
    editor: TestClient,
    repository: InMemoryRepository,
    monkeypatch: pytest.MonkeyPatch,
    instant: dt.datetime,
    today: str,
    started: int,
) -> None:
    monkeypatch.setattr(observations_router, "_now", lambda: instant)

    response = editor.post(URL, json=payload(observedOn="2027-01-01"))
    if today == "2027-01-01":
        assert response.status_code == 201
    else:
        assert response.status_code == 422
        assert response.json()["detail"]["today"] == today
        assert repository.records == {}

    months = editor.get(URL + "/dashboard", params={"year": 2027}).json()["months"]
    assert sum(m["counts"] is not None for m in months) == started


def test_audit_timestamps_stay_utc(
    editor: TestClient, repository: InMemoryRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    instant = dt.datetime(2027, 1, 1, 6, 0, tzinfo=dt.UTC)
    monkeypatch.setattr(observations_router, "_now", lambda: instant)

    assert created(editor, observedOn="2027-01-01")["createdAt"].startswith("2027-01-01T06:00:00")


# List


@pytest.fixture
def listed(repository: InMemoryRepository) -> list[int]:
    return seed(
        repository,
        values(observed_on=dt.date(2026, 9, 30), outcome="safe", kind="act", category_id=1),
        values(observed_on=dt.date(2026, 10, 1), outcome="unsafe", kind="act", category_id=2),
        values(observed_on=dt.date(2026, 10, 1), outcome="safe", kind="condition", category_id=2),
        values(observed_on=dt.date(2026, 10, 5), outcome="unsafe", kind="condition", category_id=3),
        values(observed_on=dt.date(2025, 10, 5), outcome="safe", kind="act", category_id=4),
    )


def listed_ids(client: TestClient, **params: Any) -> list[int]:
    response = client.get(URL, params=params)
    assert response.status_code == 200, response.text
    return [o["id"] for o in response.json()["observations"]]


def test_list_is_newest_first(editor: TestClient, listed: list[int]) -> None:
    data = editor.get(URL).json()

    assert [o["id"] for o in data["observations"]] == [4, 3, 2, 1, 5]
    assert data["totalMatching"] == 5
    assert data["canEdit"] is True


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"year": 2026}, [4, 3, 2, 1]),
        ({"year": 2026, "month": 10}, [4, 3, 2]),
        ({"year": 2026, "month": 9}, [1]),
        ({"year": 2026, "month": 11}, []),
        ({"observedFrom": "2026-10-01", "observedTo": "2026-10-01"}, [3, 2]),
        ({"observedFrom": "2026-10-02"}, [4]),
        ({"observedTo": "2026-09-30"}, [1, 5]),
        ({"year": 2026, "observedTo": "2026-10-01"}, [3, 2, 1]),
        ({"year": 2025, "observedFrom": "2026-01-01"}, []),
        ({"outcome": "safe"}, [3, 1, 5]),
        ({"outcome": "unsafe", "kind": "act"}, [2]),
        ({"kind": "condition"}, [4, 3]),
        ({"categoryId": 2}, [3, 2]),
        ({"year": 2026, "outcome": "safe", "categoryId": 2}, [3]),
    ],
)
def test_list_filters(
    editor: TestClient, listed: list[int], params: dict[str, Any], expected: list[int]
) -> None:
    assert listed_ids(editor, **params) == expected


def test_list_pages(editor: TestClient, listed: list[int]) -> None:
    response = editor.get(URL, params={"limit": 2, "offset": 2})

    assert [o["id"] for o in response.json()["observations"]] == [2, 1]
    assert response.json()["totalMatching"] == 5


@pytest.mark.parametrize(
    ("params", "error"),
    [
        ({"month": 10}, "month_requires_year"),
        ({"observedFrom": "2026-10-02", "observedTo": "2026-10-01"}, "invalid_date_range"),
    ],
)
def test_list_rejects_inconsistent_filters(
    editor: TestClient, params: dict[str, Any], error: str
) -> None:
    response = editor.get(URL, params=params)
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == error


@pytest.mark.parametrize(
    "params",
    [
        {"year": 1999},
        {"year": "abc"},
        {"year": 2026, "month": 13},
        {"outcome": "maybe"},
        {"kind": "both"},
        {"categoryId": 0},
        {"observedFrom": "yesterday"},
        {"limit": 0},
        {"limit": 501},
        {"offset": -1},
    ],
)
def test_list_rejects_invalid_parameters(editor: TestClient, params: dict[str, Any]) -> None:
    assert editor.get(URL, params=params).status_code == 422


# Update


def put(client: TestClient, observation_id: int, expected: str, **overrides: Any) -> Any:
    return client.put(
        f"{URL}/{observation_id}", json=payload(expectedUpdatedAt=expected, **overrides)
    )


def test_update_replaces_fields_and_audits_old_and_new(
    editor: TestClient, repository: InMemoryRepository
) -> None:
    first = created(editor)
    repository.audit.clear()

    response = put(
        editor, first["id"], first["updatedAt"], outcome="safe", categoryId=2, description=None
    )

    assert response.status_code == 200
    data = response.json()
    assert (data["outcome"], data["categoryCode"], data["description"]) == ("safe", "ppe", None)
    [(_, _, change)] = repository.audit
    assert change.action == "update"
    assert change.entity_key == f"observations/{first['id']}"
    assert change.old_value is not None and change.new_value is not None
    assert (change.old_value["outcome"], change.new_value["outcome"]) == ("unsafe", "safe")
    assert (change.old_value["category"], change.new_value["category"]) == ("housekeeping", "ppe")
    assert change.new_value["description"] is None


def test_unchanged_update_is_not_written_or_audited(
    editor: TestClient, repository: InMemoryRepository
) -> None:
    first = created(editor)
    repository.audit.clear()
    commits = repository.commits

    response = put(editor, first["id"], first["updatedAt"], areaLocation=" Packaging line 2 ")

    assert response.status_code == 200
    assert response.json() == first
    assert repository.audit == []
    assert repository.commits == commits


def test_stale_update_is_a_conflict_and_writes_nothing(
    editor: TestClient, repository: InMemoryRepository
) -> None:
    first = created(editor)
    repository.audit.clear()

    response = put(editor, first["id"], "2026-10-07T11:00:00Z", outcome="safe")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "edit_conflict"
    assert detail["current"] == first
    assert repository.records[first["id"]].values.outcome == "unsafe"
    assert repository.audit == []


def test_update_requires_a_timezone_aware_expected_timestamp(editor: TestClient) -> None:
    first = created(editor)
    assert put(editor, first["id"], "2026-10-07T12:00:00").status_code == 422
    body = payload()
    assert editor.put(f"{URL}/{first['id']}", json=body).status_code == 422


def test_update_of_missing_observation_is_not_found(editor: TestClient) -> None:
    response = put(editor, 404, NOW.isoformat())

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "observation_not_found"


def test_update_validates_like_create(editor: TestClient, repository: InMemoryRepository) -> None:
    first = created(editor)

    assert put(editor, first["id"], first["updatedAt"], kind="other").status_code == 422
    assert put(editor, first["id"], first["updatedAt"], categoryId=99).status_code == 422
    assert put(editor, first["id"], first["updatedAt"], observedOn="2026-10-08").status_code == 422
    assert repository.records[first["id"]].values == values()


def test_update_may_keep_a_retired_category_but_not_move_to_one(
    editor: TestClient, repository: InMemoryRepository
) -> None:
    [kept, moved] = seed(repository, values(category_id=9), values(category_id=1))
    stamp = (NOW - dt.timedelta(days=1)).isoformat()

    response = put(editor, kept, stamp, categoryId=9, outcome="safe")
    assert response.status_code == 200
    assert response.json()["categoryCode"] == "retired"

    response = put(editor, moved, stamp, categoryId=9)
    assert response.status_code == 422
    assert repository.records[moved].values.category_id == 1


# Delete


def test_delete_removes_the_record_and_audits_its_last_values(
    editor: TestClient, repository: InMemoryRepository
) -> None:
    first = created(editor)
    repository.audit.clear()

    response = editor.delete(f"{URL}/{first['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert repository.records == {}
    [(_, _, change)] = repository.audit
    assert change.action == "delete"
    assert change.new_value is None
    assert change.old_value is not None and change.old_value["category"] == "housekeeping"
    assert editor.delete(f"{URL}/{first['id']}").status_code == 404


def test_each_change_is_its_own_change_set(
    editor: TestClient, repository: InMemoryRepository
) -> None:
    first = created(editor)
    put(editor, first["id"], first["updatedAt"], outcome="safe")
    editor.delete(f"{URL}/{first['id']}")

    assert [c.action for _, _, c in repository.audit] == ["create", "update", "delete"]
    assert len({change_set for _, change_set, _ in repository.audit}) == 3


# Summary and dashboard


def test_summary_counts_the_selected_month(editor: TestClient, listed: list[int]) -> None:
    response = editor.get(URL + "/summary", params={"year": 2026, "month": 10})

    assert response.status_code == 200
    data = response.json()
    assert (data["year"], data["month"]) == (2026, 10)
    assert data["counts"] == {
        "total": 3,
        "safe": 1,
        "unsafe": 2,
        "safeAct": 0,
        "safeCondition": 1,
        "unsafeAct": 1,
        "unsafeCondition": 1,
    }
    by_code = {c["code"]: c for c in data["categories"]}
    assert by_code["ppe"] == {
        "categoryId": 2, "code": "ppe", "name": "PPE", "total": 2, "safe": 1, "unsafe": 1,
    }  # fmt: skip
    assert by_code["housekeeping"]["total"] == 0
    assert sum(c["total"] for c in data["categories"]) == data["counts"]["total"]


def test_summary_without_month_covers_the_year(editor: TestClient, listed: list[int]) -> None:
    data = editor.get(URL + "/summary", params={"year": 2026}).json()

    assert data["month"] is None
    assert data["counts"]["total"] == 4


@pytest.mark.parametrize("params", [{}, {"year": 2026, "month": 0}, {"year": 2101}])
def test_summary_rejects_invalid_periods(editor: TestClient, params: dict[str, Any]) -> None:
    assert editor.get(URL + "/summary", params=params).status_code == 422


def test_dashboard_aggregates_the_year(editor: TestClient, listed: list[int]) -> None:
    response = editor.get(URL + "/dashboard", params={"year": 2026})

    assert response.status_code == 200
    data = response.json()
    assert data["throughMonth"] == 10
    assert data["counts"]["total"] == 4
    assert data["unsafeShare"] == 0.5
    assert data["yearsWithData"] == [2025, 2026]
    totals = [m["counts"]["total"] if m["counts"] else None for m in data["months"]]
    assert totals == [0, 0, 0, 0, 0, 0, 0, 0, 1, 3, None, None]
    fire = next(c for c in data["categories"] if c["code"] == "fire")
    assert fire["monthly"][9] == 1


def test_dashboard_for_a_past_year_shows_all_twelve_months(
    editor: TestClient, listed: list[int]
) -> None:
    data = editor.get(URL + "/dashboard", params={"year": 2025}).json()

    assert data["throughMonth"] == 12
    assert all(m["counts"] is not None for m in data["months"])
    assert data["counts"]["total"] == 1


# Failures and logging


def test_missing_database_is_reported_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def not_configured() -> None:
        raise DatabaseNotConfiguredError("DATABASE_URL is not set")

    monkeypatch.setattr(observations_router, "get_sessionmaker", not_configured)
    app = create_app()
    app.dependency_overrides[get_user_principal] = lambda: principal(P.SAFETY_OBSERVATIONS_VIEW)
    with TestClient(app) as client:
        response = client.get(URL)

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "database_unavailable"


def test_database_errors_roll_back_and_report_unavailable(
    editor: TestClient, repository: InMemoryRepository
) -> None:
    repository.fail = OperationalError("insert", {}, Exception("connection lost"))

    response = editor.post(URL, json=payload())

    assert response.status_code == 503
    assert repository.rollbacks == 1
    assert repository.records == {}
    assert repository.audit == []
    assert editor.get(URL).status_code == 503


def test_saves_are_logged_without_free_text(
    editor: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    created(editor, description="secret-ish free text", areaLocation="Dock 9")

    line = next(
        r.getMessage() for r in caplog.records if "event=safety_observation_saved" in r.getMessage()
    )
    assert "action=create" in line
    assert "observation_id=1" in line
    assert "user=tester" in line
    assert "secret-ish" not in caplog.text
    assert "Dock 9" not in caplog.text
