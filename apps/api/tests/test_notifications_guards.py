"""Notifications platform guards that need no database: migration source and
registry parity, restricted templates, configuration safety, secrets in API
responses, the route permission matrix, the worker CLI, and static guards
(Resend is imported only by its adapter; the web app never sees email secrets).

The PostgreSQL behaviour (publisher, outbox, modes, SKIP LOCKED, audit) lives
in test_notifications_outbox_database.py."""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from principals import as_user
from pydantic import BaseModel, SecretStr

from app.auth.models import User
from app.auth.roles import ADMIN_CODE, STANDARD_ROLES
from app.auth.router import database
from app.core.authorization import ANONYMOUS, get_user_principal
from app.core.config import Settings, get_settings
from app.core.permissions import Permission
from app.db.base import Base
from app.main import create_app
from app.notifications import models as notification_models
from app.notifications import registry, schemas, service, templates, worker
from app.notifications.router import router as notifications_router

P = Permission
API_ROOT = Path(__file__).resolve().parents[1]
APP = API_ROOT / "app"
VERSIONS = API_ROOT / "alembic" / "versions"
REPO = API_ROOT.parents[1]
WEB = REPO / "apps" / "web"
PROVIDER = APP / "notifications" / "providers" / "resend.py"
BASE = "/api/v1/admin/notifications"

# Fixture-only secret. It must never appear in any response, log, row or audit event.
SECRET = "re_FIXTURE_notifications_secret_0123456789"  # noqa: S105

NOTIFICATION_PERMISSIONS = {p for p in Permission if p.value.startswith("notifications.")}


def _migration() -> ModuleType:
    path = next(VERSIONS.glob("*-0018_notifications_email_platform.py"))
    spec = importlib.util.spec_from_file_location("migration_0018_guard", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


# Migration 0018 (source; the schema itself is checked against PostgreSQL) -----------


def test_migration_follows_0017_and_creates_every_model_table() -> None:
    migration = _migration()
    assert (migration.revision, migration.down_revision) == ("0018", "0017")
    modeled = {
        table.name for table in Base.metadata.tables.values() if table.schema == "notifications"
    }
    assert modeled == set(migration.TABLES_CREATE_ORDER)
    assert migration.TABLES_DROP_ORDER == tuple(reversed(migration.TABLES_CREATE_ORDER))


def test_no_notification_table_stores_a_secret() -> None:
    forbidden = re.compile(r"api_?key|secret|password|token|credential", re.I)
    columns = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        if table.schema == "notifications"
        for column in table.columns
        if forbidden.search(column.name)
    ]
    assert columns == []
    source = next(VERSIONS.glob("*-0018_*.py")).read_text(encoding="utf-8")
    assert not re.search(r"api_?key|resend_api|secret|password", source, re.I)
    assert not re.search(r"\bre_[A-Za-z0-9]{16,}", source)


def test_migration_seeds_match_the_registry() -> None:
    migration = _migration()
    seeded = {code: (name, module, description, set(variables))
              for code, name, module, description, variables in migration.EVENT_TYPE_SEEDS}
    assert set(seeded) == set(registry.BY_CODE)
    for code, (name, module, description, variables) in seeded.items():
        event = registry.BY_CODE[code]
        assert (name, module, description) == (
            event.display_name,
            event.module_code,
            event.description,
        ), code
        assert variables == set(event.variables), code


def test_migration_ships_disabled_and_unpublished() -> None:
    source = next(VERSIONS.glob("*-0018_*.py")).read_text(encoding="utf-8")
    # The one seeded workflow is off and its template is only a draft.
    assert '"enabled": False' in source
    assert '"status": "draft"' in source
    assert '"status": "published"' not in source
    assert '"emergency_pause": False' in source
    # No business data is seeded.
    seeded = set(re.findall(r'sa\.table\(\s*"([a-z_]+)"', source))
    assert seeded == {
        "notification_event_types",
        "email_templates",
        "email_template_revisions",
        "notification_workflows",
        "workflow_recipient_rules",
        "notification_settings",
        "permissions",
    }
    assert "INSERT INTO core.users" not in source and "user_roles" not in source


