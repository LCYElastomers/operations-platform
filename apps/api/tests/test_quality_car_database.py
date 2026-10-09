"""PostgreSQL tests for Corrective Action Reports (migrations 0012 and 0013).

Enabled by TEST_DATABASE_URL (see postgres_support.py). Each test runs in a
transaction that is rolled back, including the fixture user it signs in as.
Fixture reports are requested in 2003, so stored reports are never read or
changed; the reviewed 2026 mapping is applied only when none of its CAR
numbers is stored.
"""

import datetime as dt
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from postgres_support import requires_postgres
from principals import TESTER, TESTER_ID, TESTER_NAME, as_user
from sqlalchemy import Engine, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.auth.models import User
from app.core.authorization import get_user_principal
from app.core.permissions import Permission as P
from app.main import create_app
from app.quality.car import legacy_import, service
from app.quality.car import router as car_router
from app.quality.car.models import Car, CarAction
from app.quality.car.repository import CarFilter, CarRepository
from app.quality.car.schemas import (
    ActionComplete,
    ActionCreate,
    ActionUpdate,
    ApprovalRecord,
    CarCreate,
    CarUpdate,
    QualityCostCreate,
    QualityCostLink,
)
from app.quality.cost.models import CostRecord
from app.quality.cost.records import Actor, RecordForbiddenError, RecordRuleError

pytestmark = requires_postgres

NOW = dt.datetime(2026, 10, 9, 17, 0, tzinfo=dt.UTC)
# A signed-in fixture user not subject to permission rules (the service tests).
ACTOR = Actor(TESTER, NOW, user_id=TESTER_ID, name=TESTER_NAME)
OTHER_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
OTHER_NAME = "Other User (fixture)"
YEAR_2003 = CarFilter(date_from=dt.date(2003, 1, 1), date_to=dt.date(2003, 12, 31))
MAPPING = (
    Path(__file__).resolve().parents[1] / "import_templates" / "quality_cars_2026.mapping.json"
)


class NonCommitting(CarRepository):
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


def _fixture_user(session: Session, user_id: uuid.UUID, name: str, **values: Any) -> None:
    session.execute(
        insert(User).values(
            id=user_id,
            email=f"{user_id.hex}@fixture.test",
            name=name,
            status="active",
            created_by="fixture",
            updated_by="fixture",
            **values,
        )
    )


@pytest.fixture
def repo(session: Session) -> NonCommitting:
    _fixture_user(session, TESTER_ID, TESTER_NAME)
    _fixture_user(session, OTHER_ID, OTHER_NAME)
    return NonCommitting(session)


@pytest.fixture
def area_id(session: Session) -> int:
    found = session.scalar(text("SELECT id FROM safety.areas WHERE active ORDER BY id LIMIT 1"))
    assert found is not None
    return found


def _create(repo: CarRepository, actor: Actor = ACTOR, **fields: Any) -> Any:
    request = CarCreate.model_validate(
        {"subject": "Fixture: label mismatch", "requestDate": "2003-03-04", **fields}
    )
    return service.create(repo, request, actor)


def _update(repo: CarRepository, row: Any, actor: Actor = ACTOR, **fields: Any) -> Any:
    c = row.car
    body = {
        "subject": c.subject,
        "requestDate": c.request_date.isoformat(),
        "status": c.status,
        "version": c.version,
        **fields,
    }
    return service.update(repo, c.id, CarUpdate.model_validate(body), actor)


def _events(session: Session, key_prefix: str) -> list[AuditEvent]:
    return list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_key.like(f"{key_prefix}%"))
            .order_by(AuditEvent.id)
        )
    )


# Create, draft and edit --------------------------------------------------------------


def test_a_draft_is_numbered_by_request_year_and_audited_as_the_user(
    repo: NonCommitting, session: Session
) -> None:
    first = _create(repo)
    second = _create(repo, subject="Fixture: second")
    assert first.car.car_number == "Q-2003-001"
    assert second.car.car_number == "Q-2003-002"
    assert first.car.status == "open"
    assert first.car.source == "manual"
    assert first.car.material_loss is None
    assert first.car.created_by == TESTER
    (event,) = _events(session, service.entity_key(first.car.id))
    assert event.action == "create"
    assert event.new_value["car_number"] == "Q-2003-001"
    assert event.actor_id == TESTER
    assert event.actor_user_id == TESTER_ID
    assert event.actor_name == TESTER_NAME


