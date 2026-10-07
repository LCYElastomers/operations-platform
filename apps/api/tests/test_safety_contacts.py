"""Supervisor Safety Contacts: service rules and API behaviour against an in-memory repository.

Database behaviour (constraints, locking, real SQL) is covered by
test_safety_contacts_database.py.
"""

import datetime as dt
import json
import logging
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import replace
from pathlib import Path
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
from app.safety.contacts import router as contacts_router
from app.safety.contacts import service
from app.safety.contacts.repository import (
    ContactFilter,
    ContactRecord,
    ContactValues,
    CountRow,
    DuplicateDisplayNameError,
    SupervisorRecord,
    SupervisorValues,
)
from app.safety.contacts.router import contact_repository

URL = "/api/v1/safety/contacts"
SUPERVISORS = URL + "/supervisors"
NOW = dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.UTC)
SEEDED = NOW - dt.timedelta(days=1)
P = Permission


class InMemoryRepository:
    """Holds committed rows; writes become visible only on commit, like a transaction."""

    def __init__(self) -> None:
        self.supervisor_rows: dict[int, SupervisorRecord] = {}
        self.contact_rows: dict[int, ContactRecord] = {}
        self.pending_supervisors: dict[int, SupervisorRecord | None] = {}
        self.pending_contacts: dict[int, ContactRecord | None] = {}
        self.audit: list[tuple[str, uuid.UUID, AuditChange]] = []
        self.pending_audit: list[tuple[str, uuid.UUID, AuditChange]] = []
        self.next_supervisor_id = 1
        self.next_contact_id = 1
        self.commits = 0
        self.rollbacks = 0
        self.fail: Exception | None = None

    # Visibility

    def _contacts(self) -> dict[int, ContactRecord]:
        merged = {**self.contact_rows, **self.pending_contacts}
        return {k: v for k, v in merged.items() if v is not None}

    def _supervisor_map(self) -> dict[int, SupervisorRecord]:
        merged = {**self.supervisor_rows, **self.pending_supervisors}
        contacted = {c.values.supervisor_id for c in self._contacts().values()}
        return {
            k: replace(v, has_contacts=k in contacted) for k, v in merged.items() if v is not None
        }

    # Supervisors

    def supervisors(self) -> list[SupervisorRecord]:
        if self.fail:
            raise self.fail
        return sorted(
            self._supervisor_map().values(),
            key=lambda s: (s.values.display_name.lower(), s.id),
        )

    def get_supervisor(
        self, supervisor_id: int, *, lock: str | None = None
    ) -> SupervisorRecord | None:
        return self._supervisor_map().get(supervisor_id)

    def _check_name(self, values: SupervisorValues, supervisor_id: int | None) -> None:
        for s in self._supervisor_map().values():
            if (
                s.id != supervisor_id
                and s.values.display_name.lower() == values.display_name.lower()
            ):
                raise DuplicateDisplayNameError(values.display_name)

    def insert_supervisor(self, values: SupervisorValues, *, actor_id: str, at: dt.datetime) -> int:
        if self.fail:
            raise self.fail
        self._check_name(values, None)
        supervisor_id, self.next_supervisor_id = (
            self.next_supervisor_id,
            self.next_supervisor_id + 1,
        )
        self.pending_supervisors[supervisor_id] = SupervisorRecord(
            supervisor_id, values, False, at, actor_id, at, actor_id
        )
        return supervisor_id

    def update_supervisor(
        self, supervisor_id: int, values: SupervisorValues, *, actor_id: str, at: dt.datetime
    ) -> None:
        self._check_name(values, supervisor_id)
        current = self._supervisor_map()[supervisor_id]
        self.pending_supervisors[supervisor_id] = replace(
            current, values=values, updated_at=at, updated_by=actor_id
        )

    def delete_supervisor(self, supervisor_id: int) -> None:
        self.pending_supervisors[supervisor_id] = None

    def contacts_outside(
        self, supervisor_id: int, effective_from: dt.date, effective_to: dt.date | None
    ) -> int:
        return sum(
            1
            for c in self._contacts().values()
            if c.values.supervisor_id == supervisor_id
            and (
                c.values.contact_date < effective_from
                or (effective_to is not None and c.values.contact_date > effective_to)
            )
        )

    # Contacts

    def _matching(self, criteria: ContactFilter) -> list[ContactRecord]:
        def keep(c: ContactRecord) -> bool:
            v = c.values
            return (
                (criteria.contact_from is None or v.contact_date >= criteria.contact_from)
                and (criteria.contact_to is None or v.contact_date <= criteria.contact_to)
                and (criteria.supervisor_id is None or v.supervisor_id == criteria.supervisor_id)
            )

        return [c for c in self._contacts().values() if keep(c)]

    def search(
        self, criteria: ContactFilter, *, limit: int, offset: int
    ) -> tuple[list[ContactRecord], int]:
        if self.fail:
            raise self.fail
        rows = sorted(
            self._matching(criteria), key=lambda c: (c.values.contact_date, c.id), reverse=True
        )
        return [self._named(r) for r in rows[offset : offset + limit]], len(rows)

    def _named(self, record: ContactRecord) -> ContactRecord:
        name = self._supervisor_map()[record.values.supervisor_id].values.display_name
        return replace(record, supervisor_name=name)

    def get(self, contact_id: int, *, for_update: bool = False) -> ContactRecord | None:
        record = self._contacts().get(contact_id)
        return None if record is None else self._named(record)

    def get_by_request(self, request_id: uuid.UUID) -> ContactRecord | None:
        found = [c for c in self._contacts().values() if c.request_id == request_id]
        return self._named(found[0]) if found else None

    def insert(
        self,
        values: ContactValues,
        *,
        request_id: uuid.UUID | None,
        actor_id: str,
        at: dt.datetime,
    ) -> int | None:
        if self.fail:
            raise self.fail
        if request_id is not None and any(
            c.request_id == request_id for c in self._contacts().values()
        ):
            return None
        contact_id, self.next_contact_id = self.next_contact_id, self.next_contact_id + 1
        self.pending_contacts[contact_id] = ContactRecord(
            contact_id, values, "", request_id, at, actor_id, at, actor_id
        )
        return contact_id

    def update(
        self, contact_id: int, values: ContactValues, *, actor_id: str, at: dt.datetime
    ) -> None:
        self.pending_contacts[contact_id] = replace(
            self._contacts()[contact_id], values=values, updated_at=at, updated_by=actor_id
        )

    def delete(self, contact_id: int) -> None:
        self.pending_contacts[contact_id] = None

    def counts(self, criteria: ContactFilter) -> list[CountRow]:
        tally: dict[tuple[int, int], int] = {}
        for c in self._matching(criteria):
            key = (c.values.contact_date.month, c.values.supervisor_id)
            tally[key] = tally.get(key, 0) + 1
        return [CountRow(m, s, n) for (m, s), n in tally.items()]

    def years_with_contacts(self) -> list[int]:
        return sorted({c.values.contact_date.year for c in self._contacts().values()})

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
        for key, s in self.pending_supervisors.items():
            if s is None:
                self.supervisor_rows.pop(key, None)
            else:
                self.supervisor_rows[key] = s
        for key, c in self.pending_contacts.items():
            if c is None:
                self.contact_rows.pop(key, None)
            else:
                self.contact_rows[key] = c
        self.audit.extend(self.pending_audit)
        self.pending_supervisors, self.pending_contacts, self.pending_audit = {}, {}, []
        self.commits += 1

    def rollback(self) -> None:
        self.pending_supervisors, self.pending_contacts, self.pending_audit = {}, {}, []
        self.rollbacks += 1


