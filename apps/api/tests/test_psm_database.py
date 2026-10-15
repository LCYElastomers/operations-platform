"""PostgreSQL tests for Process Safety Management (migration 0015).

Enabled by TEST_DATABASE_URL (see postgres_support.py). Each test runs in a
transaction that is rolled back. Fixture studies are labelled "Fixture" and
dated 2003; the reviewed 2026 mapping is applied only when it is not stored.
"""

import datetime as dt
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from postgres_support import requires_postgres
from principals import TESTER, TESTER_ID, TESTER_NAME, as_user
from sqlalchemy import Engine, func, insert, select
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.auth.models import User
from app.core import mail
from app.core.authorization import get_user_principal
from app.core.config import Settings
from app.core.permissions import Permission as P
from app.main import create_app
from app.quality.cost.records import Actor, RecordForbiddenError, RecordRuleError
from app.safety.psm import metrics, notifications, pha_import, service
from app.safety.psm import router as psm_router
from app.safety.psm.models import (
    PsmAction,
    PsmActionUpdate,
    PsmDepartment,
    PsmNotification,
    PsmRecommendation,
    PsmScenario,
    PsmStudy,
    PsmStudyType,
)
from app.safety.psm.schemas import (
    AcceptRequest,
    ActionUpdate,
    ClosureRequest,
    ReasonRequest,
    RecommendationCreate,
    RecommendationUpdate,
    RejectRequest,
    ResolutionRequest,
    ScenarioOrder,
    ScenarioUpdate,
    StatusChange,
    StudyWrite,
    VerificationApprove,
)
from app.safety.psm.store import PsmStore

pytestmark = requires_postgres

NOW = dt.datetime(2026, 10, 9, 17, 0, tzinfo=dt.UTC)
# A signed-in fixture user not subject to permission rules (the service tests).
ACTOR = Actor(TESTER, NOW, user_id=TESTER_ID, name=TESTER_NAME)
MAPPING = (
    Path(__file__).resolve().parents[1]
    / "import_templates"
    / "psm_pha_2026_300_400_600.mapping.json"
)
JUSTIFICATION = "Fixture: the existing interlock already covers this scenario."
REASON = "Fixture reason for the change."


class NonCommitting(PsmStore):
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
def store(session: Session) -> NonCommitting:
    session.execute(
        insert(User).values(
            id=TESTER_ID,
            email=f"{TESTER_ID.hex}@fixture.test",
            name=TESTER_NAME,
            status="active",
            created_by="fixture",
            updated_by="fixture",
        )
    )
    return NonCommitting(session)


def _study(store: PsmStore, code: str = "FIXTURE-PSM-2003") -> int:
    type_id = store.session.scalar(select(PsmStudyType.id).where(PsmStudyType.code == "pha"))
    request = StudyWrite.model_validate(
        {
            "studyCode": code,
            "title": f"Fixture: PHA study {code}",
            "year": 2003,
            "studyTypeId": type_id,
            "recommendationPrefix": code.upper(),
        }
    )
    return service.create_study(store, request, ACTOR)


def _scenario(risk: str = "low", event: str = "Fixture event") -> dict[str, str]:
    return {
        "event": event,
        "cause": "Fixture cause",
        "consequence": "Fixture consequence",
        "risk": risk,
    }


def _recommendation(store: PsmStore, study_id: int, *risks: str) -> int:
    request = RecommendationCreate.model_validate(
        {
            "studyId": study_id,
            "areaEquipment": "Fixture V-1",
            "recommendationText": "Fixture: install a high-level alarm.",
            "scenarios": [
                _scenario(r, f"Fixture event {i}") for i, r in enumerate(risks or ("low",))
            ],
        }
    )
    return service.create_recommendation(store, request, ACTOR)


def _rec(store: PsmStore, rec_id: int) -> PsmRecommendation:
    row = store.get(PsmRecommendation, rec_id)
    store.session.refresh(row)
    return row


def _accept(store: PsmStore, rec_id: int, actor: Actor = ACTOR, **fields: Any) -> PsmAction:
    rec = _rec(store, rec_id)
    service.accept(
        store,
        rec_id,
        AcceptRequest.model_validate({"version": rec.version, "confirm": True, **fields}),
        actor,
    )
    action = store.action_of(rec_id)
    assert action is not None
    store.session.refresh(action)
    return action