def test_numbering_continues_after_the_highest_number_of_the_year(
    repo: NonCommitting, session: Session
) -> None:
    session.execute(
        insert(Car).values(
            car_number="Q-2003-005",
            subject="Fixture: imported",
            request_date=dt.date(2003, 1, 1),
            status=None,
            source="legacy_import",
            created_by="t",
            updated_by="t",
        )
    )
    assert _create(repo).car.car_number == "Q-2003-006"


def test_editing_saves_sections_and_children_and_unchanged_writes_nothing(
    repo: NonCommitting, session: Session
) -> None:
    row = _create(repo)
    sections = {
        "sourceCode": "customer_complaint",
        "departmentCode": "quality",
        "nonconformityDescription": "Fixture description",
        "dispositionCodes": ["hold", "rework"],
        "safetyHazard": False,
        "materialLoss": "125.50",
        "productionTimeLoss": "0",
        "whySteps": [{"what": "Fixture what", "why": "Fixture why"}],
        "references": [{"type": "work_order", "key": "WO-1"}],
    }
    edited = _update(repo, row, **sections)
    c = edited.car
    assert c.version == 2
    assert c.disposition_codes == ["hold", "rework"]
    assert c.material_loss == Decimal("125.50")
    assert c.production_time_loss == Decimal(0)
    assert c.other_costs is None
    assert [s.what for s in edited.why_steps] == ["Fixture what"]
    assert [(r.type, r.key) for r in edited.references] == [("work_order", "WO-1")]

    out = service.car_out(edited, dt.date(2026, 10, 9), 14)
    assert out.total_cost == Decimal("125.50")

    same = _update(repo, edited, **{**sections, "materialLoss": "125.5"})
    assert same.car.version == 2
    assert len(_events(session, service.entity_key(row.car.id))) == 2


def test_people_are_users_and_names_come_from_the_user_record(repo: NonCommitting) -> None:
    row = _create(repo, assignedToUserId=str(OTHER_ID), requestedByUserId=str(TESTER_ID))
    assert (row.car.assigned_to, row.car.assigned_to_user_id) == (OTHER_NAME, OTHER_ID)
    assert (row.car.requested_by, row.car.requested_by_user_id) == (TESTER_NAME, TESTER_ID)

    # A browser-supplied name is ignored in favour of the user's own name.
    renamed = _update(repo, row, assignedToUserId=str(OTHER_ID), assignedTo="Someone Else")
    assert renamed.car.assigned_to == OTHER_NAME

    with pytest.raises(RecordRuleError) as raised:
        _update(repo, renamed, assignedTo="Free Text Person")
    assert raised.value.error == "invalid_person"
    with pytest.raises(RecordRuleError) as unknown:
        _update(repo, renamed, assignedToUserId=str(uuid.uuid4()))
    assert unknown.value.error == "invalid_person"


def test_an_inactive_user_cannot_be_newly_chosen_but_stays_on_history(
    repo: NonCommitting, session: Session
) -> None:
    row = _create(repo, assignedToUserId=str(OTHER_ID))
    session.execute(User.__table__.update().where(User.id == OTHER_ID).values(status="inactive"))
    # Unchanged, the inactive assignee stays.
    kept = _update(repo, row, assignedToUserId=str(OTHER_ID), subject="Fixture: renamed")
    assert (kept.car.assigned_to, kept.car.assigned_to_user_id) == (OTHER_NAME, OTHER_ID)
    other = _create(repo, subject="Fixture: second")
    with pytest.raises(RecordRuleError) as raised:
        _update(repo, other, assignedToUserId=str(OTHER_ID))
    assert raised.value.error == "invalid_person"


