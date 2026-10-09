"""PostgreSQL tests for sign-in, sessions, administration and My Assignments
(migration 0013).

Enabled by TEST_DATABASE_URL (see postgres_support.py). Requests go through
the real cookie and session path; every database session the application
opens is bound to one connection whose transaction is rolled back after each
test, so fixture users (``@fixture.test``) and their changes never persist.
Passwords are generated per test and never written down.
"""

import datetime as dt
import hashlib
import secrets
import sys
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from postgres_support import requires_postgres
from sqlalchemy import Connection, Engine, delete, insert, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.audit.models import AuditEvent
from app.auth import cli
from app.auth.credentials import hash_password
from app.auth.models import AuthSession, PasswordToken, Role, RolePermission, User, UserRole
from app.core.config import Settings, get_settings
from app.main import create_app
from app.quality.car.models import Car, CarAction

pytestmark = requires_postgres

HEADERS = {"X-Requested-With": "operations-platform"}
SETTINGS = Settings(
    _env_file=None,
    environment="test",
    session_cookie_secure=False,
    login_max_failures=3,
)
COOKIE = "op_session"


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
    application.dependency_overrides[get_settings] = lambda: SETTINGS
    return application


def _all(connection: Connection, statement: Any) -> list[Any]:
    """ORM objects read inside the test transaction."""
    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        return list(db.scalars(statement))


def _password() -> str:
    return secrets.token_urlsafe(18)