def _reject(store: PsmStore, rec_id: int) -> None:
    rec = _rec(store, rec_id)
    service.reject(
        store,
        rec_id,
        RejectRequest.model_validate({"version": rec.version, "justification": JUSTIFICATION}),
        ACTOR,
    )


def _action(store: PsmStore, action_id: int) -> PsmAction:
    row = store.get(PsmAction, action_id)
    store.session.refresh(row)
    return row


def _events(session: Session, key_prefix: str) -> list[str]:
    rows = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity_key.like(f"{key_prefix}%"))
        .order_by(AuditEvent.id)
    )
    return [(row.new_value or {}).get("event") for row in rows]


def _actions_of(session: Session, rec_id: int) -> int:
    return session.scalar(select(func.count()).where(PsmAction.recommendation_id == rec_id)) or 0


def _evidence(store: PsmStore, action_id: int) -> None:
    service.add_attachment(
        store,
        service.Upload("fixture-evidence.pdf", "work_order", "Fixture", b"%PDF-1.4 fixture"),
        ACTOR,
        action_id=action_id,
    )


# Import ---------------------------------------------------------------------------------


@pytest.fixture
def mapping(session: Session) -> pha_import.PhaMapping:
    found = pha_import.PhaMapping.model_validate_json(MAPPING.read_text(encoding="utf-8"))
    stored = session.scalar(
        select(PsmStudy.id).where(PsmStudy.source_key == found.study_source_key)
    )
    if stored is not None:
        pytest.skip("the 2026 PHA study is already stored in this database")
    return found


def test_import_creates_the_reviewed_recommendations_and_scenarios(
    store: NonCommitting, session: Session, mapping: pha_import.PhaMapping
) -> None:
    result = pha_import.apply(store, mapping, ACTOR)
    assert result.recommendations == 20
    assert result.scenarios == 30
    recs = list(
        session.scalars(
            select(PsmRecommendation)
            .where(PsmRecommendation.study_id == result.study_id)
            .order_by(PsmRecommendation.recommendation_number)
        )
    )
    assert [r.display_id for r in recs] == [f"PHA-2026-{n:03d}" for n in range(1, 21)]
    counts = {r.recommendation_number: len(store.scenarios_of(r.id)) for r in recs}
    assert counts[2] == 2 and counts[6] == 2 and counts[10] == 4
    assert counts[16] == counts[17] == counts[18] == 2
    risks = [s.risk for r in recs for s in store.scenarios_of(r.id)]
    assert (risks.count("low"), risks.count("medium"), risks.count("high")) == (12, 18, 0)
    # Order follows the worksheet rows.
    for r in recs:
        rows = [s.source_row for s in store.scenarios_of(r.id)]
        assert rows == sorted(rows)
    assert {r.disposition for r in recs} == {"pending_review"}
    assert all(r.disposition_justification is None for r in recs)
    assert (
        session.scalar(
            select(func.count())
            .select_from(PsmAction)
            .join(PsmRecommendation)
            .where(PsmRecommendation.study_id == result.study_id)
        )
        == 0
    )
    labels = {r.area_equipment for r in recs}
    assert not labels & {"Total", "Rejected", "Accepted", "Open", "Closed", "In-Progress"}
    assert _events(session, f"psm/recommendations/{recs[0].id}")[0] == "imported"


def test_import_is_idempotent_and_keeps_stored_values(
    store: NonCommitting, session: Session, mapping: pha_import.PhaMapping
) -> None:
    first = pha_import.apply(store, mapping, ACTOR)
    rec = session.scalar(
        select(PsmRecommendation).where(
            PsmRecommendation.study_id == first.study_id,
            PsmRecommendation.recommendation_number == 1,
        )
    )
    assert rec is not None
    service.update_recommendation(
        store,
        rec.id,
        RecommendationUpdate.model_validate(
            {
                "version": rec.version,
                "areaEquipment": rec.area_equipment,
                "recommendationText": "Fixture: edited after import.",
                "isDraft": False,
            }
        ),
        ACTOR,
    )
    _accept(store, rec.id)
    again = pha_import.apply(store, mapping, ACTOR)
    assert again.study_id == first.study_id
    assert (again.recommendations, again.scenarios, again.nodes) == (0, 0, 0)
    assert any("recommendation text differs" in d for d in again.plan.differences)
    session.refresh(rec)
    assert rec.recommendation_text == "Fixture: edited after import."
    assert rec.disposition == "accepted"
    total = session.scalar(select(func.count()).where(PsmRecommendation.study_id == first.study_id))
    assert total == 20