def test_a_legacy_name_is_kept_and_never_linked_by_guessing(
    repo: NonCommitting, session: Session
) -> None:
    car_id = session.scalar(
        insert(Car)
        .values(
            car_number="Q-2003-060",
            subject="Fixture: imported",
            request_date=dt.date(2003, 1, 1),
            status="open",
            source="legacy_import",
            # The same text as a user's name: still not linked.
            assigned_to=TESTER_NAME,
            reviewer="Fixture Reviewer",
            created_by="legacy-import",
            updated_by="legacy-import",
        )
        .returning(Car.id)
    )
    row = repo.get(car_id)
    edited = _update(repo, row, assignedTo=TESTER_NAME, subject="Fixture: imported (edited)")
    assert (edited.car.assigned_to, edited.car.assigned_to_user_id) == (TESTER_NAME, None)
    assert (edited.car.reviewer, edited.car.reviewer_user_id) == ("Fixture Reviewer", None)


def test_a_stale_version_is_refused(repo: NonCommitting) -> None:
    row = _create(repo)
    _update(repo, row, assignedToUserId=str(TESTER_ID))
    stale = CarUpdate.model_validate(
        {"subject": "Fixture", "requestDate": "2003-03-04", "status": "open", "version": 1}
    )
    with pytest.raises(service.CarConflictError):
        service.update(repo, row.car.id, stale, ACTOR)


# Approvals ---------------------------------------------------------------------------


def test_approvals_are_recorded_by_the_signed_in_user_and_withdrawn_by_them(
    repo: NonCommitting, session: Session
) -> None:
    row = _create(repo)
    approver = Actor(TESTER, NOW, frozenset({P.CAR_APPROVE}), TESTER_ID, TESTER_NAME)
    approved = service.record_approval(
        repo, row.car.id, ApprovalRecord(version=1, function_code="quality"), approver
    )
    (approval,) = approved.approvals
    assert (approval.function_code, approval.name, approval.user_id) == (
        "quality",
        TESTER_NAME,
        TESTER_ID,
    )
    assert approval.created_by == TESTER
    assert approved.car.version == 2

    with pytest.raises(RecordRuleError) as twice:
        service.record_approval(
            repo, row.car.id, ApprovalRecord(version=2, function_code="quality"), approver
        )
    assert twice.value.error == "already_approved"

    other = Actor(str(OTHER_ID), NOW, frozenset({P.CAR_APPROVE}), OTHER_ID, OTHER_NAME)
    with pytest.raises(RecordForbiddenError):
        service.withdraw_approval(repo, row.car.id, "quality", 2, other)
    admin = Actor(str(OTHER_ID), NOW, frozenset({P.CAR_ADMIN}), OTHER_ID, OTHER_NAME)
    withdrawn = service.withdraw_approval(repo, row.car.id, "quality", 2, admin)
    assert withdrawn.approvals == ()
    assert [e.action for e in _events(session, service.entity_key(row.car.id))] == [
        "create",
        "update",
        "update",
    ]


# Actions, closure, effectiveness -------------------------------------------------------


def test_multiple_actions_are_added_edited_and_completed(
    repo: NonCommitting, session: Session
) -> None:
    row = _create(repo)
    car_id = row.car.id
    for text_ in ("Fixture action one", "Fixture action two"):
        row = service.add_action(
            repo, car_id, ActionCreate(action=text_, owner_user_id=TESTER_ID), ACTOR
        )
    first, second = row.actions
    assert [a.position for a in row.actions] == [1, 2]
    assert first.status == "open"
    assert (first.owner, first.owner_user_id) == (TESTER_NAME, TESTER_ID)

    row = service.update_action(
        repo,
        car_id,
        second.id,
        ActionUpdate(
            action="Fixture action two (revised)",
            owner_user_id=TESTER_ID,
            status="in_progress",
            version=1,
        ),
        1,
        ACTOR,
    )
    assert row.actions[1].action == "Fixture action two (revised)"
    assert row.actions[1].version == 2

    row = service.complete_action(
        repo, car_id, first.id, ActionComplete(version=1, completed_on=dt.date(2003, 3, 10)), ACTOR
    )
    assert row.actions[0].status == "complete"
    assert row.actions[0].completed_on == dt.date(2003, 3, 10)
    # Recording actions never bumps the report's version.
    assert row.car.version == 1

    events = _events(session, f"{service.entity_key(car_id)}/actions/")
    assert [e.action for e in events] == ["create", "create", "update", "update"]
    assert {e.entity_type for e in events} == {service.ACTION_ENTITY_TYPE}
    assert {e.actor_user_id for e in events} == {TESTER_ID}
    history = repo.history(
        (service.ENTITY_TYPE, service.ACTION_ENTITY_TYPE), service.entity_key(car_id)
    )
    assert len(history) == 5