def sup_values(name: str, **overrides: Any) -> SupervisorValues:
    base: dict[str, Any] = {
        "display_name": name,
        "active": True,
        "participation_eligible": True,
        "effective_from": dt.date(2026, 1, 1),
        "effective_to": None,
    }
    return SupervisorValues(**{**base, **overrides})


def seed_supervisors(repository: InMemoryRepository, *items: SupervisorValues) -> list[int]:
    ids = [repository.insert_supervisor(v, actor_id="seed", at=SEEDED) for v in items]
    repository.commit()
    return ids


def seed_contacts(repository: InMemoryRepository, *items: tuple[dt.date, int]) -> list[int]:
    ids = [
        repository.insert(
            ContactValues(contact_date=day, supervisor_id=supervisor_id),
            request_id=None,
            actor_id="seed",
            at=SEEDED,
        )
        for day, supervisor_id in items
    ]
    repository.commit()
    repository.audit.clear()
    repository.commits = 0
    return [i for i in ids if i is not None]


def sup_record(supervisor_id: int, name: str, **overrides: Any) -> SupervisorRecord:
    return SupervisorRecord(
        supervisor_id, sup_values(name, **overrides), False, SEEDED, "seed", SEEDED, "seed"
    )


# Participation and counts ---------------------------------------------------------


def test_participation_counts_eligible_supervisors_with_a_contact() -> None:
    supervisors = [
        sup_record(1, "Avery"),
        sup_record(2, "Blake"),
        sup_record(3, "Casey"),
        sup_record(4, "Drew", participation_eligible=False),
    ]
    rows = [CountRow(3, 1, 4), CountRow(3, 4, 2), CountRow(2, 2, 1)]

    result = service.participation(supervisors, rows, year=2026, month=3)

    assert (result.participating, result.eligible) == (1, 3)
    assert result.rate == pytest.approx(1 / 3)


def test_participation_respects_effective_dates() -> None:
    supervisors = [
        # Joined mid-March: counts for March.
        sup_record(1, "Avery", effective_from=dt.date(2026, 3, 20)),
        # Left at the end of February: not in March's denominator.
        sup_record(2, "Blake", active=False, effective_to=dt.date(2026, 2, 28)),
        # Starts in April.
        sup_record(3, "Casey", effective_from=dt.date(2026, 4, 1)),
        sup_record(4, "Drew"),
    ]
    rows = [CountRow(3, 1, 1), CountRow(2, 2, 3)]

    march = service.participation(supervisors, rows, year=2026, month=3)
    february = service.participation(supervisors, rows, year=2026, month=2)
    april = service.participation(supervisors, rows, year=2026, month=4)

    assert (march.participating, march.eligible) == (1, 2)
    assert (february.participating, february.eligible) == (1, 2)
    assert (april.participating, april.eligible) == (0, 3)
    assert april.rate == 0


def test_participation_without_eligible_supervisors_has_no_rate() -> None:
    result = service.participation([], [], year=2026, month=1)
    assert (result.participating, result.eligible, result.rate) == (0, 0, None)


@pytest.mark.parametrize(("year", "expected"), [(2025, 12), (2026, 10), (2027, 0)])
def test_started_months(year: int, expected: int) -> None:
    assert service.started_months(year, NOW.date()) == expected