def test_migration_permissions_and_grants_match_the_catalog_and_roles() -> None:
    migration = _migration()
    assert {Permission(code) for code in migration.PERMISSIONS} == NOTIFICATION_PERMISSIONS
    roles = {role.code: role for role in STANDARD_ROLES}
    for code, granted in migration.ROLE_GRANTS.items():
        assert {p.value for p in roles[code].permissions if p in NOTIFICATION_PERMISSIONS} == set(
            granted
        ), code
    # Roles the migration does not name hold no notifications permission.
    for code, role in roles.items():
        if code not in migration.ROLE_GRANTS:
            assert not role.permissions & NOTIFICATION_PERMISSIONS, code


def test_downgrade_refuses_to_discard_history() -> None:
    guard = _migration().DOWNGRADE_GUARD
    for table in ("notification_events", "email_deliveries", "notification_outbox"):
        assert f"FROM notifications.{table}" in guard
    assert guard.count("RAISE EXCEPTION") == 3


# Roles ---------------------------------------------------------------------------------


def test_only_admin_changes_email_configuration() -> None:
    roles = {role.code: role for role in STANDARD_ROLES}
    assert roles[ADMIN_CODE].permissions >= NOTIFICATION_PERMISSIONS
    readers = {P.NOTIFICATIONS_VIEW, P.NOTIFICATIONS_DELIVERY_VIEW}
    assert roles["SAFETY_ADMIN"].permissions & NOTIFICATION_PERMISSIONS == readers
    assert roles["PSM_ADMIN"].permissions & NOTIFICATION_PERMISSIONS == readers
    changers = NOTIFICATION_PERMISSIONS - readers
    for code, role in roles.items():
        if code != ADMIN_CODE:
            assert not role.permissions & changers, code


# Registry ------------------------------------------------------------------------------


def test_registry_codes_are_stable_unique_and_well_formed() -> None:
    codes = [event.code for event in registry.EVENT_TYPES]
    assert len(codes) == len(set(codes))
    for event in registry.EVENT_TYPES:
        assert re.fullmatch(r"[a-z][a-z0-9_.]{1,99}", event.code)
        assert set(registry.COMMON_VARIABLES) <= set(event.variables), event.code
        assert len(event.variables) == len(set(event.variables)), event.code
    assert "notifications.test" in registry.BY_CODE
    assert registry.allowed_variables("no.such.event") == frozenset(registry.COMMON_VARIABLES)


def test_psm_legacy_events_map_to_registered_psm_codes() -> None:
    assert set(registry.PSM_LEGACY_TO_CODE.values()) <= set(registry.BY_CODE)
    assert all(code.startswith("psm.") for code in registry.PSM_LEGACY_TO_CODE.values())
    assert len(set(registry.PSM_LEGACY_TO_CODE.values())) == len(registry.PSM_LEGACY_TO_CODE)
    # Comments and generic status changes stay on the legacy path only.
    assert "comment_added" not in registry.PSM_LEGACY_TO_CODE
    assert "status_changed" not in registry.PSM_LEGACY_TO_CODE


# Restricted templates ------------------------------------------------------------------


def test_templates_accept_only_registered_placeholders() -> None:
    result = templates.validate_templates(
        event_type_code="psm.action.assigned",
        subject="{{action.reference}} for {{recipient.name}}",
        html="<p>{{ action.title }} {{incident.reference}}</p>",
        text="{{action.status}}",
    )
    assert result.unsupported_variables == ("incident.reference",)
    assert not result.valid


def test_templates_report_missing_subject_and_body() -> None:
    result = templates.validate_templates(
        event_type_code="psm.action.assigned", subject="  ", html="", text=""
    )
    assert set(result.missing_required) == {"subject", "body"}
    assert not result.valid


@pytest.mark.parametrize(
    "html",
    [
        "<p>x</p><script>alert(1)</script>",
        '<a href="javascript:alert(1)">x</a>',
        '<p onclick="steal()">x</p>',
    ],
)
def test_templates_flag_unsafe_html(html: str) -> None:
    result = templates.validate_templates(
        event_type_code="psm.action.assigned", subject="s", html=html, text="t"
    )
    assert result.unsafe_content_findings
    assert not result.valid


