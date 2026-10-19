"""PostgreSQL tests for the shared Notifications platform (migration 0018)."""

from __future__ import annotations

import json
import secrets
import sys
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from postgres_support import requires_postgres
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, insert, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.audit.models import AuditEvent
from app.auth.credentials import hash_password
from app.auth.models import User, UserRole
from app.core.config import Settings, get_settings
from app.main import create_app
from app.notifications.models import (
    EmailDelivery,
    EmailTemplate,
    NotificationEvent,
    NotificationOutbox,
    NotificationWorkflow,
)
from app.notifications.outbox import claim_outbox, process_pending
from app.notifications.publisher import has_enabled_workflow, publish_notification_event
from app.notifications.service import Actor, publish_revision, update_workflow

pytestmark = requires_postgres

HEADERS = {"X-Requested-With": "operations-platform"}


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()


@pytest.fixture
def maker(connection: Connection) -> sessionmaker[Session]:
    return sessionmaker(bind=connection, join_transaction_mode="create_savepoint")


@pytest.fixture
def app(maker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    application = create_app()
    for name, module in list(sys.modules.items()):
        if name.startswith("app.") and hasattr(module, "get_sessionmaker"):
            monkeypatch.setattr(module, "get_sessionmaker", lambda: maker)
    return application


def _password() -> str:
    return secrets.token_urlsafe(18)


def _user(
    connection: Connection, *roles: str, password: str | None = None
) -> tuple[uuid.UUID, str]:
    user_id = uuid.uuid4()
    email = f"user-{user_id.hex[:10]}@fixture.test"
    connection.execute(
        insert(User).values(
            id=user_id,
            email=email,
            name=f"Fixture {user_id.hex[:6]}",
            status="active",
            password_hash=hash_password(password) if password else None,
            created_by="fixture",
            updated_by="fixture",
        )
    )
    for role in roles:
        connection.execute(
            insert(UserRole).values(user_id=user_id, role_code=role, assigned_by="fixture")
        )
    return user_id, email


def _sign_in(
    app: FastAPI, email: str, password: str, settings: Settings | None = None
) -> TestClient:
    application = app
    if settings is not None:
        application.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(application)
    response = client.post(
        "/api/v1/auth/sign-in", json={"email": email, "password": password}, headers=HEADERS
    )
    assert response.status_code == 204, response.text
    return client


def _admin_client(
    app: FastAPI, connection: Connection, settings: Settings | None = None
) -> TestClient:
    password = _password()
    _, email = _user(connection, "ADMIN", password=password)
    return _sign_in(app, email, password, settings=settings)


def test_notifications_schema_and_seed_tables(connection: Connection) -> None:
    schemas = inspect(connection).get_schema_names()
    assert "notifications" in schemas
    tables = set(inspect(connection).get_table_names(schema="notifications"))
    for name in (
        "notification_event_types",
        "email_templates",
        "email_template_revisions",
        "notification_workflows",
        "workflow_recipient_rules",
        "notification_events",
        "notification_outbox",
        "email_deliveries",
        "email_delivery_attempts",
        "notification_settings",
    ):
        assert name in tables
    event_count = connection.execute(
        text("SELECT count(*) FROM notifications.notification_event_types")
    ).scalar_one()
    assert event_count >= 2
    workflow_enabled = connection.execute(
        text(
            "SELECT enabled FROM notifications.notification_workflows "
            "WHERE code = 'psm.action.assigned.owner'"
        )
    ).scalar_one()
    assert workflow_enabled is False


def test_publish_without_enabled_workflow_skips_outbox(connection: Connection) -> None:
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        event = publish_notification_event(
            session,
            event_type_code="psm.action.assigned",
            entity_type="safety.psm_action",
            entity_id="1",
            entity_reference="PSM-1",
            payload={"action": {"title": "T", "reference": "PSM-1"}},
            actor_user_id=None,
            idempotency_key=f"test-no-outbox-{uuid.uuid4()}",
        )
        session.flush()
        assert event is not None
        outbox = session.scalars(
            select(NotificationOutbox).where(NotificationOutbox.notification_event_id == event.id)
        ).all()
        assert outbox == []


def test_publish_with_enabled_workflow_creates_outbox(connection: Connection) -> None:
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        workflow = session.scalar(
            select(NotificationWorkflow).where(
                NotificationWorkflow.code == "psm.action.assigned.owner"
            )
        )
        assert workflow is not None
        # Enabling requires a published revision — publish the seeded draft first.
        template = session.get(EmailTemplate, workflow.template_id)
        assert template is not None
        draft_id = session.execute(
            text(
                "SELECT id FROM notifications.email_template_revisions "
                "WHERE template_id = :tid AND status = 'draft' ORDER BY id LIMIT 1"
            ),
            {"tid": template.id},
        ).scalar_one()
        actor = Actor(actor_id="fixture", user_id=uuid.uuid4())
        publish_revision(
            session,
            template.id,
            draft_id,
            actor=actor,
            event_type_code="psm.action.assigned",
        )
        update_workflow(
            session,
            workflow.id,
            actor=actor,
            display_name=None,
            enabled=True,
            delivery_timing_code=None,
            schedule_config_json=None,
            recipient_rules=None,
        )
        assert has_enabled_workflow(session, "psm.action.assigned")

        event = publish_notification_event(
            session,
            event_type_code="psm.action.assigned",
            entity_type="safety.psm_action",
            entity_id="42",
            entity_reference="PSM-42",
            payload=_psm_payload("PSM-42"),
            actor_user_id=None,
            idempotency_key=f"test-outbox-{uuid.uuid4()}",
        )
        session.flush()
        assert event is not None
        rows = session.scalars(
            select(NotificationOutbox).where(NotificationOutbox.notification_event_id == event.id)
        ).all()
        assert len(rows) == 1
        assert rows[0].status == "pending"


def test_idempotent_publish(connection: Connection) -> None:
    key = f"idem-{uuid.uuid4()}"
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        first = publish_notification_event(
            session,
            event_type_code="psm.action.assigned",
            entity_type="safety.psm_action",
            entity_id="9",
            entity_reference="PSM-9",
            payload={},
            actor_user_id=None,
            idempotency_key=key,
        )
        session.flush()
        second = publish_notification_event(
            session,
            event_type_code="psm.action.assigned",
            entity_type="safety.psm_action",
            entity_id="9",
            entity_reference="PSM-9",
            payload={"extra": True},
            actor_user_id=None,
            idempotency_key=key,
        )
        session.flush()
        assert first is not None and second is not None
        assert first.id == second.id
        count = session.scalar(
            select(NotificationEvent).where(NotificationEvent.idempotency_key == key)
        )
        assert count is not None


def test_disabled_mode_marks_delivery_without_provider(
    connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        email_enabled=True,
        email_delivery_mode="disabled",
        email_provider="resend",
        email_from_address="from@example.com",
    )
    monkeypatch.setattr("app.notifications.outbox.get_settings", lambda: settings)
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        _enable_owner_workflow(session)
        event = publish_notification_event(
            session,
            event_type_code="psm.action.assigned",
            entity_type="safety.psm_action",
            entity_id="7",
            entity_reference="PSM-7",
            payload=_psm_payload("PSM-7"),
            actor_user_id=None,
            idempotency_key=f"disabled-{uuid.uuid4()}",
        )
        session.flush()
        assert event is not None
        processed = process_pending(session, limit=5)
        session.flush()
        assert processed >= 1
        delivery = session.scalars(
            select(EmailDelivery).where(EmailDelivery.notification_event_id == event.id)
        ).first()
        assert delivery is not None
        assert delivery.status == "disabled"
        assert delivery.delivery_mode == "disabled"
        assert delivery.provider_message_id is None


def test_redirect_mode_uses_mocked_resend(
    connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeResponse:
        status = 200

        def read(self) -> bytes:
            return b'{"id":"redir_1"}'

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, *args: Any, **kwargs: Any) -> FakeResponse:
        captured["body"] = json.loads(request.data.decode("utf-8"))
        auth = request.get_header("Authorization")
        assert auth.startswith("Bearer ")
        assert "re_test_key" not in json.dumps(captured["body"])
        return FakeResponse()

    monkeypatch.setattr("app.notifications.providers.resend.urllib.request.urlopen", fake_urlopen)
    settings = Settings(
        _env_file=None,
        environment="test",
        email_enabled=True,
        email_delivery_mode="redirect",
        email_provider="resend",
        resend_api_key=SecretStr("re_test_key"),
        email_from_address="from@example.com",
        email_redirect_to="sink@example.com",
        app_public_url="https://ops.example.test",
    )
    monkeypatch.setattr("app.notifications.outbox.get_settings", lambda: settings)
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        _enable_owner_workflow(session)
        event = publish_notification_event(
            session,
            event_type_code="psm.action.assigned",
            entity_type="safety.psm_action",
            entity_id="8",
            entity_reference="PSM-8",
            payload=_psm_payload("PSM-8", title="Redirect me"),
            actor_user_id=None,
            idempotency_key=f"redirect-{uuid.uuid4()}",
        )
        session.flush()
        process_pending(session, limit=5)
        session.flush()
        delivery = session.scalars(
            select(EmailDelivery).where(EmailDelivery.notification_event_id == event.id)
        ).first()
        assert delivery is not None
        assert delivery.delivery_mode in {"redirect", "test"}
        assert delivery.status == "accepted"
        assert delivery.provider_message_id == "redir_1"
        assert "sink@example.com" in json.dumps(delivery.actual_to_json)
        assert "re_test_key" not in json.dumps(delivery.__dict__, default=str)


def test_claim_outbox_skip_locked(connection: Connection) -> None:
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        _enable_owner_workflow(session)
        for i in range(3):
            publish_notification_event(
                session,
                event_type_code="psm.action.assigned",
                entity_type="safety.psm_action",
                entity_id=str(100 + i),
                entity_reference=f"PSM-{100 + i}",
                payload=_psm_payload(f"PSM-{100 + i}", title=f"T{i}"),
                actor_user_id=None,
                idempotency_key=f"claim-{uuid.uuid4()}",
            )
        session.flush()
        first = claim_outbox(session, worker_id="w1", limit=2)
        assert len(first) == 2
        second = claim_outbox(session, worker_id="w2", limit=2)
        first_ids = {row.id for row in first}
        second_ids = {row.id for row in second}
        assert first_ids.isdisjoint(second_ids)


def test_admin_overview_requires_permission(app: FastAPI, connection: Connection) -> None:
    password = _password()
    _, email = _user(connection, password=password)  # no roles
    settings = Settings(_env_file=None, environment="test", session_cookie_secure=False)
    client = _sign_in(app, email, password, settings=settings)
    response = client.get("/api/v1/admin/notifications/overview")
    assert response.status_code == 403


def test_admin_overview_and_settings_hide_secrets(app: FastAPI, connection: Connection) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        session_cookie_secure=False,
        email_enabled=True,
        email_delivery_mode="redirect",
        email_provider="resend",
        resend_api_key=SecretStr("re_must_not_leak"),
        email_from_address="from@example.com",
        email_redirect_to="sink@example.com",
    )
    client = _admin_client(app, connection, settings=settings)
    overview = client.get("/api/v1/admin/notifications/overview")
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["apiKeyConfigured"] is True
    raw = overview.text
    assert "re_must_not_leak" not in raw
    assert "RESEND_API_KEY" not in raw
    settings_resp = client.get("/api/v1/admin/notifications/settings")
    assert settings_resp.status_code == 200
    assert "re_must_not_leak" not in settings_resp.text