def test_dashboard_counts_months_supervisors_and_participation() -> None:
    supervisors = [
        sup_record(2, "blake"),
        sup_record(1, "Avery"),
        sup_record(3, "Casey", participation_eligible=False),
        sup_record(
            4,
            "Old Timer",
            active=False,
            effective_from=dt.date(2025, 1, 1),
            effective_to=dt.date(2025, 6, 30),
        ),
        sup_record(5, "Zed", effective_from=dt.date(2027, 1, 1)),
    ]
    rows = [CountRow(1, 1, 3), CountRow(1, 2, 1), CountRow(2, 3, 2), CountRow(10, 1, 1)]

    dashboard = service.build_dashboard(
        year=2026, today=NOW.date(), supervisors=supervisors, rows=rows, years_with_data=[2026]
    )

    assert dashboard.through_month == 10
    assert dashboard.contacts == 7
    assert [m.contacts for m in dashboard.months] == [
        4, 2, 0, 0, 0, 0, 0, 0, 0, 1, None, None,
    ]  # fmt: skip
    january = dashboard.months[0].participation
    assert january is not None
    assert (january.participating, january.eligible) == (2, 2)
    february = dashboard.months[1].participation
    assert february is not None
    assert (february.participating, february.eligible) == (0, 2)
    assert dashboard.months[11].participation is None
    # Alphabetical regardless of case or volume; out-of-period supervisors without contacts omitted.
    assert [s.display_name for s in dashboard.supervisors] == ["Avery", "blake", "Casey"]
    avery = dashboard.supervisors[0]
    assert avery.monthly == [3, 0, 0, 0, 0, 0, 0, 0, 0, 1, None, None]
    assert avery.total == 4
    assert sum(s.total for s in dashboard.supervisors) == dashboard.contacts


def test_dashboard_lists_a_former_supervisor_who_has_contacts_in_the_year() -> None:
    supervisors = [
        sup_record(
            4,
            "Old Timer",
            active=False,
            effective_from=dt.date(2025, 1, 1),
            effective_to=dt.date(2025, 6, 30),
        )
    ]
    dashboard = service.build_dashboard(
        year=2025,
        today=NOW.date(),
        supervisors=supervisors,
        rows=[CountRow(3, 4, 2)],
        years_with_data=[2025],
    )
    assert [(s.display_name, s.active, s.total) for s in dashboard.supervisors] == [
        ("Old Timer", False, 2)
    ]
    assert dashboard.through_month == 12
    december = dashboard.months[11].participation
    assert december is not None and december.eligible == 0 and december.rate is None


def test_summary_lists_active_supervisors_and_any_with_contacts() -> None:
    supervisors = [
        sup_record(1, "Casey"),
        sup_record(2, "Avery", active=False, effective_to=dt.date(2026, 3, 31)),
        sup_record(3, "Blake", active=False, effective_to=dt.date(2026, 3, 31)),
    ]
    summary = service.build_summary(
        year=2026, month=3, supervisors=supervisors, rows=[CountRow(3, 2, 2)]
    )
    assert [(s.display_name, s.contacts) for s in summary.supervisors] == [
        ("Avery", 2),
        ("Casey", 0),
    ]
    assert summary.contacts == 2
    assert summary.participation is not None
    assert (summary.participation.participating, summary.participation.eligible) == (1, 3)

    year = service.build_summary(year=2026, month=None, supervisors=supervisors, rows=[])
    assert year.participation is None


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
    assert (criteria.contact_from, criteria.contact_to) == (start, end)


# API -----------------------------------------------------------------------------


def principal(*permissions: Permission) -> UserPrincipal:
    return UserPrincipal("tester", authenticated=True, granted=frozenset(permissions))


@pytest.fixture
def repository() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(contacts_router, "_now", lambda: NOW)


def make_client(repository: InMemoryRepository, user: UserPrincipal | None) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[contact_repository] = lambda: repository
    if user is not None:
        app.dependency_overrides[get_user_principal] = lambda: user
    with TestClient(app) as client:
        yield client


@pytest.fixture
def editor(repository: InMemoryRepository) -> Iterator[TestClient]:
    yield from make_client(repository, principal(P.SAFETY_CONTACTS_EDIT))


@pytest.fixture
def viewer(repository: InMemoryRepository) -> Iterator[TestClient]:
    yield from make_client(repository, principal(P.SAFETY_CONTACTS_VIEW))


@pytest.fixture
def team(repository: InMemoryRepository) -> list[int]:
    return seed_supervisors(
        repository,
        sup_values("Casey Brown"),
        sup_values("avery Jones"),
        sup_values("Blake Smith", active=False, effective_to=dt.date(2026, 6, 30)),
    )


def sup_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "displayName": "Jordan Lee",
        "active": True,
        "participationEligible": True,
        "effectiveFrom": "2026-01-01",
        "effectiveTo": None,
        **overrides,
    }


def contact_payload(**overrides: Any) -> dict[str, Any]:
    return {"contactDate": "2026-10-06", "supervisorId": 1, **overrides}