def _user(
    connection: Connection,
    *roles: str,
    password: str | None = None,
    status: str = "active",
    name: str | None = None,
) -> tuple[uuid.UUID, str]:
    """A fixture user; returns (id, email)."""
    user_id = uuid.uuid4()
    email = f"user-{user_id.hex[:10]}@fixture.test"
    connection.execute(
        insert(User).values(
            id=user_id,
            email=email,
            name=name or f"Fixture {user_id.hex[:6]}",
            status=status,
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


def _sign_in(app: FastAPI, email: str, password: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/sign-in", json={"email": email, "password": password}, headers=HEADERS
    )
    assert response.status_code == 204, response.text
    return client


def _signed_in(app: FastAPI, connection: Connection, *roles: str) -> tuple[TestClient, uuid.UUID]:
    password = _password()
    user_id, email = _user(connection, *roles, password=password)
    return _sign_in(app, email, password), user_id


# Sign-in ------------------------------------------------------------------------------


def test_sign_in_sets_an_http_only_cookie_and_stores_only_its_hash(
    app: FastAPI, connection: Connection
) -> None:
    password = _password()
    user_id, email = _user(connection, "QUALITY_USER", password=password)
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/sign-in",
        json={"email": f"  {email.upper()} ", "password": password},
        headers=HEADERS,
    )
    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    token = client.cookies[COOKIE]
    stored = connection.execute(
        select(AuthSession.token_hash).where(AuthSession.user_id == user_id)
    ).scalar_one()
    assert stored == hashlib.sha256(token.encode()).digest()
    assert token.encode() != stored

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["user"]["id"] == str(user_id)
    assert body["user"]["email"] == email
    assert [r["code"] for r in body["roles"]] == ["QUALITY_USER"]
    assert "car.create" in body["permissions"]
    assert "car.close" not in body["permissions"]
    text = me.text.lower()
    assert "hash" not in text and "token" not in text and password.lower() not in text
    last_login = connection.execute(select(User.last_login_at).where(User.id == user_id))
    assert last_login.scalar_one() is not None


def test_sign_in_needs_the_application_header(app: FastAPI, connection: Connection) -> None:
    password = _password()
    _, email = _user(connection, "VIEWER", password=password)
    response = TestClient(app).post(
        "/api/v1/auth/sign-in", json={"email": email, "password": password}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "csrf_check_failed"


def test_every_refused_sign_in_gets_the_same_answer(app: FastAPI, connection: Connection) -> None:
    password = _password()
    _, active = _user(connection, "VIEWER", password=password)
    _, inactive = _user(connection, "VIEWER", password=password, status="inactive")
    _, no_password = _user(connection, "VIEWER")
    client = TestClient(app)
    answers = []
    for email, attempt in (
        (active, _password()),
        ("nobody@fixture.test", password),
        (inactive, password),
        (no_password, password),
    ):
        response = client.post(
            "/api/v1/auth/sign-in", json={"email": email, "password": attempt}, headers=HEADERS
        )
        assert response.status_code == 401
        answers.append(response.json())
    assert all(a == answers[0] for a in answers)
    assert answers[0]["detail"]["error"] == "sign_in_failed"
    assert COOKIE not in client.cookies


def test_repeated_failures_lock_the_account(app: FastAPI, connection: Connection) -> None:
    password = _password()
    user_id, email = _user(connection, "VIEWER", password=password)
    client = TestClient(app)
    for _ in range(SETTINGS.login_max_failures):
        client.post(
            "/api/v1/auth/sign-in", json={"email": email, "password": _password()}, headers=HEADERS
        )
    locked = client.post(
        "/api/v1/auth/sign-in", json={"email": email, "password": password}, headers=HEADERS
    )
    assert locked.status_code == 401
    until = connection.execute(select(User.locked_until).where(User.id == user_id)).scalar_one()
    assert until is not None and until > dt.datetime.now(dt.UTC)


def test_logging_never_contains_the_password_or_token(
    app: FastAPI, connection: Connection, caplog: pytest.LogCaptureFixture
) -> None:
    password = _password()
    _, email = _user(connection, "VIEWER", password=password)
    caplog.set_level("DEBUG")
    client = _sign_in(app, email, password)
    client.post(
        "/api/v1/auth/sign-in", json={"email": email, "password": _password()}, headers=HEADERS
    )
    logged = caplog.text
    assert password not in logged
    assert client.cookies[COOKIE] not in logged
    assert email not in logged


# Sessions --------------------------------------------------------------------------------


def test_signed_out_requests_get_401_and_signing_out_ends_the_session(
    app: FastAPI, connection: Connection
) -> None:
    anonymous = TestClient(app)
    assert anonymous.get("/api/v1/auth/me").status_code == 401
    assert anonymous.get("/api/v1/quality/cars").status_code == 401
    client, _ = _signed_in(app, connection, "VIEWER")
    token = client.cookies[COOKIE]
    assert client.get("/api/v1/quality/cars").status_code == 200
    assert client.post("/api/v1/auth/sign-out", headers=HEADERS).status_code == 204
    replay = TestClient(app, cookies={COOKIE: token})
    assert replay.get("/api/v1/auth/me").status_code == 401
    assert replay.get("/api/v1/quality/cars").status_code == 401


def test_an_expired_or_idle_session_is_refused(app: FastAPI, connection: Connection) -> None:
    client, user_id = _signed_in(app, connection, "VIEWER")
    connection.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id)
        .values(last_seen_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=2))
    )
    assert client.get("/api/v1/auth/me").status_code == 401


def test_writes_with_a_session_need_the_application_header(
    app: FastAPI, connection: Connection
) -> None:
    client, _ = _signed_in(app, connection, "QUALITY_USER")
    body = {"subject": "Fixture", "requestDate": "2003-05-01"}
    refused = client.post("/api/v1/quality/cars", json=body)
    assert refused.status_code == 403
    assert refused.json()["detail"]["error"] == "csrf_check_failed"
    assert client.post("/api/v1/quality/cars", json=body, headers=HEADERS).status_code == 201