# Disposition ----------------------------------------------------------------------------


def test_accepting_creates_exactly_one_action_with_the_recommendation_links(
    store: NonCommitting, session: Session
) -> None:
    rec_id = _recommendation(store, _study(store), "low", "medium")
    action = _accept(store, rec_id)
    assert action.recommendation_id == rec_id
    assert action.action_number.startswith("PSM-ACT-2026-")
    assert action.status == "not_started"
    assert action.title.endswith(_rec(store, rec_id).display_id)
    with pytest.raises(RecordRuleError) as raised:
        _accept(store, rec_id)
    assert raised.value.error == "already_accepted"
    assert _actions_of(session, rec_id) == 1
    events = _events(session, f"psm/recommendations/{rec_id}")
    assert "disposition_changed" in events and "action_generated" in events


def test_rejecting_needs_a_justification_and_creates_no_action(
    store: NonCommitting, session: Session
) -> None:
    rec_id = _recommendation(store, _study(store))
    _reject(store, rec_id)
    rec = _rec(store, rec_id)
    assert rec.disposition == "rejected"
    assert rec.disposition_justification == JUSTIFICATION
    assert _actions_of(session, rec_id) == 0
    assert "rejection_justification_added" in _events(session, f"psm/recommendations/{rec_id}")


def test_a_rejected_recommendation_accepted_later_gets_its_action(
    store: NonCommitting, session: Session
) -> None:
    rec_id = _recommendation(store, _study(store))
    _reject(store, rec_id)
    action = _accept(store, rec_id)
    assert action.status == "not_started"
    assert _rec(store, rec_id).disposition == "accepted"
    assert _actions_of(session, rec_id) == 1


def test_rejection_after_acceptance_keeps_the_action_for_resolution(
    store: NonCommitting, session: Session
) -> None:
    rec_id = _recommendation(store, _study(store))
    action = _accept(store, rec_id)
    _reject(store, rec_id)
    assert _action(store, action.id).requires_resolution
    reinstated = _accept(store, rec_id)
    assert reinstated.id == action.id
    assert not reinstated.requires_resolution
    assert _actions_of(session, rec_id) == 1


def test_resolution_can_archive_the_kept_action(store: NonCommitting) -> None:
    rec_id = _recommendation(store, _study(store))
    action = _accept(store, rec_id)
    _reject(store, rec_id)
    current = _action(store, action.id)
    service.resolve(
        store,
        action.id,
        ResolutionRequest.model_validate(
            {"version": current.version, "resolution": "archive", "reason": REASON}
        ),
        ACTOR,
    )
    archived = _action(store, action.id)
    assert archived.archived_at is not None and not archived.requires_resolution


def test_disposition_and_action_status_are_separate(store: NonCommitting) -> None:
    rec_id = _recommendation(store, _study(store))
    action = _accept(store, rec_id)
    service.change_status(
        store,
        action.id,
        StatusChange.model_validate({"version": action.version, "status": "in_progress"}),
        ACTOR,
    )
    assert _action(store, action.id).status == "in_progress"
    assert _rec(store, rec_id).disposition == "accepted"


def test_accepting_with_an_external_owner_records_the_assignment(
    store: NonCommitting, session: Session
) -> None:
    department = session.scalar(select(PsmDepartment.id).order_by(PsmDepartment.id).limit(1))
    rec_id = _recommendation(store, _study(store))
    action = _accept(
        store,
        rec_id,
        departmentId=department,
        ownerName="Fixture Contractor",
        ownerEmail="contractor@fixture.test",
        dueDate="2099-01-31",
        task="Fixture: install and test the alarm.",
    )
    assert action.owner_user_id is None
    assert action.owner_name == "Fixture Contractor"
    assert action.owner_email == "contractor@fixture.test"
    assert action.department_id == department
    assert action.due_date == dt.date(2099, 1, 31)
    assert action.description == "Fixture: install and test the alarm."