def created(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post(URL, json=contact_payload(**overrides))
    assert response.status_code == 201, response.text
    return dict(response.json())


# Authorization


def test_anonymous_requests_are_refused(repository: InMemoryRepository, team: list[int]) -> None:
    seed_contacts(repository, (dt.date(2026, 10, 1), 1))
    for client in make_client(repository, None):
        for path in ("", "/supervisors", "/summary?year=2026", "/dashboard?year=2026"):
            assert client.get(URL + path).status_code == 401
        assert client.post(URL, json=contact_payload()).status_code == 401
        assert client.post(SUPERVISORS, json=sup_payload()).status_code == 401
        assert client.delete(f"{URL}/1").status_code == 401
    assert len(repository.contact_rows) == 1
    assert repository.audit == []


def test_viewer_reads_but_cannot_write(
    viewer: TestClient, repository: InMemoryRepository, team: list[int]
) -> None:
    [contact_id] = seed_contacts(repository, (dt.date(2026, 10, 1), 1))

    for path in ("", "/supervisors", "/summary?year=2026&month=10", "/dashboard?year=2026"):
        assert viewer.get(URL + path).status_code == 200
    assert viewer.get(URL).json()["canEdit"] is False
    assert viewer.get(SUPERVISORS).json()["canEdit"] is False

    response = viewer.post(URL, json=contact_payload())
    assert response.status_code == 403
    assert response.json()["detail"]["permission"] == "safety.contacts.edit"
    stamp = SEEDED.isoformat()
    assert (
        viewer.put(f"{URL}/{contact_id}", json=contact_payload(expectedUpdatedAt=stamp)).status_code
        == 403
    )
    assert viewer.delete(f"{URL}/{contact_id}").status_code == 403
    assert viewer.post(SUPERVISORS, json=sup_payload()).status_code == 403
    assert (
        viewer.put(f"{SUPERVISORS}/1", json=sup_payload(expectedUpdatedAt=stamp)).status_code == 403
    )
    assert viewer.delete(f"{SUPERVISORS}/2").status_code == 403
    assert list(repository.contact_rows) == [contact_id]
    assert len(repository.supervisor_rows) == 3
    assert repository.audit == []


@pytest.mark.parametrize(
    ("granted", "can_view", "can_edit"),
    [
        (P.SAFETY_VIEW, True, False),
        (P.SAFETY_EDIT, True, True),
        (P.SAFETY_CONTACTS_VIEW, True, False),
        (P.SAFETY_CONTACTS_EDIT, True, True),
        (P.SAFETY_OBSERVATIONS_EDIT, False, False),
        (P.SAFETY_INCIDENTS_EDIT, False, False),
    ],
)
def test_module_grants_cover_contacts(
    repository: InMemoryRepository,
    team: list[int],
    granted: Permission,
    can_view: bool,
    can_edit: bool,
) -> None:
    for client in make_client(repository, principal(granted)):
        response = client.get(URL)
        assert response.status_code == (200 if can_view else 403)
        if can_view:
            assert response.json()["canEdit"] is can_edit
        assert client.post(URL, json=contact_payload()).status_code == (201 if can_edit else 403)
        assert client.post(SUPERVISORS, json=sup_payload()).status_code == (
            201 if can_edit else 403
        )


def test_development_mode_records_the_development_user(
    repository: InMemoryRepository, team: list[int]
) -> None:
    app = create_app()
    app.dependency_overrides[contact_repository] = lambda: repository
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, user_auth_mode="development-unauthenticated"
    )
    with TestClient(app) as client:
        response = client.post(URL, json=contact_payload())

    assert response.status_code == 201
    assert response.json()["createdBy"] == "development-user"
    assert repository.audit[0][0] == "development-user"


# Supervisors


def test_supervisors_are_listed_alphabetically_with_inactive(
    editor: TestClient, team: list[int]
) -> None:
    data = editor.get(SUPERVISORS).json()

    assert data["canEdit"] is True
    assert [s["displayName"] for s in data["supervisors"]] == [
        "avery Jones",
        "Blake Smith",
        "Casey Brown",
    ]
    blake = data["supervisors"][1]
    assert blake["active"] is False
    assert blake["effectiveTo"] == "2026-06-30"
    assert blake["hasContacts"] is False


def test_create_supervisor_normalizes_the_name_and_audits(
    editor: TestClient, repository: InMemoryRepository
) -> None:
    response = editor.post(SUPERVISORS, json=sup_payload(displayName="  Jordan   Lee "))

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["displayName"] == "Jordan Lee"
    assert data["participationEligible"] is True
    assert data["createdBy"] == "tester"
    [(actor, _, change)] = repository.audit
    assert actor == "tester"
    assert change.action == "create"
    assert change.entity_type == "safety.contact_supervisor"
    assert change.entity_key == f"contact-supervisors/{data['id']}"
    assert change.old_value is None
    assert change.new_value == {
        "display_name": "Jordan Lee",
        "active": True,
        "participation_eligible": True,
        "effective_from": "2026-01-01",
        "effective_to": None,
    }


@pytest.mark.parametrize("name", ["casey brown", "CASEY  BROWN", " Casey Brown "])
def test_supervisor_names_are_unique_ignoring_case_and_spacing(
    editor: TestClient, repository: InMemoryRepository, team: list[int], name: str
) -> None:
    response = editor.post(SUPERVISORS, json=sup_payload(displayName=name))

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "duplicate_display_name"
    assert len(repository.supervisor_rows) == 3
    assert repository.audit == []


@pytest.mark.parametrize(
    "bad",
    [
        {"displayName": ""},
        {"displayName": "   "},
        {"displayName": "x" * 101},
        {"displayName": 7},
        {"active": None},
        {"active": "true"},
        {"participationEligible": 1},
        {"effectiveFrom": None},
        {"effectiveFrom": "1999-12-31"},
        {"effectiveFrom": "01/01/2026"},
        {"effectiveTo": "2026-13-01"},
        {"rating": "good"},
        {"target": 8},
    ],
)
def test_create_supervisor_rejects_invalid_fields(
    editor: TestClient, repository: InMemoryRepository, bad: dict[str, Any]
) -> None:
    assert editor.post(SUPERVISORS, json=sup_payload(**bad)).status_code == 422, bad
    assert repository.supervisor_rows == {}