def test_access_changes_take_effect_on_the_next_request(
    app: FastAPI, connection: Connection
) -> None:
    client, user_id = _signed_in(app, connection, "QUALITY_USER")
    cars = "/api/v1/quality/cars"
    assert client.get(cars).status_code == 200

    # An inactive role grants nothing.
    connection.execute(update(Role).where(Role.code == "QUALITY_USER").values(active=False))
    assert client.get(cars).status_code == 403
    connection.execute(update(Role).where(Role.code == "QUALITY_USER").values(active=True))
    assert client.get(cars).status_code == 200

    # A removed permission or role is gone at once.
    connection.execute(
        delete(RolePermission).where(
            RolePermission.role_code == "QUALITY_USER", RolePermission.permission_code == "car.view"
        )
    )
    assert client.get(cars).status_code == 403
    connection.execute(delete(UserRole).where(UserRole.user_id == user_id))
    assert client.get("/api/v1/auth/me").json()["permissions"] == []

    # A deactivated user is signed out.
    connection.execute(update(User).where(User.id == user_id).values(status="inactive"))
    assert client.get("/api/v1/auth/me").status_code == 401


def test_permissions_are_the_union_of_active_roles(app: FastAPI, connection: Connection) -> None:
    client, _ = _signed_in(app, connection, "QUALITY_USER", "SAFETY_USER")
    permissions = set(client.get("/api/v1/auth/me").json()["permissions"])
    assert {"car.create", "incident.create", "safetyObservation.create"} <= permissions
    assert not {"car.close", "incident.close", "users.manage", "roles.manage"} & permissions
    assert client.get("/api/v1/quality/cars").status_code == 200
    assert client.get("/api/v1/safety/observations/categories").status_code == 200
    assert client.get("/api/v1/admin/users").status_code == 403


# Passwords ---------------------------------------------------------------------------


