"""PostgreSQL integration tests for Supervisor Safety Contacts (migration 0005).

Enabled by TEST_DATABASE_URL (see test_moisture_database.py). Each test runs in
a transaction that is rolled back. Records use 2003 dates and test-only names,
and audit queries filter on the test actors, so other rows are never read.
"""

import datetime as dt
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from postgres_support import requires_postgres
from sqlalchemy import Engine, delete, insert, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.safety.contacts import service
from app.safety.contacts.models import ContactSupervisor, SupervisorSafetyContact
from app.safety.contacts.repository import (
    DatabaseContactRepository,
    DuplicateDisplayNameError,
    SupervisorValues,
)
from app.safety.contacts.schemas import (
    ContactCreate,
    ContactUpdate,
    SupervisorInput,
    SupervisorUpdate,
)

pytestmark = requires_postgres

NOW = dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.UTC)
START = dt.date(2003, 1, 1)
ACTORS = ["db-tester", "db-second"]


class NonCommittingRepository(DatabaseContactRepository):
    """Flushes instead of committing, so the test transaction can be rolled back."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.session = session

    def commit(self) -> None:
        self.session.flush()

    def rollback(self) -> None:
        pass


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with engine.connect() as connection:
        transaction = connection.begin()
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        yield db
        db.close()
        transaction.rollback()


@pytest.fixture
def repository(session: Session) -> NonCommittingRepository:
    return NonCommittingRepository(session)


def add_supervisor(repository: DatabaseContactRepository, name: str, **overrides: Any) -> int:
    data: dict[str, Any] = {
        "displayName": name,
        "active": True,
        "participationEligible": True,
        "effectiveFrom": START.isoformat(),
        "effectiveTo": None,
        **overrides,
    }
    record = service.create_supervisor(
        repository, SupervisorInput.model_validate(data), actor_id="db-tester", now=NOW
    )
    return record.id


def add_contact(
    repository: DatabaseContactRepository, supervisor_id: int, day: dt.date, **extra: Any
) -> int:
    data = {"contactDate": day.isoformat(), "supervisorId": supervisor_id, **extra}
    record, created = service.create_contact(
        repository, ContactCreate.model_validate(data), actor_id="db-tester", now=NOW
    )
    assert created
    return record.id


def audit_events(session: Session, entity_type: str) -> list[AuditEvent]:
    return list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_type == entity_type)
            .where(AuditEvent.actor_id.in_(ACTORS))
            .order_by(AuditEvent.id)
        )
    )


# Schema --------------------------------------------------------------------------


def test_tables_constraints_and_indexes(engine: Engine) -> None:
    inspector = inspect(engine)

    assert inspector.has_table("contact_supervisors", schema="safety")
    assert inspector.has_table("supervisor_safety_contacts", schema="safety")
    [fk] = inspector.get_foreign_keys("supervisor_safety_contacts", schema="safety")
    assert (fk["name"], fk["constrained_columns"], fk["referred_table"]) == (
        "fk_supervisor_safety_contacts_supervisor",
        ["supervisor_id"],
        "contact_supervisors",
    )
    assert fk["options"].get("ondelete") == "RESTRICT"
    assert {
        c["name"] for c in inspector.get_check_constraints("contact_supervisors", "safety")
    } == {
        "ck_contact_supervisors_display_name",
        "ck_contact_supervisors_effective_from",
        "ck_contact_supervisors_effective_period",
        "ck_contact_supervisors_inactive_has_end",
    }
    assert {
        c["name"] for c in inspector.get_check_constraints("supervisor_safety_contacts", "safety")
    } == {"ck_supervisor_safety_contacts_contact_date"}
    assert {i["name"] for i in inspector.get_indexes("supervisor_safety_contacts", "safety")} == {
        "ix_supervisor_safety_contacts_contact_date",
        "ix_supervisor_safety_contacts_supervisor_id",
        # Backs the request_id unique constraint.
        "uq_supervisor_safety_contacts_request_id",
    }
    assert [
        (u["name"], u["column_names"])
        for u in inspector.get_unique_constraints("supervisor_safety_contacts", "safety")
    ] == [("uq_supervisor_safety_contacts_request_id", ["request_id"])]
    [name_index] = inspector.get_indexes("contact_supervisors", "safety")
    assert name_index["name"] == "uq_contact_supervisors_display_name"
    assert name_index["unique"]

    supervisor_nullable = {
        c["name"] for c in inspector.get_columns("contact_supervisors", "safety") if c["nullable"]
    }
    assert supervisor_nullable == {"effective_to"}
    contact_nullable = {
        c["name"]
        for c in inspector.get_columns("supervisor_safety_contacts", "safety")
        if c["nullable"]
    }
    assert contact_nullable == {"request_id"}


def test_contact_columns_are_only_date_supervisor_and_system_fields(engine: Engine) -> None:
    columns = {
        c["name"] for c in inspect(engine).get_columns("supervisor_safety_contacts", "safety")
    }
    assert columns == {
        "id",
        "contact_date",
        "supervisor_id",
        "request_id",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
    }


# Service round trip ----------------------------------------------------------------


def test_supervisor_and_contact_round_trip_with_audit(
    session: Session, repository: NonCommittingRepository
) -> None:
    supervisor_id = add_supervisor(repository, "Zz Db Test Avery")
    other_id = add_supervisor(repository, "Zz Db Test Blake")
    contact_id = add_contact(repository, supervisor_id, dt.date(2003, 5, 14))

    current = repository.get(contact_id)
    assert current is not None
    assert current.supervisor_name == "Zz Db Test Avery"
    later = NOW + dt.timedelta(minutes=5)
    updated = service.update_contact(
        repository,
        contact_id,
        ContactUpdate.model_validate(
            {
                "contactDate": "2003-05-15",
                "supervisorId": other_id,
                "expectedUpdatedAt": current.updated_at.isoformat(),
            }
        ),
        actor_id="db-second",
        now=later,
    )
    assert (updated.values.contact_date, updated.supervisor_name) == (
        dt.date(2003, 5, 15),
        "Zz Db Test Blake",
    )
    assert (updated.created_by, updated.updated_by) == ("db-tester", "db-second")

    service.delete_contact(repository, contact_id, actor_id="db-second", now=later)
    assert repository.get(contact_id) is None

    events = audit_events(session, service.CONTACT_ENTITY_TYPE)
    assert [(e.actor_id, e.action) for e in events] == [
        ("db-tester", "create"),
        ("db-second", "update"),
        ("db-second", "delete"),
    ]
    assert {e.entity_key for e in events} == {f"contacts/{contact_id}"}
    assert events[0].new_value == {"contact_date": "2003-05-14", "supervisor_id": supervisor_id}
    assert events[1].old_value == events[0].new_value
    assert events[1].new_value == {"contact_date": "2003-05-15", "supervisor_id": other_id}
    assert events[2].old_value == events[1].new_value
    assert events[2].new_value is None
    assert len({e.change_set_id for e in events}) == 3

    supervisor_events = audit_events(session, service.SUPERVISOR_ENTITY_TYPE)
    assert [e.entity_key for e in supervisor_events] == [
        f"contact-supervisors/{supervisor_id}",
        f"contact-supervisors/{other_id}",
    ]
    assert supervisor_events[0].new_value is not None
    assert supervisor_events[0].new_value["display_name"] == "Zz Db Test Avery"


def test_supervisor_update_is_audited_with_old_and_new_values(
    session: Session, repository: NonCommittingRepository
) -> None:
    supervisor_id = add_supervisor(repository, "Zz Db Test Casey")
    current = repository.get_supervisor(supervisor_id)
    assert current is not None and current.has_contacts is False

    service.update_supervisor(
        repository,
        supervisor_id,
        SupervisorUpdate.model_validate(
            {
                "displayName": "Zz Db Test Casey",
                "active": False,
                "participationEligible": False,
                "effectiveFrom": "2003-01-01",
                "effectiveTo": "2003-06-30",
                "expectedUpdatedAt": current.updated_at.isoformat(),
            }
        ),
        actor_id="db-second",
        now=NOW + dt.timedelta(minutes=1),
    )

    [_, event] = audit_events(session, service.SUPERVISOR_ENTITY_TYPE)
    assert event.action == "update"
    assert event.old_value is not None and event.new_value is not None
    assert (event.old_value["active"], event.new_value["active"]) == (True, False)
    assert event.new_value["effective_to"] == "2003-06-30"
    assert event.new_value["participation_eligible"] is False


def test_request_id_replay_returns_the_first_contact(
    session: Session, repository: NonCommittingRepository
) -> None:
    supervisor_id = add_supervisor(repository, "Zz Db Test Drew")
    request_id = str(uuid.uuid4())
    data = ContactCreate.model_validate(
        {"contactDate": "2003-02-03", "supervisorId": supervisor_id, "requestId": request_id}
    )

    first, created = service.create_contact(repository, data, actor_id="db-tester", now=NOW)
    again, created_again = service.create_contact(repository, data, actor_id="db-tester", now=NOW)

    assert (created, created_again) == (True, False)
    assert again.id == first.id
    # The database itself refuses a second row for the same request.
    duplicate = repository.insert(
        first.values, request_id=uuid.UUID(request_id), actor_id="db-tester", at=NOW
    )
    assert duplicate is None
    assert len(audit_events(session, service.CONTACT_ENTITY_TYPE)) == 1


def test_counts_participation_and_alphabetical_dashboard(
    repository: NonCommittingRepository,
) -> None:
    a = add_supervisor(repository, "Zz Db Test avery")
    b = add_supervisor(repository, "Zz Db Test Blake", effectiveFrom="2003-03-15")
    c = add_supervisor(repository, "Zz Db Test Casey", participationEligible=False)
    for day, supervisor in [
        (dt.date(2003, 1, 31), a),
        (dt.date(2003, 1, 2), a),
        (dt.date(2003, 1, 9), c),
        (dt.date(2003, 3, 20), b),
    ]:
        add_contact(repository, supervisor, day)

    january = service.period(2003, 1)
    records, total = repository.search(january, limit=10, offset=0)
    assert total == 3
    assert [r.values.contact_date for r in records] == [
        dt.date(2003, 1, 31),
        dt.date(2003, 1, 9),
        dt.date(2003, 1, 2),
    ]

    dashboard = service.dashboard(repository, year=2003, today=NOW.date())
    ours = [s for s in dashboard.supervisors if s.display_name.startswith("Zz Db Test")]
    assert [s.display_name for s in ours] == [
        "Zz Db Test avery",
        "Zz Db Test Blake",
        "Zz Db Test Casey",
    ]
    assert [s.monthly[:3] for s in ours] == [[2, 0, 0], [0, 0, 1], [1, 0, 0]]
    jan, feb, mar = (dashboard.months[i].participation for i in range(3))
    assert jan is not None and feb is not None and mar is not None
    # Casey is not eligible; Blake joins in March.
    assert (jan.participating, jan.eligible) == (1, 1)
    assert (feb.participating, feb.eligible) == (0, 1)
    assert (mar.participating, mar.eligible) == (1, 2)
    assert 2003 in dashboard.years_with_data


def test_stale_contact_update_is_a_conflict(repository: NonCommittingRepository) -> None:
    supervisor_id = add_supervisor(repository, "Zz Db Test Emery")
    contact_id = add_contact(repository, supervisor_id, dt.date(2003, 4, 1))

    with pytest.raises(service.EditConflictError):
        service.update_contact(
            repository,
            contact_id,
            ContactUpdate.model_validate(
                {
                    "contactDate": "2003-04-02",
                    "supervisorId": supervisor_id,
                    "expectedUpdatedAt": "2003-01-01T00:00:00Z",
                }
            ),
            actor_id="db-tester",
            now=NOW,
        )


def test_supervisor_with_contacts_cannot_be_deleted(
    session: Session, repository: NonCommittingRepository
) -> None:
    supervisor_id = add_supervisor(repository, "Zz Db Test Finley")
    add_contact(repository, supervisor_id, dt.date(2003, 7, 1))

    with pytest.raises(service.SupervisorHasContactsError):
        service.delete_supervisor(repository, supervisor_id, actor_id="db-tester", now=NOW)
    with pytest.raises(IntegrityError, match="fk_supervisor_safety_contacts_supervisor"):
        session.execute(delete(ContactSupervisor).where(ContactSupervisor.id == supervisor_id))


def test_supervisor_without_contacts_can_be_deleted(
    session: Session, repository: NonCommittingRepository
) -> None:
    supervisor_id = add_supervisor(repository, "Zz Db Test Gray")
    service.delete_supervisor(repository, supervisor_id, actor_id="db-tester", now=NOW)
    assert repository.get_supervisor(supervisor_id) is None
    [_, deleted] = audit_events(session, service.SUPERVISOR_ENTITY_TYPE)
    assert (deleted.action, deleted.new_value) == ("delete", None)


# Database constraints ------------------------------------------------------------


def test_display_names_are_unique_ignoring_case(repository: NonCommittingRepository) -> None:
    add_supervisor(repository, "Zz Db Test Harper")
    with pytest.raises(DuplicateDisplayNameError):
        repository.insert_supervisor(
            SupervisorValues("ZZ DB TEST HARPER", True, True, START, None),
            actor_id="db-tester",
            at=NOW,
        )


def _supervisor_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "display_name": "Zz Db Test Row",
        "active": True,
        "participation_eligible": True,
        "effective_from": START,
        "effective_to": None,
        "created_by": "db-tester",
        "updated_by": "db-tester",
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"display_name": ""}, "ck_contact_supervisors_display_name"),
        ({"display_name": " Zz Padded"}, "ck_contact_supervisors_display_name"),
        ({"display_name": "x" * 101}, "ck_contact_supervisors_display_name"),
        ({"effective_from": dt.date(1999, 12, 31)}, "ck_contact_supervisors_effective_from"),
        ({"effective_to": dt.date(2002, 12, 31)}, "ck_contact_supervisors_effective_period"),
        ({"active": False}, "ck_contact_supervisors_inactive_has_end"),
    ],
)
def test_database_rejects_invalid_supervisors(
    session: Session, overrides: dict[str, object], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        session.execute(insert(ContactSupervisor).values(_supervisor_row(**overrides)))


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"contact_date": dt.date(1999, 12, 31)}, "ck_supervisor_safety_contacts_contact_date"),
        ({"supervisor_id": 2_000_000_000}, "fk_supervisor_safety_contacts_supervisor"),
    ],
)
def test_database_rejects_invalid_contacts(
    session: Session,
    repository: NonCommittingRepository,
    overrides: dict[str, object],
    constraint: str,
) -> None:
    supervisor_id = add_supervisor(repository, "Zz Db Test Indy")
    row: dict[str, object] = {
        "contact_date": dt.date(2003, 1, 1),
        "supervisor_id": supervisor_id,
        "created_by": "db-tester",
        "updated_by": "db-tester",
        **overrides,
    }
    with pytest.raises(IntegrityError, match=constraint):
        session.execute(insert(SupervisorSafetyContact).values(row))