def test_only_the_owner_completes_an_action(repo: NonCommitting) -> None:
    row = _create(repo)
    row = service.add_action(
        repo, row.car.id, ActionCreate(action="Fixture", owner_user_id=OTHER_ID), ACTOR
    )
    (item,) = row.actions
    complete = ActionComplete(version=1, completed_on=dt.date(2003, 3, 10))
    worker = Actor(TESTER, NOW, frozenset({P.CAR_COMPLETE_ACTION}), TESTER_ID, TESTER_NAME)
    with pytest.raises(RecordForbiddenError):
        service.complete_action(repo, row.car.id, item.id, complete, worker)
    owner = Actor(str(OTHER_ID), NOW, frozenset({P.CAR_COMPLETE_ACTION}), OTHER_ID, OTHER_NAME)
    done = service.complete_action(repo, row.car.id, item.id, complete, owner)
    assert done.actions[0].status == "complete"
    assert done.actions[0].updated_by == str(OTHER_ID)


def test_closing_takes_the_approver_and_reviewer_from_the_session(
    repo: NonCommitting,
) -> None:
    row = _create(repo)
    car_id = row.car.id
    row = service.add_action(repo, car_id, ActionCreate(action="Fixture action"), ACTOR)
    closing = {"status": "closed", "dateClosed": "2003-04-01", "effectivenessResult": "effective"}
    with pytest.raises(RecordRuleError) as raised:
        _update(repo, row, **closing)
    assert raised.value.error == "actions_outstanding"

    row = service.complete_action(
        repo,
        car_id,
        row.actions[0].id,
        ActionComplete(version=1, completed_on=dt.date(2003, 3, 20)),
        ACTOR,
    )
    editor = Actor(TESTER, NOW, frozenset({P.CAR_EDIT}), TESTER_ID, TESTER_NAME)
    with pytest.raises(RecordForbiddenError):
        _update(repo, row, editor, **closing)

    closer = Actor(
        str(OTHER_ID),
        NOW,
        frozenset({P.CAR_EDIT, P.CAR_CLOSE, P.CAR_REVIEW_EFFECTIVENESS}),
        OTHER_ID,
        OTHER_NAME,
    )
    closed = _update(repo, row, closer, **closing)
    assert closed.car.status == "closed"
    assert closed.car.date_closed == dt.date(2003, 4, 1)
    assert (closed.car.closure_approved_by, closed.car.closure_approved_by_user_id) == (
        OTHER_NAME,
        OTHER_ID,
    )
    assert (closed.car.reviewer, closed.car.reviewer_user_id) == (OTHER_NAME, OTHER_ID)

    with pytest.raises(RecordRuleError) as refused:
        service.add_action(repo, car_id, ActionCreate(action="Late action"), ACTOR)
    assert refused.value.error == "car_closed"

    with pytest.raises(RecordForbiddenError):
        _update(repo, closed, closer, status="open")
    reopener = Actor(TESTER, NOW, frozenset({P.CAR_EDIT, P.CAR_REOPEN}), TESTER_ID, TESTER_NAME)
    reopened = _update(repo, closed, reopener, status="open", effectivenessResult="effective")
    assert reopened.car.closure_approved_by is None
    assert reopened.car.closure_approved_by_user_id is None
    # The review was not changed, so its reviewer stays.
    assert reopened.car.reviewer_user_id == OTHER_ID


def test_the_database_refuses_a_closed_report_without_a_date(session: Session) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(
            insert(Car).values(
                car_number="Q-2003-099",
                subject="Fixture",
                request_date=dt.date(2003, 1, 1),
                status="closed",
                created_by="t",
                updated_by="t",
            )
        )
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(
            insert(Car).values(
                car_number="Q-2003-098",
                subject="Fixture",
                request_date=dt.date(2003, 1, 1),
                status=None,
                source="manual",
                created_by="t",
                updated_by="t",
            )
        )


