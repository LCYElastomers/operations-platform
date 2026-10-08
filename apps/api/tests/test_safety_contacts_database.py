"""Retired Supervisor Safety Contacts: the tables (migration 0005) and their
constraints are preserved, and stored rows stay readable.

Enabled by TEST_DATABASE_URL (see postgres_support.py). Each test runs in a
transaction that is rolled back. Rows use 2003 dates and test-only names.
"""

import datetime as dt
from collections.abc import Iterator

import pytest
from postgres_support import requires_postgres
from sqlalchemy import Engine, insert, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.safety.contacts.models import ContactSupervisor, SupervisorSafetyContact

pytestmark = requires_postgres

START = dt.date(2003, 1, 1)


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with engine.connect() as connection:
        transaction = connection.begin()
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        yield db
        db.close()
        transaction.rollback()


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


def _add_supervisor(session: Session, name: str) -> int:
    supervisor_id = session.scalar(
        insert(ContactSupervisor)
        .values(_supervisor_row(display_name=name))
        .returning(ContactSupervisor.id)
    )
    assert supervisor_id is not None
    return supervisor_id


def test_tables_constraints_and_indexes_are_preserved(engine: Engine) -> None:
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
    assert {i["name"] for i in inspector.get_indexes("supervisor_safety_contacts", "safety")} == {
        "ix_supervisor_safety_contacts_contact_date",
        "ix_supervisor_safety_contacts_supervisor_id",
        "uq_supervisor_safety_contacts_request_id",
    }
    columns = {c["name"] for c in inspector.get_columns("supervisor_safety_contacts", "safety")}
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


def test_stored_rows_remain_readable(session: Session) -> None:
    supervisor_id = _add_supervisor(session, "Zz Db Test Avery")
    session.execute(
        insert(SupervisorSafetyContact).values(
            contact_date=dt.date(2003, 5, 14),
            supervisor_id=supervisor_id,
            created_by="db-tester",
            updated_by="db-tester",
        )
    )

    rows = session.execute(
        select(SupervisorSafetyContact.contact_date, ContactSupervisor.display_name)
        .join(ContactSupervisor)
        .where(ContactSupervisor.id == supervisor_id)
    ).all()

    assert [tuple(r) for r in rows] == [(dt.date(2003, 5, 14), "Zz Db Test Avery")]


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"display_name": ""}, "ck_contact_supervisors_display_name"),
        ({"effective_to": dt.date(2002, 12, 31)}, "ck_contact_supervisors_effective_period"),
        ({"active": False}, "ck_contact_supervisors_inactive_has_end"),
    ],
)
def test_database_still_rejects_invalid_supervisors(
    session: Session, overrides: dict[str, object], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        session.execute(insert(ContactSupervisor).values(_supervisor_row(**overrides)))


def test_display_names_stay_unique_ignoring_case(session: Session) -> None:
    _add_supervisor(session, "Zz Db Test Harper")
    with pytest.raises(IntegrityError, match="uq_contact_supervisors_display_name"):
        _add_supervisor(session, "ZZ DB TEST HARPER")