@pytest.mark.parametrize(
    "missing", ["displayName", "active", "participationEligible", "effectiveFrom", "effectiveTo"]
)
def test_create_supervisor_requires_every_field(editor: TestClient, missing: str) -> None:
    body = sup_payload()
    del body[missing]
    assert editor.post(SUPERVISORS, json=body).status_code == 422


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"effectiveFrom": "2026-05-01", "effectiveTo": "2026-04-30"}, "effective_period_invalid"),
        ({"active": False, "effectiveTo": None}, "inactive_requires_end_date"),
    ],
)
def test_create_supervisor_enforces_period_rules(
    editor: TestClient, repository: InMemoryRepository, overrides: dict[str, Any], error: str
) -> None:
    response = editor.post(SUPERVISORS, json=sup_payload(**overrides))
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == error
    assert repository.supervisor_rows == {}


def test_supervisor_can_be_ineligible_and_inactive_with_an_end_date(editor: TestClient) -> None:
    response = editor.post(
        SUPERVISORS,
        json=sup_payload(active=False, participationEligible=False, effectiveTo="2026-03-31"),
    )
    assert response.status_code == 201
    assert (response.json()["active"], response.json()["participationEligible"]) == (False, False)


def supervisor_put(client: TestClient, supervisor_id: int, **overrides: Any) -> Any:
    current = next(
        s for s in client.get(SUPERVISORS).json()["supervisors"] if s["id"] == supervisor_id
    )
    body = {
        key: current[key]
        for key in (
            "displayName",
            "active",
            "participationEligible",
            "effectiveFrom",
            "effectiveTo",
        )
    }
    return client.put(
        f"{SUPERVISORS}/{supervisor_id}",
        json={**body, "expectedUpdatedAt": current["updatedAt"], **overrides},
    )


def test_update_supervisor_corrects_the_name_and_audits_old_and_new(
    editor: TestClient, repository: InMemoryRepository, team: list[int]
) -> None:
    response = supervisor_put(editor, 1, displayName="Casey Browne")

    assert response.status_code == 200, response.text
    assert response.json()["displayName"] == "Casey Browne"
    assert response.json()["updatedAt"] == "2026-10-07T12:00:00Z"
    [(_, _, change)] = repository.audit
    assert change.action == "update"
    assert change.entity_key == "contact-supervisors/1"
    assert change.old_value is not None and change.old_value["display_name"] == "Casey Brown"
    assert change.new_value is not None and change.new_value["display_name"] == "Casey Browne"


def test_supervisor_can_change_the_case_of_its_own_name(
    editor: TestClient, team: list[int]
) -> None:
    assert supervisor_put(editor, 2, displayName="Avery Jones").status_code == 200


def test_unchanged_supervisor_is_not_written(
    editor: TestClient, repository: InMemoryRepository, team: list[int]
) -> None:
    response = supervisor_put(editor, 1)
    assert response.status_code == 200
    assert response.json()["updatedAt"] == SEEDED.isoformat().replace("+00:00", "Z")
    assert repository.audit == []
    assert repository.commits == 1  # only the seed


def test_deactivating_needs_an_end_date(
    editor: TestClient, repository: InMemoryRepository, team: list[int]
) -> None:
    response = supervisor_put(editor, 1, active=False)
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "inactive_requires_end_date"

    response = supervisor_put(editor, 1, active=False, effectiveTo="2026-10-07")
    assert response.status_code == 200
    assert response.json()["active"] is False


def test_effective_dates_cannot_exclude_recorded_contacts(
    editor: TestClient, repository: InMemoryRepository, team: list[int]
) -> None:
    seed_contacts(repository, (dt.date(2026, 3, 15), 1), (dt.date(2026, 9, 2), 1))

    response = supervisor_put(editor, 1, effectiveFrom="2026-04-01")
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "contacts_outside_effective_period"
    assert response.json()["detail"]["contacts"] == 1

    response = supervisor_put(editor, 1, active=False, effectiveTo="2026-08-31")
    assert response.json()["detail"]["contacts"] == 1
    assert repository.audit == []

    assert supervisor_put(editor, 1, active=False, effectiveTo="2026-09-30").status_code == 200