def test_sanitizer_keeps_formatting_and_drops_active_content() -> None:
    cleaned = templates.sanitize_html(
        '<p style="color:red">Hi <b>there</b></p><img src="x" onerror="x()">'
        '<a href="https://ops.example.test/a" onclick="x()">open</a>'
        '<a href="javascript:alert(1)">bad</a><iframe src="https://evil.test"></iframe>'
    )
    assert "<b>there</b>" in cleaned and 'href="https://ops.example.test/a"' in cleaned
    for forbidden in ("<img", "onerror", "onclick", "javascript:", "<iframe"):
        assert forbidden not in cleaned


def test_rendering_substitutes_only_dotted_lookups() -> None:
    context = {"action": {"title": "Fix <valve>", "due": None}, "n": 3}
    assert templates.render("{{action.title}}|{{ action.due }}|{{n}}", context) == (
        "Fix <valve>||3"
    )
    # Anything that is not a plain variable path is left untouched, never evaluated.
    assert templates.render("{{7*7}} {% if x %}y{% endif %}", context) == (
        "{{7*7}} {% if x %}y{% endif %}"
    )


@pytest.mark.parametrize("path", ["action.nope", "action.title.__class__", "missing"])
def test_rendering_refuses_unknown_paths_and_attribute_traversal(path: str) -> None:
    with pytest.raises(KeyError):
        templates.render("{{" + path + "}}", {"action": {"title": "x"}})


def test_rendered_email_html_is_sanitized_after_substitution() -> None:
    subject, html, text = templates.render_email(
        subject_template="{{action.title}}",
        html_template="<p>{{action.title}}</p>",
        text_template="",
        context={"action": {"title": "<script>alert(1)</script>Valve"}},
    )
    assert "<script" not in html.lower()
    assert subject == "<script>alert(1)</script>Valve"  # a subject is plain text
    assert "Valve" in text and "<p>" not in text


# Configuration -------------------------------------------------------------------------


def test_email_is_off_by_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.email_provider == "none" and settings.email_enabled is False
    assert settings.email_delivery_mode == "disabled"
    assert settings.resend_api_key is None and not settings.resend_configured
    assert not settings.email_live_ready and not settings.email_redirect_ready


@pytest.mark.parametrize("value", ["", "  ", "LIVE!", "sandbox", "true", "1"])
def test_unrecognized_delivery_modes_are_disabled_never_live(value: str) -> None:
    assert Settings(_env_file=None, email_delivery_mode=value).email_delivery_mode == "disabled"


def test_delivery_mode_is_case_and_space_insensitive() -> None:
    assert Settings(_env_file=None, email_delivery_mode=" Redirect ").email_delivery_mode == (
        "redirect"
    )


def test_environment_variables_configure_email(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "EMAIL_ENABLED": "true",
        "EMAIL_PROVIDER": "resend",
        "EMAIL_DELIVERY_MODE": "redirect",
        "EMAIL_REDIRECT_TO": "sink@fixture.test",
        "EMAIL_FROM_ADDRESS": "from@fixture.test",
        "EMAIL_OUTBOX_MAX_ATTEMPTS": "3",
        "RESEND_API_KEY": SECRET,
    }.items():
        monkeypatch.setenv(name, value)
    settings = Settings(_env_file=None)
    assert settings.email_redirect_ready and not settings.email_live_ready
    assert settings.email_outbox_max_attempts == 3
    assert settings.resend_api_key is not None
    assert settings.resend_api_key.get_secret_value() == SECRET


@pytest.mark.parametrize(
    ("missing", "mode"),
    [
        ("email_enabled", "live"),
        ("email_provider", "live"),
        ("resend_api_key", "live"),
        ("email_from_address", "live"),
        ("email_enabled", "redirect"),
        ("email_provider", "redirect"),
        ("resend_api_key", "redirect"),
        ("email_from_address", "redirect"),
        ("email_redirect_to", "redirect"),
    ],
)
def test_a_mode_is_ready_only_with_every_required_setting(missing: str, mode: str) -> None:
    complete: dict[str, Any] = {
        "email_enabled": True,
        "email_provider": "resend",
        "email_delivery_mode": mode,
        "resend_api_key": SecretStr(SECRET),
        "email_from_address": "from@fixture.test",
        "email_redirect_to": "sink@fixture.test",
    }
    settings = Settings(_env_file=None, **complete)
    assert settings.email_live_ready or settings.email_redirect_ready
    del complete[missing]
    settings = Settings(_env_file=None, **complete)
    assert not (settings.email_live_ready or settings.email_redirect_ready)