# Scenarios ------------------------------------------------------------------------------


def test_scenarios_keep_order_and_governing_risk_is_the_highest(
    store: NonCommitting,
) -> None:
    study_id = _study(store)
    rec_id = _recommendation(store, study_id, "low", "medium", "low")
    scenarios = store.scenarios_of(rec_id)
    assert [s.sequence_number for s in scenarios] == [1, 2, 3]
    assert [s.event for s in scenarios] == [f"Fixture event {i}" for i in range(3)]
    (view,) = service.views(store.scope(study_id=study_id))
    assert metrics.governing_risk(view.scenario_risks) == "medium"

    first, second, third = scenarios
    service.update_scenario(
        store,
        rec_id,
        first.id,
        ScenarioUpdate.model_validate({**_scenario("high", "Fixture edited"), "version": 1}),
        ACTOR,
    )
    store.session.refresh(second)
    assert second.event == "Fixture event 1" and second.risk == "medium"
    (view,) = service.views(store.scope(study_id=study_id))
    assert metrics.governing_risk(view.scenario_risks) == "high"

    rec = _rec(store, rec_id)
    service.reorder_scenarios(
        store,
        rec_id,
        ScenarioOrder.model_validate(
            {"version": rec.version, "scenarioIds": [third.id, first.id, second.id]}
        ),
        ACTOR,
    )
    assert [s.id for s in store.scenarios_of(rec_id)] == [third.id, first.id, second.id]


def test_archiving_keeps_scenarios_and_is_refused_with_an_open_action(
    store: NonCommitting, session: Session
) -> None:
    study_id = _study(store)
    rec_id = _recommendation(store, study_id, "low", "medium")
    rec = _rec(store, rec_id)
    service.archive_recommendation(
        store,
        rec_id,
        ReasonRequest.model_validate({"version": rec.version, "reason": REASON}),
        ACTOR,
    )
    assert _rec(store, rec_id).archived_at is not None
    assert len(store.scenarios_of(rec_id)) == 2
    orphans = session.scalar(
        select(func.count())
        .select_from(PsmScenario)
        .outerjoin(PsmRecommendation, PsmRecommendation.id == PsmScenario.recommendation_id)
        .where(PsmRecommendation.id.is_(None))
    )
    assert orphans == 0
    assert service.views(store.scope(study_id=study_id)) == []

    other = _recommendation(store, study_id)
    _accept(store, other)
    with pytest.raises(RecordRuleError) as raised:
        service.archive_recommendation(
            store,
            other,
            ReasonRequest.model_validate({"version": _rec(store, other).version, "reason": REASON}),
            ACTOR,
        )
    assert raised.value.error == "open_action"


# Closure --------------------------------------------------------------------------------


def _start(store: PsmStore, action: PsmAction) -> PsmAction:
    service.change_status(
        store,
        action.id,
        StatusChange.model_validate({"version": action.version, "status": "in_progress"}),
        ACTOR,
    )
    return _action(store, action.id)


def _request_closure(
    store: PsmStore, action: PsmAction, actor: Actor = ACTOR, **fields: Any
) -> None:
    service.request_closure(
        store,
        action.id,
        ClosureRequest.model_validate(
            {"version": action.version, "summary": "Fixture: alarm installed and tested.", **fields}
        ),
        actor,
    )


def test_closure_needs_evidence_or_an_authorized_exception(store: NonCommitting) -> None:
    action = _start(store, _accept(store, _recommendation(store, _study(store))))
    with pytest.raises(RecordRuleError) as raised:
        _request_closure(store, action)
    assert raised.value.error == "evidence_required"

    requester = Actor(
        TESTER, NOW, frozenset({P.PSM_REQUEST_CLOSURE}), user_id=TESTER_ID, name=TESTER_NAME
    )
    with pytest.raises(RecordForbiddenError):
        _request_closure(store, action, requester, exceptionReason=REASON)

    admin = Actor(TESTER, NOW, frozenset({P.PSM_ADMIN}), user_id=TESTER_ID, name=TESTER_NAME)
    _request_closure(store, action, admin, exceptionReason=REASON)
    done = _action(store, action.id)
    assert done.status == "pending_verification"
    assert done.closure_exception_reason == REASON