def test_an_action_completion_date_needs_the_complete_status(session: Session) -> None:
    car_id = session.scalar(
        insert(Car)
        .values(
            car_number="Q-2003-097",
            subject="Fixture",
            request_date=dt.date(2003, 1, 1),
            status="open",
            created_by="t",
            updated_by="t",
        )
        .returning(Car.id)
    )
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(
            insert(CarAction).values(
                car_id=car_id,
                position=1,
                action="Fixture",
                status="open",
                completed_on=dt.date(2003, 1, 2),
                created_by="t",
                updated_by="t",
            )
        )


def test_a_referenced_user_cannot_be_deleted(repo: NonCommitting, session: Session) -> None:
    _create(repo, assignedToUserId=str(OTHER_ID))
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(User.__table__.delete().where(User.id == OTHER_ID))


# Quality Cost link ----------------------------------------------------------------------


def test_a_quality_cost_record_is_created_from_the_cost_impact(
    repo: NonCommitting, session: Session, area_id: int
) -> None:
    row = _create(
        repo,
        materialLoss="200",
        productionTimeLoss="50.25",
        product="Fixture product",
        assignedToUserId=str(OTHER_ID),
    )
    created = service.create_quality_cost(
        repo,
        row.car.id,
        QualityCostCreate(
            version=1,
            area_id=area_id,
            coq_class="internal_failure",
            category_code="internal_failure.rework",
            financial_status="potential",
        ),
        ACTOR,
    )
    record_id = created.car.quality_cost_record_id
    assert record_id is not None
    record = session.get(CostRecord, record_id)
    assert record is not None
    assert record.material_cost == Decimal("200")
    assert record.production_cost == Decimal("50.25")
    assert record.other_cost is None
    assert record.product == "Fixture product"
    assert record.title.startswith("Q-2003-001 ")
    # The CAR's assignee (an active user) becomes the owner.
    assert (record.owner, record.owner_user_id) == (OTHER_NAME, OTHER_ID)
    assert created.quality_cost is not None
    assert created.car.version == 2
    refs = session.execute(
        text(
            "SELECT target_type, target_key FROM quality.cost_record_references "
            "WHERE record_id = :id"
        ),
        {"id": record_id},
    ).all()
    assert refs == [("car", "Q-2003-001")]

    with pytest.raises(RecordRuleError) as raised:
        service.create_quality_cost(
            repo,
            row.car.id,
            QualityCostCreate(
                version=2,
                area_id=area_id,
                coq_class="internal_failure",
                category_code="internal_failure.rework",
                financial_status="potential",
            ),
            ACTOR,
        )
    assert raised.value.error == "already_linked"


def test_an_existing_record_is_linked_once_and_can_be_unlinked(
    repo: NonCommitting, session: Session
) -> None:
    record_id = session.scalar(
        insert(CostRecord)
        .values(
            record_date=dt.date(2003, 2, 1),
            title="Fixture cost",
            coq_class="internal_failure",
            category_code="internal_failure.rework",
            description="Fixture",
            financial_status="potential",
            status="open",
            source="legacy_import",
            created_by="t",
            updated_by="t",
        )
        .returning(CostRecord.id)
    )
    one = _create(repo)
    two = _create(repo, subject="Fixture: second")
    linked = service.link_quality_cost(
        repo, one.car.id, QualityCostLink(version=1, record_id=record_id), ACTOR
    )
    assert linked.car.quality_cost_record_id == record_id
    assert repo.car_for_cost_record(record_id).id == one.car.id  # type: ignore[union-attr]

    with pytest.raises(RecordRuleError) as raised:
        service.link_quality_cost(
            repo, two.car.id, QualityCostLink(version=1, record_id=record_id), ACTOR
        )
    assert raised.value.error == "cost_record_linked"

    unlinked = service.link_quality_cost(
        repo, one.car.id, QualityCostLink(version=2, record_id=None), ACTOR
    )
    assert unlinked.car.quality_cost_record_id is None
    # The cost record itself is untouched.
    assert session.get(CostRecord, record_id) is not None


# Register filters ----------------------------------------------------------------------