def test_a_blank_key_is_no_key() -> None:
    assert not Settings(_env_file=None, resend_api_key="").resend_configured
    assert not Settings(_env_file=None, resend_api_key=SecretStr("   ")).resend_configured


def test_the_key_never_appears_in_settings_representations() -> None:
    settings = Settings(_env_file=None, resend_api_key=SecretStr(SECRET), email_enabled=True)
    for rendered in (repr(settings), str(settings), settings.model_dump_json()):
        assert SECRET not in rendered


def test_a_validation_error_does_not_echo_the_key() -> None:
    with pytest.raises(ValueError) as caught:
        Settings(_env_file=None, resend_api_key=SecretStr(SECRET), email_outbox_max_attempts=0)
    assert SECRET not in str(caught.value)


# Secrets in API responses --------------------------------------------------------------


def test_notification_schemas_have_no_secret_fields() -> None:
    names: list[str] = []
    for model in vars(schemas).values():
        if isinstance(model, type) and issubclass(model, BaseModel) and model is not BaseModel:
            for name, field in model.model_fields.items():
                names += [name, field.alias or name]
    offenders = {
        name
        for name in names
        if re.search(r"secret|password|token|credential|api_?key", name, re.I)
    }
    # The one allowed mention reports only whether a key is set.
    assert offenders <= {"api_key_configured", "apiKeyConfigured"}
    assert schemas.SettingsOut.model_fields["api_key_configured"].annotation is bool
    assert schemas.OverviewOut.model_fields["api_key_configured"].annotation is bool


def test_settings_response_reports_configured_without_the_key() -> None:
    session = SimpleNamespace(get=lambda *_: SimpleNamespace(emergency_pause=False))
    settings = Settings(
        _env_file=None,
        resend_api_key=SecretStr(SECRET),
        email_enabled=True,
        email_provider="resend",
        email_from_address="from@fixture.test",
    )
    body = service.get_settings(session, settings)  # type: ignore[arg-type]
    payload = body.model_dump_json(by_alias=True)
    assert SECRET not in payload and "RESEND_API_KEY" not in payload
    assert json.loads(payload)["apiKeyConfigured"] is True
    unset = service.get_settings(session, Settings(_env_file=None))  # type: ignore[arg-type]
    assert unset.api_key_configured is False


def test_readiness_does_not_leak_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, resend_api_key=SecretStr(SECRET))
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        for path in ("/api/v1/health", "/api/v1/health/ready"):
            response = client.get(path)
            assert SECRET not in response.text and "RESEND_API_KEY" not in response.text


def test_permission_errors_do_not_name_the_key_or_the_user() -> None:
    app = create_app()
    app.dependency_overrides[database] = lambda: object()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, resend_api_key=SecretStr(SECRET)
    )
    app.dependency_overrides[get_user_principal] = lambda: as_user(P.APP_VIEW)
    with TestClient(app) as client:
        response = client.get(f"{BASE}/settings")
    assert response.status_code == 403
    assert response.json()["detail"] == {
        "error": "permission_denied",
        "message": "You do not have permission to perform this action.",
    }
    assert SECRET not in response.text


# Permission matrix ---------------------------------------------------------------------