def test_closure_lifecycle_is_verified_and_audited(store: NonCommitting, session: Session) -> None:
    rec_id = _recommendation(store, _study(store))
    action = _start(store, _accept(store, rec_id))
    _evidence(store, action.id)
    _request_closure(store, action)
    action = _action(store, action.id)
    assert action.status == "pending_verification"
    assert action.closure_summary == "Fixture: alarm installed and tested."

    service.return_closure(
        store,
        action.id,
        ReasonRequest.model_validate({"version": action.version, "reason": REASON}),
        ACTOR,
    )
    action = _action(store, action.id)
    assert action.status == "in_progress"
    assert action.return_reason == REASON

    _request_closure(store, action)
    action = _action(store, action.id)
    service.approve_closure(
        store, action.id, VerificationApprove.model_validate({"version": action.version}), ACTOR
    )
    action = _action(store, action.id)
    assert action.status == "closed"
    assert action.verified_by_name == TESTER_NAME
    assert action.closed_at is not None

    service.reopen(
        store,
        action.id,
        ReasonRequest.model_validate({"version": action.version, "reason": REASON}),
        ACTOR,
    )
    action = _action(store, action.id)
    assert action.status == "in_progress"
    assert action.reopen_reason == REASON

    events = _events(session, f"psm/recommendations/{rec_id}/actions/{action.id}")
    for event in (
        "action_generated",
        "status_changed",
        "evidence_added",
        "closure_requested",
        "returned",
        "closure_verified",
        "closed",
        "reopened",
    ):
        assert event in events, event
    updates = session.scalars(select(PsmActionUpdate).where(PsmActionUpdate.action_id == action.id))
    assert {"closure_request", "closure_returned"} <= {u.update_type for u in updates}


def test_reasons_are_required_to_return_and_reopen() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReasonRequest.model_validate({"version": 1, "reason": "short"})


def test_editing_never_closes_and_skipping_in_progress_needs_a_reason(
    store: NonCommitting,
) -> None:
    action = _accept(store, _recommendation(store, _study(store)), dueDate="2099-01-31")
    service.update_action(
        store,
        action.id,
        ActionUpdate.model_validate(
            {"version": action.version, "title": "Fixture: renamed", "dueDate": "2099-02-28"}
        ),
        ACTOR,
    )
    action = _action(store, action.id)
    assert action.status == "not_started"
    _evidence(store, action.id)
    with pytest.raises(RecordRuleError) as raised:
        _request_closure(store, action)
    assert raised.value.error == "reason_required"
    _request_closure(store, action, skipReason="Fixture: done during the outage.")
    assert _action(store, action.id).status == "pending_verification"


def test_moving_the_due_date_after_work_began_needs_a_reason(store: NonCommitting) -> None:
    action = _start(
        store, _accept(store, _recommendation(store, _study(store)), dueDate="2099-01-31")
    )
    body = {"version": action.version, "title": action.title, "dueDate": "2099-03-31"}
    with pytest.raises(RecordRuleError) as raised:
        service.update_action(store, action.id, ActionUpdate.model_validate(body), ACTOR)
    assert raised.value.field == "dueDateReason"
    service.update_action(
        store, action.id, ActionUpdate.model_validate({**body, "dueDateReason": REASON}), ACTOR
    )
    assert _action(store, action.id).due_date == dt.date(2099, 3, 31)


def test_evidence_is_locked_while_pending_verification(store: NonCommitting) -> None:
    action = _start(store, _accept(store, _recommendation(store, _study(store))))
    _evidence(store, action.id)
    (attachment,) = store.attachments(action_id=action.id)
    _request_closure(store, action)
    with pytest.raises(RecordRuleError) as raised:
        service.remove_attachment(store, attachment.id, REASON, ACTOR)
    assert raised.value.error == "locked_evidence"


# Figures from the database -------------------------------------------------------------