def test_stale_supervisor_update_is_a_conflict(
    editor: TestClient, repository: InMemoryRepository, team: list[int]
) -> None:
    response = editor.put(
        f"{SUPERVISORS}/1",
        json=sup_payload(displayName="Casey B", expectedUpdatedAt="2026-01-01T00:00:00Z"),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "edit_conflict"
    assert response.json()["detail"]["current"]["displayName"] == "Casey Brown"
    assert repository.audit == []


def test_update_unknown_supervisor_is_not_found(editor: TestClient) -> None:
    response = editor.put(f"{SUPERVISORS}/99", json=sup_payload(expectedUpdatedAt=NOW.isoformat()))
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "supervisor_not_found"


def test_supervisor_without_contacts_can_be_deleted_with_audit(
    editor: TestClient, repository: InMemoryRepository, team: list[int]
) -> None:
    assert editor.delete(f"{SUPERVISORS}/2").status_code == 204
    assert 2 not in repository.supervisor_rows
    [(_, _, change)] = repository.audit
    assert (change.action, change.entity_key, change.new_value) == (
        "delete",
        "contact-supervisors/2",
        None,
    )
    assert change.old_value is not None and change.old_value["display_name"] == "avery Jones"


def test_supervisor_with_contacts_cannot_be_deleted(
    editor: TestClient, repository: InMemoryRepository, team: list[int]
) -> None:
    seed_contacts(repository, (dt.date(2026, 3, 15), 3))

    response = editor.delete(f"{SUPERVISORS}/3")

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "supervisor_has_contacts"
    assert 3 in repository.supervisor_rows
    assert repository.audit == []
    listed = editor.get(SUPERVISORS).json()["supervisors"]
    assert next(s for s in listed if s["id"] == 3)["hasContacts"] is True


# Contacts: create


def test_create_contact_returns_it_and_audits_ids_only(
    editor: TestClient, repository: InMemoryRepository, team: list[int]
) -> None:
    data = created(editor)

    assert data == {
        "id": 1,
        "contactDate": "2026-10-06",
        "supervisorId": 1,
        "supervisorName": "Casey Brown",
        "createdAt": "2026-10-07T12:00:00Z",
        "createdBy": "tester",
        "updatedAt": "2026-10-07T12:00:00Z",
        "updatedBy": "tester",
    }
    assert repository.commits == 2  # the seeded supervisors, then the contact
    [(actor, _, change)] = repository.audit
    assert actor == "tester"
    assert (change.action, change.entity_type, change.entity_key) == (
        "create",
        "safety.contact",
        "contacts/1",
    )
    assert change.old_value is None
    assert change.new_value == {"contact_date": "2026-10-06", "supervisor_id": 1}


def test_each_plus_one_creates_exactly_one_record(
    editor: TestClient, repository: InMemoryRepository, team: list[int]
) -> None:
    created(editor)
    created(editor)
    assert len(repository.contact_rows) == 2
    assert len(repository.audit) == 2


def test_resubmitting_a_request_returns_the_first_contact(
    editor: TestClient, repository: InMemoryRepository, team: list[int]
) -> None:
    request_id = str(uuid.uuid4())
    first = editor.post(URL, json=contact_payload(requestId=request_id))
    again = editor.post(URL, json=contact_payload(requestId=request_id))

    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert len(repository.contact_rows) == 1
    assert len(repository.audit) == 1


def test_a_request_id_cannot_be_reused_for_a_different_contact(
    editor: TestClient, repository: InMemoryRepository, team: list[int]
) -> None:
    request_id = str(uuid.uuid4())
    editor.post(URL, json=contact_payload(requestId=request_id))
    response = editor.post(URL, json=contact_payload(requestId=request_id, supervisorId=2))

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "request_id_reused"
    assert len(repository.contact_rows) == 1


def test_create_rejects_future_dates_but_accepts_today(
    editor: TestClient, repository: InMemoryRepository, team: list[int]
) -> None:
    response = editor.post(URL, json=contact_payload(contactDate="2026-10-08"))
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "error": "contact_date_in_future",
        "message": "The contact date cannot be in the future.",
        "today": "2026-10-07",
    }
    assert repository.contact_rows == {}

    assert editor.post(URL, json=contact_payload(contactDate="2026-10-07")).status_code == 201


# 22:00 CDT on 7 October in Baytown is already 8 October in UTC.
BAYTOWN_EVENING = dt.datetime(2026, 10, 8, 3, 0, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        (dt.datetime(2026, 10, 8, 4, 59, tzinfo=dt.UTC), dt.date(2026, 10, 7)),  # 23:59 CDT
        (dt.datetime(2026, 10, 8, 5, 0, tzinfo=dt.UTC), dt.date(2026, 10, 8)),  # midnight CDT
        (dt.datetime(2026, 1, 1, 5, 59, tzinfo=dt.UTC), dt.date(2025, 12, 31)),  # 23:59 CST
        (dt.datetime(2026, 1, 1, 6, 0, tzinfo=dt.UTC), dt.date(2026, 1, 1)),  # midnight CST
        (dt.datetime(2026, 3, 9, 4, 59, tzinfo=dt.UTC), dt.date(2026, 3, 8)),  # DST began 8 March
        (dt.datetime(2026, 3, 9, 5, 0, tzinfo=dt.UTC), dt.date(2026, 3, 9)),
        (
            dt.datetime(2026, 10, 7, 23, 0, tzinfo=dt.timezone(dt.timedelta(hours=5))),
            dt.date(2026, 10, 7),
        ),
    ],
)
def test_site_today_is_the_baytown_calendar_date(instant: dt.datetime, expected: dt.date) -> None:
    assert service.site_today(instant) == expected


def test_create_uses_the_baytown_date_not_the_utc_date(
    editor: TestClient,
    repository: InMemoryRepository,
    team: list[int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(contacts_router, "_now", lambda: BAYTOWN_EVENING)

    response = editor.post(URL, json=contact_payload(contactDate="2026-10-08"))
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "contact_date_in_future"
    assert response.json()["detail"]["today"] == "2026-10-07"
    assert repository.contact_rows == {}

    assert editor.post(URL, json=contact_payload(contactDate="2026-10-07")).status_code == 201


@pytest.mark.parametrize(
    "bad",
    [
        {"contactDate": "06/10/2026"},
        {"contactDate": "2026-02-30"},
        {"contactDate": "1999-12-31"},
        {"contactDate": None},
        {"supervisorId": 0},
        {"supervisorId": "1"},
        {"supervisorId": True},
        {"supervisorId": None},
        {"requestId": "not-a-uuid"},
        {"employee": "Someone"},
        {"notes": "text"},
    ],
)
def test_create_rejects_invalid_fields(
    editor: TestClient, repository: InMemoryRepository, team: list[int], bad: dict[str, Any]
) -> None:
    assert editor.post(URL, json=contact_payload(**bad)).status_code == 422, bad
    assert repository.contact_rows == {}


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"supervisorId": 99}, "unknown_supervisor"),
        ({"supervisorId": 3, "contactDate": "2026-05-01"}, "supervisor_inactive"),
        ({"contactDate": "2025-12-31"}, "outside_effective_period"),
    ],
)
def test_create_requires_a_creditable_supervisor(
    editor: TestClient,
    repository: InMemoryRepository,
    team: list[int],
    overrides: dict[str, Any],
    error: str,
) -> None:
    response = editor.post(URL, json=contact_payload(**overrides))

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == error
    assert repository.contact_rows == {}
    assert repository.audit == []