def test_register_filters(repo: NonCommitting) -> None:
    a = _create(
        repo, departmentCode="quality", dueDate="2003-03-10", assignedToUserId=str(OTHER_ID)
    )
    b = _create(repo, subject="Fixture: repeat", previousOccurrence=True, sourceCode="other")
    _update(repo, b, previousOccurrence=True, sourceCode="other", rootCauseCode="method")

    def numbers(**criteria: Any) -> list[str]:
        filt = CarFilter(**{**YEAR_2003.__dict__, **criteria})
        rows, total = repo.search(filt)
        assert total == len(rows)
        return sorted(r.car.car_number for r in rows)

    assert numbers() == ["Q-2003-001", "Q-2003-002"]
    assert numbers(departments=("quality",)) == ["Q-2003-001"]
    assert numbers(departments=("not_recorded",)) == ["Q-2003-002"]
    assert numbers(past_due_on=dt.date(2026, 10, 9)) == ["Q-2003-001"]
    assert numbers(repeat=True) == ["Q-2003-002"]
    assert numbers(root_causes=("method",)) == ["Q-2003-002"]
    assert numbers(assigned_to=OTHER_NAME.lower()) == ["Q-2003-001"]
    assert numbers(search="repeat") == ["Q-2003-002"]
    assert numbers(search="Q-2003-001") == ["Q-2003-001"]
    assert numbers(statuses=("closed",)) == []
    assert numbers(effectiveness=("not_recorded",)) == ["Q-2003-001", "Q-2003-002"]
    assert a.car.id != b.car.id


# Import -----------------------------------------------------------------------------------


def test_the_reviewed_mapping_imports_once(repo: NonCommitting, session: Session) -> None:
    mapping = legacy_import.load_mapping(MAPPING)
    numbers = {e.car.car_number for e in mapping.cars}
    if repo.all_numbers() & numbers:
        pytest.skip("the historical CARs are already stored in this database")

    cars, actions, change_set = legacy_import.apply_plan(
        repo, mapping, actor_id="legacy-import", now=NOW
    )
    assert (cars, actions) == (5, 8)
    assert change_set is not None

    stored = repo.by_source_key()
    first = stored["car-workbook/Q-2026-001"]
    assert first.status is None
    assert first.source == "legacy_import"
    assert first.material_loss == Decimal(0)
    assert first.other_costs is None
    assert "Q-2026-001 CAR Form.xlsx" in (first.source_reference or "")
    assert "Q-2026-001 CAR Form.xlsx" in (first.migration_notes or "")
    assert {f["label"] for f in first.legacy_fields or []} >= {"Were there any equipment problems?"}
    # Imported people stay names; none is linked to a user.
    for car in stored.values():
        if car.car_number in numbers:
            assert car.assigned_to_user_id is None
            assert car.requested_by_user_id is None
    imported_events = _events(session, service.entity_key(first.id))
    assert {(e.actor_id, e.actor_user_id) for e in imported_events} == {("legacy-import", None)}
    blend = stored["car-workbook/Q-2026-006"]
    row = repo.get(blend.id)
    assert row is not None
    assert [a.status for a in row.actions] == ["complete"] * 4
    assert {a.owner_user_id for a in row.actions} == {None}
    assert len(row.why_steps) == 4

    replan = legacy_import.plan_import(mapping, *legacy_import._existing(repo))
    assert replan.empty and not replan.blocked
    # New reports continue after the highest imported number.
    request = CarCreate.model_validate({"subject": "Fixture", "requestDate": "2026-10-01"})
    assert service.create(repo, request, ACTOR).car.car_number == "Q-2026-007"

    # An imported report stays editable without inventing its missing status.
    edited = _update(
        repo,
        repo.get(first.id),
        status=None,
        departmentCode=None,
        dispositionCodes=["not_applicable"],
        materialLoss="0",
        productionTimeLoss="0",
        customerImpact=False,
        requestedBy=first.requested_by,
        assignedTo=first.assigned_to,
        containmentOwner=first.containment_owner,
    )
    assert edited.car.status is None
    assert edited.car.customer_impact is False
    assert edited.car.requested_by == first.requested_by


# Endpoints --------------------------------------------------------------------------------