def test_figures_come_from_stored_records(store: NonCommitting) -> None:
    study_id = _study(store)
    assert (
        metrics.kpis(service.views(store.scope(study_id=study_id)), NOW.date()).closure_pct is None
    )

    pending = _recommendation(store, study_id, "low", "medium", "medium")
    late = _recommendation(store, study_id, "low")
    closed = _recommendation(store, study_id, "medium")
    rejected = _recommendation(store, study_id, "high")
    unscheduled = _recommendation(store, study_id, "low")
    _accept(store, late, ownerName="Fixture Owner", dueDate="2003-01-31")
    closing = _start(store, _accept(store, closed, dueDate="2003-01-31"))
    _evidence(store, closing.id)
    _request_closure(store, closing)
    closing = _action(store, closing.id)
    service.approve_closure(
        store, closing.id, VerificationApprove.model_validate({"version": closing.version}), ACTOR
    )
    _reject(store, rejected)
    _accept(store, unscheduled)
    assert pending

    recs = service.views(store.scope(study_id=study_id))
    today = dt.date(2026, 10, 12)
    k = metrics.kpis(recs, today)
    assert (k.total, k.pending, k.accepted, k.rejected) == (5, 1, 3, 1)
    assert k.closed == 1 and k.actions == 3
    assert k.overdue == 1  # the closed action is past its due date but not overdue
    assert k.needs_scheduling == 1  # no due date is not overdue
    assert k.closure_pct == 33.3
    # Scenario counts are not recommendation counts.
    assert metrics.scenario_risks(recs) == {"high": 1, "medium": 3, "low": 3}
    assert metrics.governing_risks(recs) == {"high": 1, "medium": 2, "low": 2}


# Email ------------------------------------------------------------------------------------


def _mail_settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        smtp_host="mail.fixture.test",
        smtp_from="psm@fixture.test",
    )


