"""Authorization without a database: the permission catalog, standard roles,
the migration's frozen seed, credentials, session cookies, CSRF, and the
401/403 distinction. (Sign-in, sessions and administration against PostgreSQL:
test_auth_database.py.)"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from principals import as_user

from app.auth import credentials, sessions
from app.auth.roles import ADMIN_CODE, STANDARD_ROLES
from app.core import authorization
from app.core.authorization import ANONYMOUS, get_user_principal
from app.core.config import Settings
from app.core.permissions import Permission
from app.db.session import DatabaseNotConfiguredError
from app.main import create_app

P = Permission
MIGRATION = next(
    (Path(__file__).parents[1] / "alembic" / "versions").glob("*-0013_users_roles_permissions.py")
)
COST_RECORDS = "/api/v1/quality/cost/records"


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0013", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROLES = {role.code: role for role in STANDARD_ROLES}


# Catalog and standard roles ---------------------------------------------------------


def test_standard_roles_are_the_specified_set() -> None:
    assert list(ROLES) == [
        "ADMIN",
        "QUALITY_ADMIN",
        "QUALITY_USER",
        "SAFETY_ADMIN",
        "SAFETY_USER",
        "CONTRIBUTOR",
        "VIEWER",
    ]


def test_admin_holds_every_permission() -> None:
    assert ROLES[ADMIN_CODE].permissions == frozenset(Permission)


def test_only_admin_manages_users_and_roles() -> None:
    for code, role in ROLES.items():
        if code == ADMIN_CODE:
            continue
        assert not role.permissions & {
            P.USERS_MANAGE,
            P.ROLES_MANAGE,
            P.USERS_ASSIGN_ROLES,
            P.ROLES_ASSIGN_PERMISSIONS,
            P.USERS_CREATE,
            P.ROLES_CREATE,
        }, code


def test_module_roles_stay_in_their_module() -> None:
    quality = {p.value.split(".")[0] for p in ROLES["QUALITY_ADMIN"].permissions}
    safety = {p.value.split(".")[0] for p in ROLES["SAFETY_ADMIN"].permissions}
    assert not quality & {"safety", "safetyRecord", "incident", "nearMiss", "safetyDashboard"}
    assert not safety & {"quality", "qualityCost", "car", "qualityDashboard"}


def test_quality_user_cannot_approve_or_close_cars() -> None:
    granted = ROLES["QUALITY_USER"].permissions
    assert P.CAR_COMPLETE_ACTION in granted
    assert not granted & {P.CAR_APPROVE, P.CAR_CLOSE, P.CAR_REOPEN, P.CAR_ADMIN}
    assert not granted & {P.QUALITY_COST_CONFIRM_FINANCIAL, P.QUALITY_COST_CLOSE}


def test_viewer_is_read_only() -> None:
    writes = ("create", "edit", "delete", "close", "approve", "assign", "manage", "admin")
    for permission in ROLES["VIEWER"].permissions:
        action = permission.value.split(".", 1)[1].lower()
        assert not any(action.startswith(w) for w in writes), permission


def test_contributor_has_no_module_access() -> None:
    modules = {p.value.split(".")[0] for p in ROLES["CONTRIBUTOR"].permissions}
    assert modules == {"app", "assignments", "attachments", "comments"}


def test_migration_seed_matches_the_catalog_and_roles() -> None:
    migration = _migration()
    assert set(migration.PERMISSIONS) == {p.value for p in Permission}
    assert len(migration.PERMISSIONS) == len(set(migration.PERMISSIONS))
    assert set(migration.MODULE_LABELS) == {p.value.split(".")[0] for p in Permission}
    assert [code for code, _, _ in migration.ROLES] == list(ROLES)
    for code, name, description in migration.ROLES:
        assert (name, description) == (ROLES[code].name, ROLES[code].description)
        assert set(migration.ROLE_PERMISSIONS[code]) == {p.value for p in ROLES[code].permissions}


def test_migration_creates_no_user_accounts() -> None:
    source = MIGRATION.read_text(encoding="utf-8").lower()
    assert "bulk_insert(users" not in source.replace(" ", "")
    assert "insert into core.users" not in source


# Principal ---------------------------------------------------------------------------


def test_principal_holds_exactly_its_permissions() -> None:
    viewer = as_user(P.CAR_VIEW)
    assert viewer.has(P.CAR_VIEW)
    assert not viewer.has(P.CAR_EDIT)
    assert viewer.has_any(P.CAR_EDIT, P.CAR_VIEW) and not viewer.has_all(P.CAR_EDIT, P.CAR_VIEW)
    assert viewer.actor_id == str(viewer.user_id)


def test_anonymous_holds_nothing_and_cannot_act() -> None:
    assert not ANONYMOUS.authenticated
    assert not ANONYMOUS.has(P.APP_VIEW)
    with pytest.raises(RuntimeError):
        _ = ANONYMOUS.actor_id


# Credentials -------------------------------------------------------------------------


def test_passwords_are_hashed_with_argon2id_and_verified() -> None:
    secret = "correct horse battery"  # noqa: S105 - test value
    hashed = credentials.hash_password(secret)
    assert hashed.startswith("$argon2id$")
    assert secret not in hashed
    assert credentials.verify_password(hashed, secret)
    assert not credentials.verify_password(hashed, secret + "!")


def test_missing_hash_never_verifies() -> None:
    assert not credentials.verify_password(None, "anything at all")
    assert not credentials.verify_password("not-a-hash", "anything at all")


@pytest.mark.parametrize(
    ("password", "accepted"),
    [
        ("short", False),
        ("aaaaaaaaaaaaaaaa", False),
        ("jsmith-is-my-password", False),
        ("x" * 257, False),
        ("tide pool lantern 7", True),
    ],
)
def test_password_policy(password: str, accepted: bool) -> None:
    if accepted:
        credentials.check_password_policy(password, email="jsmith@example.test")
    else:
        with pytest.raises(credentials.WeakPasswordError):
            credentials.check_password_policy(password, email="jsmith@example.test")


def test_tokens_are_random_and_stored_only_as_hashes() -> None:
    first, second = credentials.new_token(), credentials.new_token()
    assert first != second and len(first) >= 43
    assert credentials.token_hash(first) == credentials.token_hash(first)
    assert credentials.token_hash(first) != first.encode()


# Session cookie ----------------------------------------------------------------------


def test_session_cookie_is_host_only_secure_httponly_and_lax() -> None:
    settings = Settings(_env_file=None)
    response = Response()
    sessions.set_session_cookie(response, "token-value", settings)
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-op_session=token-value")
    lowered = cookie.lower()
    assert "httponly" in lowered and "secure" in lowered and "samesite=lax" in lowered
    assert "path=/" in lowered and "domain" not in lowered


def test_insecure_cookies_are_refused_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MOISTURE_DATA_SOURCE", "database")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:placeholder-pw@db/x")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    with pytest.raises(ValueError, match="SESSION_COOKIE_SECURE"):
        Settings(_env_file=None)


# Requests: 401, 403 and CSRF ---------------------------------------------------------


def test_requests_without_a_session_are_anonymous() -> None:
    with TestClient(create_app()) as client:
        response = client.get(COST_RECORDS)
    assert response.status_code == 401
    assert response.json()["detail"] == {
        "error": "authentication_required",
        "message": "Sign in to continue.",
    }


def test_an_unknown_session_without_a_database_is_anonymous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def not_configured() -> None:
        raise DatabaseNotConfiguredError

    monkeypatch.setattr(authorization, "get_sessionmaker", not_configured)
    with TestClient(create_app()) as client:
        response = client.get(COST_RECORDS, headers={"Cookie": "__Host-op_session=guess"})
    assert response.status_code == 401


def test_writes_with_a_session_need_the_application_header() -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            COST_RECORDS, json={}, headers={"Cookie": "__Host-op_session=anything"}
        )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "csrf_check_failed"


def test_sign_in_needs_the_application_header() -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/auth/sign-in", json={"email": "a@example.test", "password": "x" * 12}
        )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "csrf_check_failed"


def test_missing_permission_is_a_403_that_names_nobody() -> None:
    app = create_app()
    app.dependency_overrides[get_user_principal] = lambda: as_user(P.APP_VIEW)
    with TestClient(app) as client:
        response = client.get(COST_RECORDS)
    assert response.status_code == 403
    assert response.json()["detail"] == {
        "error": "permission_denied",
        "message": "You do not have permission to perform this action.",
    }


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/users",
        "/api/v1/admin/roles",
        "/api/v1/admin/permissions",
        "/api/v1/admin/audit",
    ],
)
def test_administration_needs_administration_permissions(path: str) -> None:
    module_admin = [p for p in Permission if not p.value.startswith(("users.", "roles.", "audit."))]
    app = create_app()
    app.dependency_overrides[get_user_principal] = lambda: as_user(*module_admin)
    with TestClient(app) as client:
        assert client.get(path).status_code == 403
    app.dependency_overrides[get_user_principal] = lambda: ANONYMOUS
    with TestClient(app) as client:
        assert client.get(path).status_code == 401


def test_my_assignments_needs_view_own() -> None:
    app = create_app()
    app.dependency_overrides[get_user_principal] = lambda: as_user(P.APP_VIEW, P.CAR_VIEW)
    with TestClient(app) as client:
        assert client.get("/api/v1/assignments/mine").status_code == 403