ID = "00000000-0000-4000-8000-0000000000aa"
ROUTES: list[tuple[str, str, Permission, dict[str, Any] | None]] = [
    ("GET", "/overview", P.NOTIFICATIONS_VIEW, None),
    ("GET", "/event-types", P.NOTIFICATIONS_VIEW, None),
    ("GET", "/templates", P.NOTIFICATIONS_VIEW, None),
    ("GET", "/templates/{template_id}", P.NOTIFICATIONS_VIEW, None),
    ("GET", "/templates/{template_id}/revisions/{revision_id}", P.NOTIFICATIONS_VIEW, None),
    ("POST", "/templates/{template_id}/draft", P.NOTIFICATIONS_TEMPLATES_MANAGE, None),
    (
        "PATCH",
        "/templates/{template_id}/revisions/{revision_id}",
        P.NOTIFICATIONS_TEMPLATES_MANAGE,
        {"subjectTemplate": "s"},
    ),
    (
        "POST",
        "/templates/{template_id}/revisions/{revision_id}/validate",
        P.NOTIFICATIONS_VIEW,
        {"eventTypeCode": "psm.action.assigned"},
    ),
    (
        "POST",
        "/templates/{template_id}/revisions/{revision_id}/preview",
        P.NOTIFICATIONS_VIEW,
        {"eventTypeCode": "psm.action.assigned"},
    ),
    (
        "POST",
        "/templates/{template_id}/revisions/{revision_id}/publish",
        P.NOTIFICATIONS_TEMPLATES_MANAGE,
        {"eventTypeCode": "psm.action.assigned"},
    ),
    ("GET", "/workflows", P.NOTIFICATIONS_VIEW, None),
    ("GET", "/workflows/{workflow_id}", P.NOTIFICATIONS_VIEW, None),
    ("PATCH", "/workflows/{workflow_id}", P.NOTIFICATIONS_WORKFLOWS_MANAGE, {"enabled": False}),
    ("GET", "/deliveries", P.NOTIFICATIONS_DELIVERY_VIEW, None),
    ("GET", "/deliveries/{delivery_id}", P.NOTIFICATIONS_DELIVERY_VIEW, None),
    ("POST", "/deliveries/{delivery_id}/retry", P.NOTIFICATIONS_DELIVERY_RETRY, None),
    ("GET", "/test/psm-actions", P.NOTIFICATIONS_TEST_SEND, None),
    ("POST", "/test/preview", P.NOTIFICATIONS_TEST_SEND, {"templateId": 1}),
    (
        "POST",
        "/test/send",
        P.NOTIFICATIONS_TEST_SEND,
        {"templateId": 1, "toEmail": "someone@fixture.test"},
    ),
    ("GET", "/settings", P.NOTIFICATIONS_VIEW, None),
    ("PATCH", "/settings", P.NOTIFICATIONS_SETTINGS_MANAGE, {"emergencyPause": True}),
]


def _url(template: str) -> str:
    return BASE + template.format(
        template_id=1, revision_id=1, workflow_id=1, delivery_id=ID
    )


def _api(principal: Any) -> TestClient:
    app = create_app()
    # No database: authorization is decided before any handler touches the session.
    app.dependency_overrides[database] = lambda: object()
    app.dependency_overrides[get_user_principal] = lambda: principal
    return TestClient(app)


def test_the_matrix_covers_every_notifications_route() -> None:
    declared = {
        (method, route.path.removeprefix("/admin/notifications"))
        for route in notifications_router.routes
        for method in route.methods  # type: ignore[attr-defined]
    }
    assert declared == {(method, path) for method, path, _, _ in ROUTES}


@pytest.mark.parametrize(("method", "path", "permission", "body"), ROUTES)
def test_each_route_refuses_everyone_without_its_permission(
    method: str, path: str, permission: Permission, body: dict[str, Any] | None
) -> None:
    everything_else = [p for p in Permission if p != permission]
    with _api(as_user(*everything_else)) as client:
        denied = client.request(method, _url(path), json=body)
    assert denied.status_code == 403, (method, path)
    assert denied.json()["detail"]["error"] == "permission_denied"
    with _api(ANONYMOUS) as client:
        assert client.request(method, _url(path), json=body).status_code == 401


@pytest.mark.parametrize("permission", sorted(NOTIFICATION_PERMISSIONS, key=lambda p: p.value))
def test_one_notifications_permission_never_unlocks_another_area(permission: Permission) -> None:
    others = [r for r in ROUTES if r[2] != permission]
    assert others
    with _api(as_user(P.APP_VIEW, permission)) as client:
        for method, path, _, body in others:
            assert client.request(method, _url(path), json=body).status_code == 403, (
                permission,
                method,
                path,
            )