@pytest.fixture
def same_session(session: Session, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(session, "commit", session.flush)

    @contextmanager
    def sessions() -> Iterator[Session]:
        yield session

    return sessions


def _notifications(session: Session, action_id: int) -> list[PsmNotification]:
    return list(
        session.scalars(
            select(PsmNotification)
            .where(PsmNotification.action_id == action_id)
            .order_by(PsmNotification.id)
        )
    )


def test_assignment_queues_a_notification_to_an_external_owner(
    store: NonCommitting, session: Session
) -> None:
    action = _accept(
        store,
        _recommendation(store, _study(store)),
        ownerName="Fixture Contractor",
        ownerEmail="contractor@fixture.test",
    )
    (queued,) = _notifications(session, action.id)
    assert queued.event_type == "action_assigned"
    assert queued.status == "queued"
    assert queued.recipient_email == "contractor@fixture.test"
    assert queued.sent_at is None


def test_an_owner_without_email_is_recorded_as_skipped(
    store: NonCommitting, session: Session
) -> None:
    action = _accept(store, _recommendation(store, _study(store)), ownerName="Fixture Person")
    (row,) = _notifications(session, action.id)
    assert row.status == "skipped"
    assert row.status_detail


def test_failed_delivery_is_logged_and_keeps_the_business_change(
    store: NonCommitting,
    session: Session,
    same_session: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    rec_id = _recommendation(store, _study(store))
    action = _accept(
        store, rec_id, ownerName="Fixture Contractor", ownerEmail="contractor@fixture.test"
    )
    (row,) = _notifications(session, action.id)

    def refuse(settings: Settings, message: mail.OutgoingMail) -> None:
        raise mail.MailDeliveryError("The mail server refused the message.")

    with caplog.at_level(logging.WARNING, logger=notifications.logger.name):
        counts = notifications.deliver(same_session, _mail_settings(), [row.id], send=refuse)
    assert counts == {"sent": 0, "failed": 0, "queued": 1}
    session.refresh(row)
    assert row.status == "queued" and row.attempts == 1
    assert row.status_detail == "The mail server refused the message."
    assert row.sent_at is None
    assert "psm notification delivery failed" in caplog.text
    # The acceptance and its action stand.
    assert _rec(store, rec_id).disposition == "accepted"
    assert _action(store, action.id).owner_name == "Fixture Contractor"

    for _ in range(notifications.MAX_ATTEMPTS - 1):
        notifications.deliver(same_session, _mail_settings(), [row.id], send=refuse)
    session.refresh(row)
    assert row.status == "failed"
    (view,) = service.views(store.scope(recommendation_ids=[rec_id]))
    assert view.action is not None and view.action.failed_notification


def test_sent_only_after_the_server_accepts(
    store: NonCommitting, session: Session, same_session: Any
) -> None:
    action = _accept(
        store,
        _recommendation(store, _study(store)),
        ownerName="Fixture Contractor",
        ownerEmail="contractor@fixture.test",
    )
    (row,) = _notifications(session, action.id)
    nothing = notifications.deliver(same_session, Settings(_env_file=None), [row.id])  # type: ignore[call-arg]
    assert nothing == {"sent": 0, "failed": 0, "queued": 0}
    session.refresh(row)
    assert row.status == "queued"

    sent: list[mail.OutgoingMail] = []
    counts = notifications.deliver(
        same_session, _mail_settings(), [row.id], send=lambda s, m: sent.append(m)
    )
    assert counts["sent"] == 1
    session.refresh(row)
    assert row.status == "sent" and row.sent_at is not None
    assert sent[0].to_email == "contractor@fixture.test"


# Endpoints and authorization -----------------------------------------------------------


@pytest.fixture
def api(store: NonCommitting) -> Iterator[Any]:
    def make(*permissions: P) -> TestClient:
        app = create_app()
        app.dependency_overrides[psm_router.psm_store] = lambda: store
        app.dependency_overrides[get_user_principal] = lambda: as_user(*permissions)
        return TestClient(app)

    yield make


BASE = "/api/v1/safety/psm"


@pytest.mark.parametrize(
    "path", ["/options", "/dashboard", "/recommendations", "/actions", "/studies"]
)
def test_reading_requires_psm_view(api: Any, path: str) -> None:
    assert api(P.PSM_VIEW).get(BASE + path).status_code == 200
    assert api(P.SAFETY_VIEW).get(BASE + path).status_code == 403
    assert api().get(BASE + path).status_code == 403


def test_view_only_users_cannot_change_anything(api: Any, store: NonCommitting) -> None:
    study_id = _study(store)
    rec_id = _recommendation(store, study_id)
    viewer = api(P.PSM_VIEW)
    url = f"{BASE}/recommendations/{rec_id}"
    detail = viewer.get(url)
    assert detail.status_code == 200, detail.text
    abilities = detail.json()["abilities"]
    assert not any(abilities.values())
    body = {
        "version": 1,
        "areaEquipment": "Fixture",
        "recommendationText": "Fixture",
        "isDraft": False,
    }
    assert viewer.put(url, json=body).status_code == 403
    assert viewer.post(f"{url}/accept", json={"version": 1, "confirm": True}).status_code == 403
    reject = {"version": 1, "justification": JUSTIFICATION}
    assert viewer.post(f"{url}/reject", json=reject).status_code == 403
    assert _rec(store, rec_id).disposition == "pending_review"


def test_only_disposition_deciders_accept_and_assignment_needs_action_management(
    api: Any, store: NonCommitting
) -> None:
    rec_id = _recommendation(store, _study(store))
    url = f"{BASE}/recommendations/{rec_id}/accept"
    editor = api(P.PSM_VIEW, P.PSM_EDIT_RECOMMENDATIONS)
    assert editor.post(url, json={"version": 1, "confirm": True}).status_code == 403
    decider = api(P.PSM_VIEW, P.PSM_DECIDE_DISPOSITION)
    assigned = {"version": 1, "confirm": True, "ownerName": "Fixture Owner"}
    refused = decider.post(url, json=assigned)
    assert refused.status_code == 403
    assert _actions_of(store.session, rec_id) == 0
    accepted = decider.post(url, json={"version": 1, "confirm": True})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["action"]["status"] == "not_started"
    again = decider.post(url, json={"version": accepted.json()["version"], "confirm": True})
    assert again.status_code == 422
    assert _actions_of(store.session, rec_id) == 1


def test_closure_request_and_verification_permissions(api: Any, store: NonCommitting) -> None:
    action = _start(store, _accept(store, _recommendation(store, _study(store))))
    _evidence(store, action.id)
    url = f"{BASE}/actions/{action.id}"
    request = {"version": action.version, "summary": "Fixture: alarm installed and tested."}
    assert (
        api(P.PSM_VIEW, P.PSM_MANAGE_ACTIONS)
        .post(f"{url}/closure-request", json=request)
        .status_code
        == 403
    )
    requester = api(P.PSM_VIEW, P.PSM_REQUEST_CLOSURE)
    made = requester.post(f"{url}/closure-request", json=request)
    assert made.status_code == 200, made.text
    version = made.json()["action"]["version"]
    assert made.json()["action"]["status"] == "pending_verification"
    assert requester.post(f"{url}/closure-approval", json={"version": version}).status_code == 403
    verifier = api(P.PSM_VIEW, P.PSM_VERIFY_CLOSURE)
    approved = verifier.post(f"{url}/closure-approval", json={"version": version})
    assert approved.status_code == 200, approved.text
    assert approved.json()["action"]["status"] == "closed"
    reopen = {"version": approved.json()["action"]["version"], "reason": REASON}
    assert verifier.post(f"{url}/reopen", json=reopen).status_code == 403
    assert api(P.PSM_VIEW, P.PSM_REOPEN).post(f"{url}/reopen", json=reopen).status_code == 200


def test_closing_through_an_edit_or_status_change_is_refused(
    api: Any, store: NonCommitting
) -> None:
    action = _accept(store, _recommendation(store, _study(store)))
    manager = api(P.PSM_VIEW, P.PSM_MANAGE_ACTIONS)
    url = f"{BASE}/actions/{action.id}"
    closed = manager.post(f"{url}/status", json={"version": action.version, "status": "closed"})
    assert closed.status_code == 422
    edited = manager.put(
        url, json={"version": action.version, "title": action.title, "status": "closed"}
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["action"]["status"] == "not_started"


def test_import_needs_the_import_permission(api: Any) -> None:
    url = f"{BASE}/imports/pha/plan?fileName=Fixture.xlsx"
    refused = api(P.PSM_VIEW, P.PSM_ADMIN).post(url, content=b"not a workbook")
    assert refused.status_code == 403
    invalid = api(P.PSM_IMPORT).post(url, content=b"not a workbook")
    assert invalid.status_code == 422


def test_dashboard_and_register_filters_agree(api: Any, store: NonCommitting) -> None:
    study_id = _study(store)
    _recommendation(store, study_id, "low", "medium")
    rejected = _recommendation(store, study_id, "high")
    _reject(store, rejected)
    accepted = _recommendation(store, study_id, "medium")
    _accept(store, accepted, dueDate="2003-01-31")
    viewer = api(P.PSM_VIEW)
    board = viewer.get(f"{BASE}/dashboard", params={"studyId": study_id}).json()
    assert board["kpis"]["total"] == 3
    assert board["kpis"]["overdue"] == 1
    assert board["scenarioRisks"] == {"high": 1, "medium": 2, "low": 1}
    assert board["governingRisks"] == {"high": 1, "medium": 2, "low": 0}
    assert board["matrix"]["medium"]["no_action"] == 1
    assert board["matrix"]["medium"]["not_started"] == 1

    cell = viewer.get(
        f"{BASE}/recommendations",
        params={"studyId": study_id, "matrixRisk": "medium", "matrixColumn": "not_started"},
    ).json()
    assert [row["id"] for row in cell["rows"]] == [accepted]
    overdue = viewer.get(f"{BASE}/actions", params={"studyId": study_id, "tab": "overdue"}).json()
    assert overdue["total"] == board["kpis"]["overdue"]
    risky = viewer.get(
        f"{BASE}/recommendations", params={"studyId": study_id, "governingRisk": "medium"}
    ).json()
    assert risky["total"] == board["governingRisks"]["medium"]
    for bucket in board["aging"]:
        aged = viewer.get(
            f"{BASE}/actions", params={"studyId": study_id, "aging": bucket["code"]}
        ).json()
        assert aged["total"] == bucket["count"]
    refused = viewer.get(f"{BASE}/actions", params={"aging": "forever"})
    assert refused.status_code == 422
