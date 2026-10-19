"""Unit and static-guard tests for the shared Notifications platform (no DB)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.notifications.providers.base import EmailMessage
from app.notifications.providers.resend import ResendEmailProvider
from app.notifications.templates import extract_variables, sanitize_html, validate_templates

API_ROOT = Path(__file__).resolve().parents[1] / "app"
WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_email_delivery_mode_invalid_becomes_disabled() -> None:
    settings = Settings(_env_file=None, email_delivery_mode="bogus")  # type: ignore[arg-type]
    assert settings.email_delivery_mode == "disabled"


def test_live_ready_requires_full_config() -> None:
    partial = Settings(
        _env_file=None,
        email_enabled=True,
        email_delivery_mode="live",
        email_provider="resend",
        resend_api_key=SecretStr("re_test"),
    )
    assert not partial.email_live_ready
    ready = Settings(
        _env_file=None,
        email_enabled=True,
        email_delivery_mode="live",
        email_provider="resend",
        resend_api_key=SecretStr("re_test"),
        email_from_address="noreply@example.com",
    )
    assert ready.email_live_ready


def test_template_variable_extraction_and_validation() -> None:
    assert extract_variables("Hello {{action.title}} and {{ action.url }}") == [
        "action.title",
        "action.url",
    ]
    result = validate_templates(
        event_type_code="psm.action.assigned",
        subject="{{action.title}}",
        html="<p>{{action.reference}}</p><script>alert(1)</script>",
        text="{{unknown.var}}",
    )
    assert "unknown.var" in result.unsupported_variables
    assert result.unsafe_content_findings
    assert result.valid is False


def test_sanitize_html_strips_script() -> None:
    cleaned = sanitize_html(
        '<p>Hi</p><script>alert("x")</script><a href="javascript:alert(1)">x</a>'
    )
    assert "<script>" not in cleaned.lower()
    assert "javascript:" not in cleaned.lower()


def test_resend_provider_not_configured() -> None:
    provider = ResendEmailProvider(Settings(_env_file=None, email_provider="resend"))
    result = provider.send(
        EmailMessage(
            from_email="from@example.com",
            from_name="Ops",
            to=("a@example.com",),
            subject="s",
            html="<p>h</p>",
            text="h",
        )
    )
    assert result.accepted is False
    assert result.provider_error_code == "not_configured"


def test_resend_provider_accepts_mocked_http(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status = 200

        def read(self) -> bytes:
            return b'{"id":"msg_123"}'

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        "app.notifications.providers.resend.urllib.request.urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )
    settings = Settings(
        _env_file=None,
        email_provider="resend",
        resend_api_key=SecretStr("re_secret_key_value"),
        email_from_address="from@example.com",
    )
    result = ResendEmailProvider(settings).send(
        EmailMessage(
            from_email="from@example.com",
            from_name=None,
            to=("a@example.com",),
            subject="Hello",
            html="<p>Hi</p>",
            text="Hi",
        )
    )
    assert result.accepted is True
    assert result.provider_message_id == "msg_123"
    assert "re_secret" not in str(result.sanitized_response)
    assert "re_secret" not in (result.error_message or "")


def test_resend_import_only_in_provider_module() -> None:
    allowed = {API_ROOT / "notifications" / "providers" / "resend.py"}
    offenders: list[str] = []
    for path in API_ROOT.rglob("*.py"):
        if path in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        if "import resend" in source or "from resend" in source:
            offenders.append(str(path.relative_to(API_ROOT)))
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "resend" or alias.name.startswith("resend."):
                        offenders.append(str(path.relative_to(API_ROOT)))
            if isinstance(node, ast.ImportFrom) and node.module and (
                node.module == "resend" or node.module.startswith("resend.")
            ):
                offenders.append(str(path.relative_to(API_ROOT)))
    assert offenders == []


def test_web_env_has_no_resend_or_public_email_secrets() -> None:
    forbidden = ("RESEND", "NEXT_PUBLIC_RESEND", "VITE_RESEND", "NEXT_PUBLIC_EMAIL", "VITE_EMAIL")
    hits: list[str] = []
    for path in [
        *WEB_ROOT.rglob(".env*"),
        WEB_ROOT / "next.config.ts",
        WEB_ROOT / "next.config.mjs",
        WEB_ROOT / "next.config.js",
    ]:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            if token in text:
                hits.append(f"{path}: {token}")
    example = REPO_ROOT / ".env.example"
    text = example.read_text(encoding="utf-8")
    assert "RESEND_API_KEY" in text
    assert "NEXT_PUBLIC" not in text or "NEXT_PUBLIC_RESEND" not in text
    assert "VITE_RESEND" not in text
    assert hits == []


def test_settings_repr_hides_resend_key() -> None:
    settings = Settings(_env_file=None, resend_api_key=SecretStr("re_super_secret"))
    rendered = repr(settings)
    assert "re_super_secret" not in rendered