def test_other_modules_permissions_do_not_open_notifications() -> None:
    unrelated = [p for p in Permission if p not in NOTIFICATION_PERMISSIONS]
    with _api(as_user(*unrelated)) as client:
        for method, path, _, body in ROUTES:
            assert client.request(method, _url(path), json=body).status_code == 403


# Worker CLI ----------------------------------------------------------------------------


def test_worker_process_command_passes_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []
    monkeypatch.setattr(worker, "process", lambda limit: seen.append(limit) or 0)
    monkeypatch.setattr(worker, "get_settings", lambda: Settings(_env_file=None))
    assert worker.main(["process"]) == 0
    assert worker.main(["process", "--limit", "3"]) == 0
    assert seen == [20, 3]


def test_worker_needs_a_command() -> None:
    with pytest.raises(SystemExit) as caught:
        worker.main([])
    assert caught.value.code == 2
    with pytest.raises(SystemExit):
        worker.main(["deliver-everything"])


def test_worker_refuses_to_run_without_a_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(worker, "get_settings", lambda: Settings(_env_file=None))
    assert worker.process(5) == 2
    assert "DATABASE_URL is not set" in capsys.readouterr().err


# Static guards -------------------------------------------------------------------------


def test_only_the_adapter_talks_to_resend() -> None:
    offenders: list[str] = []
    for path in _python_files(APP):
        if path == PROVIDER:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(name == "resend" or name.startswith("resend.") for name in names):
                offenders.append(f"{path.relative_to(APP)}: imports resend")
        if re.search(r"api\.resend\.com|RESEND_URL", source):
            offenders.append(f"{path.relative_to(APP)}: names the Resend API")
    assert offenders == []


def test_only_the_adapter_makes_http_calls_in_notifications() -> None:
    http = re.compile(r"urllib\.request|import requests|import httpx|http\.client|aiohttp")
    offenders = [
        str(path.relative_to(APP))
        for path in _python_files(APP / "notifications")
        if path != PROVIDER and http.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_only_configuration_and_the_adapter_read_the_key() -> None:
    allowed = {PROVIDER, APP / "core" / "config.py"}
    offenders = [
        str(path.relative_to(APP))
        for path in _python_files(APP)
        if path not in allowed
        and re.search(r"resend_api_key|RESEND_API_KEY", path.read_text(encoding="utf-8"))
        # The models' docstring says the key is never stored; that is documentation.
        and path != APP / "notifications" / "models.py"
    ]
    assert offenders == []
    # The raw secret is unwrapped in the adapter and in the SMTP mailer only.
    unwrapped = {
        path
        for path in _python_files(APP)
        if "get_secret_value" in path.read_text(encoding="utf-8")
    }
    assert {p.relative_to(APP).as_posix() for p in unwrapped} == {
        "core/config.py",
        "core/mail.py",
        "db/session.py",
        "notifications/providers/resend.py",
    }


def test_business_modules_publish_events_but_never_use_providers_or_the_outbox() -> None:
    forbidden = (
        "app.notifications.providers",
        "app.notifications.outbox",
        "app.notifications.service",
        "app.notifications.worker",
    )
    offenders: list[str] = []
    for path in _python_files(APP):
        if (APP / "notifications") in path.parents or path == APP / "api" / "v1" / "health.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            offenders += [
                f"{path.relative_to(APP)}: {module}"
                for module in modules
                if module.startswith(forbidden)
            ]
    assert offenders == []


def test_the_notifications_package_never_logs_secrets_or_message_content() -> None:
    sensitive = {
        "resend_api_key",
        "get_secret_value",
        "settings",
        "key",
        "request",
        "body",
        "html",
        "text",
        "text_body",
        "send_html",
        "send_text",
        "rendered_html",
        "rendered_text",
        "subject",
        "headers",
    }
    methods = {"debug", "info", "warning", "error", "exception", "critical"}
    offenders: list[str] = []
    scanned = 0
    for path in _python_files(APP / "notifications"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in methods
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"logger", "logging", "log"}
            ):
                continue
            scanned += 1
            used = {
                n.id if isinstance(n, ast.Name) else n.attr
                for arg in [*node.args, *(k.value for k in node.keywords)]
                for n in ast.walk(arg)
                if isinstance(n, ast.Name | ast.Attribute)
            }
            if used & sensitive:
                offenders.append(f"{path.relative_to(APP)}:{node.lineno}: {sorted(used & sensitive)}")
    assert scanned >= 3  # the adapter and the worker do log; this is not a vacuous scan
    assert offenders == []