def test_emergency_pause_audited_without_bodies(app: FastAPI, connection: Connection) -> None:
    settings = Settings(_env_file=None, environment="test", session_cookie_secure=False)
    client = _admin_client(app, connection, settings=settings)
    response = client.patch(
        "/api/v1/admin/notifications/settings",
        json={"emergencyPause": True},
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        events = session.scalars(
            select(AuditEvent).order_by(AuditEvent.id.desc()).limit(20)
        ).all()
        matching = [e for e in events if "notification" in (e.entity_type or "").lower()]
        assert matching
        for event in matching:
            blob = json.dumps({"old": event.old_value, "new": event.new_value}, default=str)
            assert "<html" not in blob.lower()
            assert "re_must_not_leak" not in blob


def test_production_live_misconfig_fails_ready(
    app: FastAPI, maker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        moisture_data_source="database",
        database_url=SecretStr("postgresql+psycopg://u:p@localhost:5432/ops"),
        ingestion_auth_mode="disabled",
        email_enabled=True,
        email_delivery_mode="live",
        email_provider="resend",
        session_cookie_secure=True,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr("app.api.v1.health.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.v1.health.get_sessionmaker", lambda: maker)
    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body.get("notifications") is not None


def _psm_payload(reference: str, *, title: str = "Fix valve") -> dict[str, Any]:
    return {
        "action.reference": reference,
        "action.title": title,
        "action.owner_name": "Ada",
        "action.due_date": "2026-11-01",
        "action.status": "open",
        "action.url": f"https://ops.example.test/safety/psm/actions/{reference}",
        "recommendation.reference": "REC-1",
        "owner_email": "owner@example.com",
        "owner_name": "Ada",
    }


def _enable_owner_workflow(session: Session) -> NotificationWorkflow:
    workflow = session.scalar(
        select(NotificationWorkflow).where(NotificationWorkflow.code == "psm.action.assigned.owner")
    )
    assert workflow is not None
    draft_id = session.execute(
        text(
            "SELECT id FROM notifications.email_template_revisions "
            "WHERE template_id = :tid AND status = 'draft' ORDER BY id LIMIT 1"
        ),
        {"tid": workflow.template_id},
    ).scalar_one()
    actor = Actor(actor_id="fixture", user_id=uuid.uuid4())
    template = session.get(EmailTemplate, workflow.template_id)
    assert template is not None
    if template.current_published_revision_id is None:
        publish_revision(
            session,
            template.id,
            int(draft_id),
            actor=actor,
            event_type_code="psm.action.assigned",
        )
    update_workflow(
        session,
        workflow.id,
        actor=actor,
        display_name=None,
        enabled=True,
        delivery_timing_code=None,
        schedule_config_json=None,
        recipient_rules=None,
    )
    session.flush()
    return workflow