@pytest.fixture
def api(repo: NonCommitting) -> Iterator[Any]:
    def make(
        *permissions: P, user_id: uuid.UUID = TESTER_ID, name: str = TESTER_NAME
    ) -> TestClient:
        app = create_app()
        app.dependency_overrides[car_router.car_repository] = lambda: repo
        app.dependency_overrides[get_user_principal] = lambda: as_user(
            *permissions, user_id=user_id, name=name
        )
        return TestClient(app)

    yield make


@pytest.mark.parametrize("path", ["", "/options"])
def test_reading_requires_car_view(api: Any, path: str) -> None:
    url = f"/api/v1/quality/cars{path}"
    assert api(P.CAR_VIEW).get(url).status_code == 200
    assert api(P.QUALITY_VIEW).get(url).status_code == 403
    assert api(P.QUALITY_COST_EDIT).get(url).status_code == 403
    assert api().get(url).status_code == 403


def test_the_dashboard_needs_the_dashboard_permission(api: Any) -> None:
    url = "/api/v1/quality/cars/dashboard"
    assert api(P.CAR_VIEW).get(url).status_code == 403
    assert api(P.CAR_VIEW, P.QUALITY_DASHBOARD_VIEW).get(url).status_code == 200


def test_entry_through_the_api(api: Any) -> None:
    viewer = api(P.CAR_VIEW)
    editor = api(P.CAR_VIEW, P.CAR_CREATE, P.CAR_EDIT, P.CAR_MANAGE_ACTIONS, P.CAR_COMPLETE_ACTION)
    body = {"subject": "Fixture: API", "requestDate": "2003-05-01", "dueDate": "2003-06-01"}
    assert viewer.post("/api/v1/quality/cars", json=body).status_code == 403

    created = editor.post("/api/v1/quality/cars", json=body)
    assert created.status_code == 201, created.text
    car = created.json()["car"]
    assert car["carNumber"] == "Q-2003-001"
    assert car["pastDue"] is True
    assert car["totalCost"] is None
    assert car["createdBy"] == TESTER
    assert car["createdByName"] == TESTER_NAME
    assert created.json()["canEditCost"] is False
    assert created.json()["abilities"]["close"] is False

    url = f"/api/v1/quality/cars/{car['id']}"
    added = editor.post(f"{url}/actions", json={"action": "Fixture action", "ownerUserId": TESTER})
    assert added.status_code == 201, added.text
    (item,) = added.json()["car"]["actionItems"]
    assert item["owner"] == TESTER_NAME
    done = editor.post(
        f"{url}/actions/{item['id']}/complete",
        json={"version": item["version"], "completedOn": "2003-05-10"},
    )
    assert done.status_code == 200, done.text
    assert done.json()["car"]["actions"] == {
        "total": 1,
        "complete": 1,
        "outstanding": 0,
        "overdue": 0,
    }
    assert done.json()["car"]["awaitingEffectiveness"] is True

    refused = editor.put(url, json={**body, "status": "closed", "version": 1})
    assert refused.status_code == 422
    assert refused.json()["detail"]["error"] == "date_closed_required"

    closing = {
        **body,
        "status": "closed",
        "dateClosed": "2003-05-20",
        "effectivenessResult": "effective",
        "version": 1,
    }
    forbidden = editor.put(url, json=closing)
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["error"] == "permission_denied"

    stale = editor.put(url, json={**body, "version": 9})
    assert stale.status_code == 409
    assert stale.json()["detail"]["current"]["carNumber"] == "Q-2003-001"

    listed = viewer.get("/api/v1/quality/cars", params={"from": "2003-01-01", "to": "2003-12-31"})
    assert [c["carNumber"] for c in listed.json()["cars"]] == ["Q-2003-001"]
    history = viewer.get(f"{url}/history").json()
    assert [(e["entity"], e["action"]) for e in history["events"]] == [
        ("car", "create"),
        ("action", "create"),
        ("action", "update"),
    ]
    assert viewer.get("/api/v1/quality/cars/999999999").status_code == 404