# Contacts: list


@pytest.fixture
def listed(repository: InMemoryRepository, team: list[int]) -> list[int]:
    return seed_contacts(
        repository,
        (dt.date(2026, 9, 30), 1),
        (dt.date(2026, 10, 1), 2),
        (dt.date(2026, 10, 1), 1),
        (dt.date(2026, 10, 5), 2),
        (dt.date(2026, 2, 5), 3),
    )


def listed_ids(client: TestClient, **params: Any) -> list[int]:
    response = client.get(URL, params=params)
    assert response.status_code == 200, response.text
    return [c["id"] for c in response.json()["contacts"]]


def test_list_is_newest_first_with_names(editor: TestClient, listed: list[int]) -> None:
    data = editor.get(URL).json()

    assert [c["id"] for c in data["contacts"]] == [4, 3, 2, 1, 5]
    assert data["contacts"][0]["supervisorName"] == "avery Jones"
    assert data["totalMatching"] == 5


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"year": 2026}, [4, 3, 2, 1, 5]),
        ({"year": 2026, "month": 10}, [4, 3, 2]),
        ({"year": 2026, "month": 2}, [5]),
        ({"year": 2025}, []),
        ({"contactFrom": "2026-10-01", "contactTo": "2026-10-01"}, [3, 2]),
        ({"contactTo": "2026-09-30"}, [1, 5]),
        ({"supervisorId": 2}, [4, 2]),
        ({"year": 2026, "month": 10, "supervisorId": 1}, [3]),
    ],
)
def test_list_filters(
    editor: TestClient, listed: list[int], params: dict[str, Any], expected: list[int]
) -> None:
    assert listed_ids(editor, **params) == expected


def test_list_pages(editor: TestClient, listed: list[int]) -> None:
    response = editor.get(URL, params={"limit": 2, "offset": 2})
    assert [c["id"] for c in response.json()["contacts"]] == [2, 1]
    assert response.json()["totalMatching"] == 5


@pytest.mark.parametrize(
    ("params", "error"),
    [
        ({"month": 10}, "month_requires_year"),
        ({"contactFrom": "2026-10-02", "contactTo": "2026-10-01"}, "invalid_date_range"),
    ],
)
def test_list_rejects_inconsistent_filters(
    editor: TestClient, params: dict[str, Any], error: str
) -> None:
    response = editor.get(URL, params=params)
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == error


@pytest.mark.parametrize(
    "params", [{"year": 1999}, {"year": 2026, "month": 13}, {"limit": 0}, {"limit": 501}]
)
def test_list_validates_parameters(editor: TestClient, params: dict[str, Any]) -> None:
    assert editor.get(URL, params=params).status_code == 422


# Contacts: update and delete


def contact_put(client: TestClient, contact_id: int, **overrides: Any) -> Any:
    current = next(c for c in client.get(URL).json()["contacts"] if c["id"] == contact_id)
    body = {
        "contactDate": current["contactDate"],
        "supervisorId": current["supervisorId"],
        "expectedUpdatedAt": current["updatedAt"],
    }
    return client.put(f"{URL}/{contact_id}", json={**body, **overrides})


def test_update_changes_date_or_supervisor_with_audit(
    editor: TestClient, repository: InMemoryRepository, listed: list[int]
) -> None:
    response = contact_put(editor, 3, contactDate="2026-10-02", supervisorId=2)

    assert response.status_code == 200, response.text
    assert (response.json()["contactDate"], response.json()["supervisorName"]) == (
        "2026-10-02",
        "avery Jones",
    )
    [(_, _, change)] = repository.audit
    assert change.action == "update"
    assert change.old_value == {"contact_date": "2026-10-01", "supervisor_id": 1}
    assert change.new_value == {"contact_date": "2026-10-02", "supervisor_id": 2}


def test_unchanged_contact_is_not_written(
    editor: TestClient, repository: InMemoryRepository, listed: list[int]
) -> None:
    assert contact_put(editor, 3).status_code == 200
    assert repository.audit == []


def test_contact_can_keep_a_supervisor_who_became_inactive(
    editor: TestClient, repository: InMemoryRepository, listed: list[int]
) -> None:
    response = contact_put(editor, 5, contactDate="2026-02-06")
    assert response.status_code == 200

    response = contact_put(editor, 3, supervisorId=3, contactDate="2026-06-01")
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "supervisor_inactive"

    response = contact_put(editor, 5, contactDate="2026-07-01")
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "outside_effective_period"


def test_update_rejects_future_dates(editor: TestClient, listed: list[int]) -> None:
    response = contact_put(editor, 3, contactDate="2026-10-08")
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "contact_date_in_future"