def _web_sources() -> list[Path]:
    skipped = {"node_modules", ".next", "coverage", ".turbo"}
    return sorted(
        p
        for p in WEB.rglob("*")
        if p.is_file()
        and not skipped & set(p.relative_to(WEB).parts)
        and p.suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".css", ".md"}
        and ".test." not in p.name
        and p.name != "package-lock.json"
    )


def test_web_app_never_references_email_secrets_or_public_email_variables() -> None:
    assert _web_sources()
    pattern = re.compile(r"RESEND|(NEXT_PUBLIC|VITE)_\w*(EMAIL|RESEND|API_KEY)", re.I)
    hits = [
        str(path.relative_to(WEB))
        for path in _web_sources()
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert hits == []


def test_web_environment_files_and_dependencies_carry_no_email_configuration() -> None:
    package = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    dependencies = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
    assert not [name for name in dependencies if "resend" in name.lower()]
    for path in WEB.glob(".env*"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not re.search(r"RESEND|EMAIL_|NEXT_PUBLIC_|VITE_", text), path.name


def test_compose_gives_the_web_service_no_email_settings() -> None:
    lines = (REPO / "compose.yml").read_text(encoding="utf-8").splitlines()
    blocks: dict[str, list[str]] = {}
    current = ""
    in_services = False
    for line in lines:
        if line.startswith("services:"):
            in_services = True
        elif in_services and re.match(r"^  [A-Za-z0-9_-]+:\s*$", line):
            current = line.strip().rstrip(":")
            blocks[current] = []
        elif in_services and current:
            blocks[current].append(line)
    assert "api" in blocks and "web" in blocks
    assert not re.search(r"RESEND|EMAIL_", "\n".join(blocks["web"]))
    api = "\n".join(blocks["api"])
    assert "EMAIL_ENABLED: ${EMAIL_ENABLED:-false}" in api
    assert "EMAIL_DELIVERY_MODE: ${EMAIL_DELIVERY_MODE:-disabled}" in api
    assert "EMAIL_PROVIDER: ${EMAIL_PROVIDER:-none}" in api
    assert re.search(r"RESEND_API_KEY: \$\{RESEND_API_KEY:-\}", api)


def test_env_example_documents_every_email_setting_with_safe_defaults() -> None:
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    values = {
        match.group(1): match.group(2).strip()
        for match in re.finditer(r"^([A-Z][A-Z0-9_]*)=(.*)$", example, re.M)
    }
    compose = (REPO / "compose.yml").read_text(encoding="utf-8")
    fields = [name for name in Settings.model_fields if name.startswith(("email_", "resend_"))]
    assert fields
    for field in fields:
        variable = field.upper()
        assert variable in values, f"{variable} is not documented in .env.example"
        assert f"{variable}:" in compose, f"{variable} is not passed to the API container"
    # Nothing is live by default and no key is committed.
    assert values["EMAIL_ENABLED"] == "false"
    assert values["EMAIL_DELIVERY_MODE"] == "disabled"
    assert values["EMAIL_PROVIDER"] == "none"
    assert values["RESEND_API_KEY"] == ""
    assert not re.search(r"^(NEXT_PUBLIC|VITE)_.*(EMAIL|RESEND)", example, re.M)


def test_no_real_looking_resend_key_is_committed_in_configuration_or_docs() -> None:
    key = re.compile(r"\bre_[A-Za-z0-9]{20,}\b")
    for path in (REPO / ".env.example", REPO / "compose.yml", REPO / "README.md"):
        assert not key.search(path.read_text(encoding="utf-8")), path.name


def test_user_model_is_not_a_notification_secret_store() -> None:
    # Recipients resolve from users; the table that holds them has no mail credentials.
    assert not [c.name for c in User.__table__.columns if re.search("resend|smtp", c.name)]
    assert notification_models.NotificationSettings.__table__.columns.keys() == [
        "id",
        "emergency_pause",
        "updated_at",
        "updated_by",
    ]