def test_a_browser_cannot_choose_who_approved_or_closed(api: Any) -> None:
    editor = api(P.CAR_VIEW, P.CAR_CREATE, P.CAR_EDIT)
    car = editor.post(
        "/api/v1/quality/cars", json={"subject": "Fixture", "requestDate": "2003-05-01"}
    ).json()["car"]
    url = f"/api/v1/quality/cars/{car['id']}"
    for field, value in (
        ("closureApprovedBy", "Someone"),
        ("closureApprovedByUserId", TESTER),
        ("reviewer", "Someone"),
        ("approvals", [{"functionCode": "quality", "name": "Someone"}]),
        ("createdBy", TESTER),
        ("updatedBy", TESTER),
    ):
        sent = editor.put(
            url,
            json={"subject": "Fixture", "requestDate": "2003-05-01", "version": 1, field: value},
        )
        assert sent.status_code == 422, field

    approver = api(P.CAR_VIEW, P.CAR_APPROVE, user_id=OTHER_ID, name=OTHER_NAME)
    assert (
        editor.post(f"{url}/approvals", json={"version": 1, "functionCode": "quality"}).status_code
        == 403
    )
    impersonating = approver.post(
        f"{url}/approvals", json={"version": 1, "functionCode": "quality", "name": "Someone"}
    )
    assert impersonating.status_code == 422
    approved = approver.post(f"{url}/approvals", json={"version": 1, "functionCode": "quality"})
    assert approved.status_code == 200, approved.text
    (approval,) = approved.json()["car"]["approvals"]
    assert approval["name"] == OTHER_NAME
    assert approval["userId"] == str(OTHER_ID)
    assert approval["recordedByName"] == OTHER_NAME

    someone_else = api(P.CAR_VIEW, P.CAR_APPROVE)
    assert someone_else.delete(f"{url}/approvals/quality", params={"version": 2}).status_code == 403
    withdrawn = approver.delete(f"{url}/approvals/quality", params={"version": 2})
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["car"]["approvals"] == []


def test_creating_a_cost_record_needs_quality_cost_create(api: Any, area_id: int) -> None:
    editor = api(P.CAR_VIEW, P.CAR_CREATE, P.CAR_EDIT)
    car = editor.post(
        "/api/v1/quality/cars", json={"subject": "Fixture", "requestDate": "2003-05-01"}
    ).json()["car"]
    body = {
        "version": 1,
        "areaId": area_id,
        "coqClass": "internal_failure",
        "categoryCode": "internal_failure.rework",
        "financialStatus": "potential",
    }
    url = f"/api/v1/quality/cars/{car['id']}/quality-cost"
    assert editor.post(url, json=body).status_code == 403
    both = api(P.CAR_VIEW, P.CAR_EDIT, P.QUALITY_COST_CREATE)
    created = both.post(url, json=body)
    assert created.status_code == 200, created.text
    linked = created.json()["car"]["qualityCost"]
    assert linked["recordNumber"].startswith("QC-")
    found = api(P.CAR_VIEW).get(
        "/api/v1/quality/cars/linked", params={"costRecordId": linked["id"]}
    )
    assert [c["carNumber"] for c in found.json()] == [car["carNumber"]]


def test_responses_carry_no_source_file_location(api: Any, repo: NonCommitting) -> None:
    session = repo.session
    car_id = session.scalar(
        insert(Car)
        .values(
            car_number="Q-2003-050",
            subject="Fixture: imported",
            request_date=dt.date(2003, 1, 1),
            status=None,
            source="legacy_import",
            source_key="car-workbook/Q-2003-050",
            source_reference="fixture.xlsx (sha256 0): CAR!B2,CAR!D2",
            created_by="t",
            updated_by="t",
        )
        .returning(Car.id)
    )
    viewer = api(P.CAR_VIEW)
    for url in (
        f"/api/v1/quality/cars/{car_id}",
        "/api/v1/quality/cars?from=2003-01-01",
        f"/api/v1/quality/cars/{car_id}/history",
    ):
        body = viewer.get(url).text
        assert "CAR!" not in body
        assert "sourceReference" not in body
        assert "passwordHash" not in body
    detail = viewer.get(f"/api/v1/quality/cars/{car_id}").json()["car"]
    assert detail["status"] is None
    assert detail["statusLabel"] == "Not recorded"