def test_a_setup_link_sets_the_password_once(app: FastAPI, connection: Connection) -> None:
    admin, _ = _signed_in(app, connection, "ADMIN")
    created = admin.post(
        "/api/v1/admin/users",
        json={"email": "New.Person@Fixture.test", "name": "New Person", "roleCodes": ["VIEWER"]},
        headers=HEADERS,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["user"]["email"] == "new.person@fixture.test"
    assert body["user"]["passwordSet"] is False
    token = body["passwordLink"]["token"]
    stored = connection.execute(
        select(PasswordToken.token_hash).where(
            PasswordToken.user_id == uuid.UUID(body["user"]["id"])
        )
    ).scalar_one()
    assert stored == hashlib.sha256(token.encode()).digest()

    anonymous = TestClient(app)
    checked = anonymous.post(
        "/api/v1/auth/password-link/check", json={"token": token}, headers=HEADERS
    )
    assert checked.json() == {"name": "New Person", "email": "new.person@fixture.test"}
    weak = anonymous.post(
        "/api/v1/auth/password-link", json={"token": token, "password": "short"}, headers=HEADERS
    )
    assert weak.status_code == 422
    password = _password()
    assert (
        anonymous.post(
            "/api/v1/auth/password-link",
            json={"token": token, "password": password},
            headers=HEADERS,
        ).status_code
        == 204
    )
    reused = anonymous.post(
        "/api/v1/auth/password-link",
        json={"token": token, "password": _password()},
        headers=HEADERS,
    )
    assert reused.status_code == 400
    assert reused.json()["detail"]["error"] == "link_invalid"
    _sign_in(app, "new.person@fixture.test", password)

    duplicate = admin.post(
        "/api/v1/admin/users",
        json={"email": "NEW.person@fixture.test", "name": "Again", "roleCodes": []},
        headers=HEADERS,
    )
    assert duplicate.status_code == 409


def test_changing_your_password_ends_your_other_sessions(
    app: FastAPI, connection: Connection
) -> None:
    password = _password()
    _, email = _user(connection, "VIEWER", password=password)
    first = _sign_in(app, email, password)
    second = _sign_in(app, email, password)
    wrong = first.post(
        "/api/v1/auth/password",
        json={"currentPassword": _password(), "newPassword": _password()},
        headers=HEADERS,
    )
    assert wrong.status_code == 422
    new = _password()
    changed = first.post(
        "/api/v1/auth/password",
        json={"currentPassword": password, "newPassword": new},
        headers=HEADERS,
    )
    assert changed.status_code == 204
    assert first.get("/api/v1/auth/me").status_code == 200
    assert second.get("/api/v1/auth/me").status_code == 401
    _sign_in(app, email, new)


# Administration --------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["QUALITY_ADMIN", "SAFETY_ADMIN", "QUALITY_USER", "VIEWER"])
def test_only_administrators_manage_users_and_roles(
    app: FastAPI, connection: Connection, role: str
) -> None:
    client, _ = _signed_in(app, connection, role)
    for method, url, body in (
        ("get", "/api/v1/admin/users", None),
        ("get", "/api/v1/admin/roles", None),
        ("post", "/api/v1/admin/users", {"email": "x@fixture.test", "name": "X"}),
        ("post", "/api/v1/admin/roles", {"code": "FIXTURE_ROLE", "name": "Fixture"}),
    ):
        response = client.request(method, url, json=body, headers=HEADERS)
        assert response.status_code == 403, (role, url)
        detail = response.json()["detail"]
        assert detail == {
            "error": "permission_denied",
            "message": "You do not have permission to perform this action.",
        }
    assert TestClient(app).get("/api/v1/admin/users").status_code == 401


def test_admins_see_inactive_users_and_effective_permissions(
    app: FastAPI, connection: Connection
) -> None:
    admin, _ = _signed_in(app, connection, "ADMIN")
    user_id, _ = _user(connection, "QUALITY_USER", "SAFETY_USER", password=_password())
    detail = admin.get(f"/api/v1/admin/users/{user_id}").json()
    assert {r["code"] for r in detail["roles"]} == {"QUALITY_USER", "SAFETY_USER"}
    assert "car.create" in detail["permissions"] and "incident.create" in detail["permissions"]
    assert "passwordHash" not in str(detail) and detail["passwordSet"] is True

    deactivated = admin.post(f"/api/v1/admin/users/{user_id}/deactivate", headers=HEADERS)
    assert deactivated.json()["status"] == "inactive"
    assert deactivated.json()["permissions"] == []
    listed = admin.get("/api/v1/admin/users").json()["users"]
    assert str(user_id) in {u["id"] for u in listed}
    directory = admin.get("/api/v1/users/directory").json()["users"]
    assert str(user_id) not in {u["id"] for u in directory}
    everyone = admin.get("/api/v1/users/directory", params={"includeInactive": True}).json()
    (entry,) = [u for u in everyone["users"] if u["id"] == str(user_id)]
    assert entry["active"] is False


def test_a_delegated_user_administrator_cannot_escalate(
    app: FastAPI, connection: Connection
) -> None:
    connection.execute(
        insert(Role).values(code="FIXTURE_USER_ADMIN", name="Fixture user admin", description="")
    )
    connection.execute(
        insert(RolePermission),
        [
            {"role_code": "FIXTURE_USER_ADMIN", "permission_code": code}
            for code in (
                "app.view",
                "users.view",
                "users.create",
                "users.assignRoles",
                "roles.view",
                "car.view",
            )
        ],
    )
    client, _ = _signed_in(app, connection, "FIXTURE_USER_ADMIN")
    for roles in (["ADMIN"], ["QUALITY_ADMIN"], ["VIEWER"]):
        response = client.post(
            "/api/v1/admin/users",
            json={"email": f"{roles[0].lower()}@fixture.test", "name": "X", "roleCodes": roles},
            headers=HEADERS,
        )
        assert response.status_code == 403, roles
    unknown = client.post(
        "/api/v1/admin/users",
        json={"email": "u@fixture.test", "name": "X", "roleCodes": ["NO_SUCH_ROLE"]},
        headers=HEADERS,
    )
    assert unknown.status_code == 422


def test_roles_only_hold_known_permissions_and_standard_roles_are_protected(
    app: FastAPI, connection: Connection
) -> None:
    admin, _ = _signed_in(app, connection, "ADMIN")
    unknown = admin.post(
        "/api/v1/admin/roles",
        json={"code": "FIXTURE_ROLE", "name": "Fixture", "permissions": ["car.fly"]},
        headers=HEADERS,
    )
    assert unknown.status_code == 422
    created = admin.post(
        "/api/v1/admin/roles",
        json={"code": "FIXTURE_ROLE", "name": "Fixture", "permissions": ["car.view"]},
        headers=HEADERS,
    )
    assert created.status_code == 201, created.text
    assert created.json()["isSystem"] is False
    granted = admin.put(
        "/api/v1/admin/roles/FIXTURE_ROLE/permissions",
        json={"permissions": ["car.view", "car.export"]},
        headers=HEADERS,
    )
    assert granted.json()["permissions"] == ["car.export", "car.view"]
    assert admin.delete("/api/v1/admin/roles/FIXTURE_ROLE", headers=HEADERS).status_code == 204

    assert admin.delete("/api/v1/admin/roles/VIEWER", headers=HEADERS).status_code == 422
    renamed = admin.put(
        "/api/v1/admin/roles/VIEWER",
        json={"name": "Renamed", "description": "", "active": True},
        headers=HEADERS,
    )
    assert renamed.status_code == 422
    admin_role = admin.put(
        "/api/v1/admin/roles/ADMIN/permissions", json={"permissions": []}, headers=HEADERS
    )
    assert admin_role.status_code == 422
    deactivate_admin = admin.put(
        "/api/v1/admin/roles/ADMIN",
        json={"name": "Administrator", "description": "", "active": False},
        headers=HEADERS,
    )
    assert deactivate_admin.status_code == 422


def _only_administrator(connection: Connection) -> None:
    """Deactivate every other user (rolled back with the test)."""
    connection.execute(update(User).values(status="inactive"))


def test_the_last_administrator_cannot_be_removed(app: FastAPI, connection: Connection) -> None:
    _only_administrator(connection)
    admin, admin_id = _signed_in(app, connection, "ADMIN")
    own = f"/api/v1/admin/users/{admin_id}"

    me = admin.post(f"{own}/deactivate", headers=HEADERS)
    assert me.status_code == 422
    assert me.json()["detail"]["error"] == "deactivate_self"
    demoted = admin.put(f"{own}/roles", json={"roleCodes": ["VIEWER"]}, headers=HEADERS)
    assert demoted.status_code == 422
    assert demoted.json()["detail"]["error"] == "last_administrator"

    # With a second administrator, the first may step down.
    password = _password()
    other_id, other_email = _user(connection, "ADMIN", password=password)
    assert (
        admin.put(f"{own}/roles", json={"roleCodes": ["VIEWER"]}, headers=HEADERS).status_code
        == 200
    )
    roles = connection.execute(select(UserRole.role_code).where(UserRole.user_id == admin_id))
    assert roles.scalars().all() == ["VIEWER"]
    # Now the second is the last one, and cannot be deactivated or lose the role.
    second = _sign_in(app, other_email, password)
    assert (
        second.put(
            f"/api/v1/admin/users/{other_id}/roles", json={"roleCodes": []}, headers=HEADERS
        ).json()["detail"]["error"]
        == "last_administrator"
    )
    assert (
        second.put(
            "/api/v1/admin/roles/ADMIN",
            json={"name": "Administrator", "description": "", "active": False},
            headers=HEADERS,
        ).status_code
        == 422
    )


def test_administration_changes_are_audited_with_the_acting_user(
    app: FastAPI, connection: Connection
) -> None:
    admin, admin_id = _signed_in(app, connection, "ADMIN")
    user_id, _ = _user(connection, "VIEWER", password=_password())
    admin.put(
        f"/api/v1/admin/users/{user_id}/roles",
        json={"roleCodes": ["QUALITY_USER"]},
        headers=HEADERS,
    )
    admin.post(f"/api/v1/admin/users/{user_id}/password-link", headers=HEADERS)
    event, link = _all(
        connection,
        select(AuditEvent)
        .where(AuditEvent.entity_key == f"users/{user_id}")
        .order_by(AuditEvent.id),
    )
    assert link.new_value == {"passwordSet": True, "passwordLinkIssued": "reset"}
    assert link.actor_user_id == admin_id
    assert event.actor_id == str(admin_id)
    assert event.actor_user_id == admin_id
    assert event.actor_name is not None
    assert event.old_value["roles"] == ["VIEWER"]
    assert event.new_value["roles"] == ["QUALITY_USER"]
    stored = str(event.old_value) + str(event.new_value)
    assert "hash" not in stored.lower() and "token" not in stored.lower()

    log = admin.get("/api/v1/admin/audit", params={"actorUserId": str(admin_id)}).json()
    assert log["total"] >= 1
    assert all(e["actorId"] == str(admin_id) for e in log["events"])


# Bootstrap -------------------------------------------------------------------------------


def test_bootstrap_creates_the_first_administrator_once(
    maker: sessionmaker[Session], connection: Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    _only_administrator(connection)
    with maker() as db:
        assert cli.bootstrap_admin(db, "first.admin@fixture.test", "First Admin", None) == 0
    out = capsys.readouterr().out
    assert "/setup-password#token=" in out
    (user,) = _all(connection, select(User).where(User.email == "first.admin@fixture.test"))
    assert user.password_hash is None
    roles = connection.execute(select(UserRole.role_code).where(UserRole.user_id == user.id))
    assert roles.scalars().all() == ["ADMIN"]

    with maker() as db:
        assert cli.bootstrap_admin(db, "second.admin@fixture.test", "Second", None) == 1
    assert "Refused" in capsys.readouterr().err
    assert (
        connection.execute(select(User.id).where(User.email == "second.admin@fixture.test")).first()
        is None
    )


# My Assignments ---------------------------------------------------------------------------


def _car(connection: Connection, number: str, **values: Any) -> int:
    return connection.execute(
        insert(Car)
        .values(
            car_number=number,
            **{
                "subject": f"Fixture {number}",
                "request_date": dt.date(2003, 1, 1),
                "status": "open",
                "created_by": "fixture",
                "updated_by": "fixture",
                **values,
            },
        )
        .returning(Car.id)
    ).scalar_one()


def test_my_assignments_are_those_of_the_session_user(app: FastAPI, connection: Connection) -> None:
    client, user_id = _signed_in(app, connection, "QUALITY_USER")
    other, other_id = _signed_in(app, connection, "QUALITY_USER")
    mine = _car(connection, "Q-2003-801", assigned_to="Me", assigned_to_user_id=user_id)
    _car(connection, "Q-2003-802", assigned_to="Other", assigned_to_user_id=other_id)
    _car(
        connection,
        "Q-2003-803",
        assigned_to="Me",
        assigned_to_user_id=user_id,
        status="closed",
        date_closed=dt.date(2003, 2, 1),
        effectiveness_result="effective",
    )
    connection.execute(
        insert(CarAction).values(
            car_id=mine,
            position=1,
            action="Fixture action",
            status="open",
            owner="Me",
            owner_user_id=user_id,
            created_by="fixture",
            updated_by="fixture",
        )
    )
    listed = client.get("/api/v1/assignments/mine")
    assert listed.status_code == 200
    items = listed.json()["assignments"]
    assert {(i["kind"], i["reference"]) for i in items} == {
        ("car", "Q-2003-801"),
        ("car_action", "Q-2003-801 action 1"),
    }
    assert {
        i["reference"] for i in other.get("/api/v1/assignments/mine").json()["assignments"]
    } == {"Q-2003-802"}
    # The request cannot name another user.
    spoofed = client.get("/api/v1/assignments/mine", params={"userId": str(other_id)})
    assert {i["reference"] for i in spoofed.json()["assignments"]} >= {"Q-2003-801"}
    assert "Q-2003-802" not in {i["reference"] for i in spoofed.json()["assignments"]}
    assert TestClient(app).get("/api/v1/assignments/mine").status_code == 401