def test_update_uses_the_baytown_date_not_the_utc_date(
    editor: TestClient, listed: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(contacts_router, "_now", lambda: BAYTOWN_EVENING)

    response = contact_put(editor, 3, contactDate="2026-10-08")
    assert response.status_code == 422
    assert response.json()["detail"]["today"] == "2026-10-07"

    response = contact_put(editor, 3, contactDate="2026-10-07")
    assert response.status_code == 200
    assert response.json()["contactDate"] == "2026-10-07"


def test_stale_contact_update_is_a_conflict(
    editor: TestClient, repository: InMemoryRepository, listed: list[int]
) -> None:
    response = contact_put(
        editor, 3, contactDate="2026-10-02", expectedUpdatedAt="2026-01-01T00:00:00Z"
    )
    assert response.status_code == 409
    assert response.json()["detail"]["current"]["contactDate"] == "2026-10-01"
    assert repository.audit == []


def test_update_unknown_contact_is_not_found(editor: TestClient, team: list[int]) -> None:
    response = editor.put(f"{URL}/99", json=contact_payload(expectedUpdatedAt=NOW.isoformat()))
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "contact_not_found"


def test_delete_is_audited_and_undo_removes_exactly_the_new_record(
    editor: TestClient, repository: InMemoryRepository, listed: list[int]
) -> None:
    new = created(editor)
    repository.audit.clear()

    assert editor.delete(f"{URL}/{new['id']}").status_code == 204

    assert new["id"] not in repository.contact_rows
    assert len(repository.contact_rows) == 5
    [(_, _, change)] = repository.audit
    assert (change.action, change.entity_key) == ("delete", f"contacts/{new['id']}")
    assert change.old_value == {"contact_date": "2026-10-06", "supervisor_id": 1}
    assert change.new_value is None
    assert editor.delete(f"{URL}/{new['id']}").status_code == 404


# Summary and dashboard


def test_month_summary_has_per_supervisor_counts_and_participation(
    editor: TestClient, listed: list[int]
) -> None:
    data = editor.get(URL + "/summary", params={"year": 2026, "month": 10}).json()

    assert data["contacts"] == 3
    assert [(s["displayName"], s["contacts"]) for s in data["supervisors"]] == [
        ("avery Jones", 2),
        ("Casey Brown", 1),
    ]
    assert data["participation"] == {"participating": 2, "eligible": 2, "rate": 1.0}


def test_dashboard_endpoint_is_alphabetical_with_null_future_months(
    editor: TestClient, listed: list[int]
) -> None:
    data = editor.get(URL + "/dashboard", params={"year": 2026}).json()

    assert data["throughMonth"] == 10
    assert data["contacts"] == 5
    assert [s["displayName"] for s in data["supervisors"]] == [
        "avery Jones",
        "Blake Smith",
        "Casey Brown",
    ]
    assert data["supervisors"][1]["monthly"][:3] == [0, 1, 0]
    assert data["supervisors"][0]["monthly"][10:] == [None, None]
    assert data["months"][1]["participation"] == {"participating": 1, "eligible": 3, "rate": 1 / 3}
    assert data["months"][11] == {"month": 12, "contacts": None, "participation": None}
    assert data["yearsWithData"] == [2026]
    assert "target" not in str(data).lower()


def test_dashboard_months_started_follow_the_baytown_date(
    editor: TestClient, listed: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 22:00 CDT on 31 October is 1 November in UTC; November has not started in Baytown.
    monkeypatch.setattr(
        contacts_router, "_now", lambda: dt.datetime(2026, 11, 1, 3, 0, tzinfo=dt.UTC)
    )

    data = editor.get(URL + "/dashboard", params={"year": 2026}).json()

    assert data["throughMonth"] == 10
    assert data["months"][10] == {"month": 11, "contacts": None, "participation": None}


def test_dashboard_requires_a_year(editor: TestClient) -> None:
    assert editor.get(URL + "/dashboard").status_code == 422


# Failures


def test_database_failure_is_a_503_and_nothing_is_saved(
    editor: TestClient, repository: InMemoryRepository, team: list[int]
) -> None:
    repository.fail = OperationalError("SELECT 1", {}, Exception("down"))

    assert editor.get(URL).status_code == 503
    assert editor.get(SUPERVISORS).status_code == 503
    response = editor.post(URL, json=contact_payload())
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "database_unavailable"
    assert repository.contact_rows == {}


def test_missing_database_is_a_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable() -> Any:
        raise DatabaseNotConfiguredError

    monkeypatch.setattr(contacts_router, "get_sessionmaker", unavailable)
    for client in make_client(InMemoryRepository(), principal(P.SAFETY_CONTACTS_EDIT)):
        client.app.dependency_overrides.pop(contact_repository)  # type: ignore[attr-defined]
        assert client.get(URL).status_code == 503


def test_legacy_template_has_no_year_names_or_values() -> None:
    path = Path(__file__).resolve().parents[1] / "import_templates"
    template = json.loads((path / "safety_contacts_legacy.template.json").read_text("utf-8"))

    assert template["year"] is None
    assert template["applied"] is False
    assert len(template["supervisors"]) == 20
    for row in template["supervisors"]:
        assert row["sourceName"] is None
        assert row["approvedDisplayName"] is None
        assert row["months"] == [None] * 12


def test_logs_identify_records_without_names(
    editor: TestClient, team: list[int], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.safety.contacts.service"):
        created(editor)
        editor.post(SUPERVISORS, json=sup_payload(displayName="Jordan Lee"))

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "event=safety_contact_saved action=create id=1" in messages
    assert "event=safety_contact_supervisor_saved action=create" in messages
    assert "Casey" not in messages
    assert "Jordan" not in messages
