"""The Resend adapter and delivery-mode rules, with no real network and no database.

Every test here runs with the socket layer blocked, so a test that forgot to mock
``urlopen`` fails instead of contacting Resend."""

from __future__ import annotations

import io
import json
import logging
import socket
import urllib.error
from collections.abc import Callable, Iterator
from dataclasses import FrozenInstanceError
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.notifications import outbox, service
from app.notifications.providers import resend as resend_module
from app.notifications.providers.base import EmailMessage, ProviderSendResult
from app.notifications.providers.resend import RESEND_URL, ResendEmailProvider

# Fixture-only secret; it must not appear in any result, log record or exception.
KEY = "re_PROVIDER_fixture_key_9f8e7d6c5b4a"  # noqa: S105
OWNER = "owner@fixture.test"
REDIRECT = "sink@fixture.test"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    yield


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "email_enabled": True,
        "email_provider": "resend",
        "resend_api_key": SecretStr(KEY),
        "email_from_address": "noreply@fixture.test",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _message(**overrides: Any) -> EmailMessage:
    values: dict[str, Any] = {
        "from_email": "noreply@fixture.test",
        "from_name": "Operations Platform",
        "to": (OWNER,),
        "subject": "Subject",
        "html": "<p>Hello</p>",
        "text": "Hello",
    }
    values.update(overrides)
    return EmailMessage(**values)


class Response:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class Transport:
    """A stand-in for ``urllib.request.urlopen`` that records what was sent."""

    def __init__(self, behaviour: Callable[[], Response]) -> None:
        self.behaviour = behaviour
        self.requests: list[Any] = []
        self.timeouts: list[float | None] = []

    def __call__(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        self.requests.append(request)
        self.timeouts.append(kwargs.get("timeout"))
        return self.behaviour()

    @property
    def body(self) -> dict[str, Any]:
        return json.loads(self.requests[-1].data.decode("utf-8"))


def _install(monkeypatch: pytest.MonkeyPatch, behaviour: Callable[[], Response]) -> Transport:
    transport = Transport(behaviour)
    monkeypatch.setattr(resend_module.urllib.request, "urlopen", transport)
    return transport


def _http_error(code: int, body: bytes) -> Callable[[], Response]:
    def raise_error() -> Response:
        raise urllib.error.HTTPError(RESEND_URL, code, "error", {}, io.BytesIO(body))  # type: ignore[arg-type]

    return raise_error


def _send(settings: Settings | None = None, **message: Any) -> ProviderSendResult:
    return ResendEmailProvider(settings or _settings()).send(_message(**message))


# Request ---------------------------------------------------------------------------------


def test_a_send_posts_json_to_resend_with_a_bearer_key(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _install(monkeypatch, lambda: Response(200, b'{"id":"msg_1"}'))

    result = _send(cc=("cc@fixture.test",), bcc=("bcc@fixture.test",), reply_to="help@fixture.test")

    assert result.accepted and result.provider_message_id == "msg_1"
    (request,) = transport.requests
    assert request.full_url == RESEND_URL == "https://api.resend.com/emails"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == f"Bearer {KEY}"
    assert request.get_header("Content-type") == "application/json"
    assert transport.timeouts == [resend_module.TIMEOUT_SECONDS]
    assert transport.body == {
        "from": "Operations Platform <noreply@fixture.test>",
        "to": [OWNER],
        "cc": ["cc@fixture.test"],
        "bcc": ["bcc@fixture.test"],
        "reply_to": "help@fixture.test",
        "subject": "Subject",
        "html": "<p>Hello</p>",
        "text": "Hello",
    }


def test_optional_fields_are_left_out_and_the_key_stays_out_of_the_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _install(monkeypatch, lambda: Response(200, b'{"id":"msg_2"}'))

    _send(from_name=None)

    assert transport.body["from"] == "noreply@fixture.test"
    assert not {"cc", "bcc", "reply_to", "headers"} & set(transport.body)
    assert KEY not in json.dumps(transport.body)


def test_a_custom_timeout_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _install(monkeypatch, lambda: Response(200, b'{"id":"m"}'))
    ResendEmailProvider(_settings(), timeout=3).send(_message())
    assert transport.timeouts == [3]


@pytest.mark.parametrize("key", [None, SecretStr(""), SecretStr("   ")])
def test_without_a_key_nothing_is_sent(monkeypatch: pytest.MonkeyPatch, key: SecretStr | None) -> None:
    transport = _install(monkeypatch, lambda: pytest.fail("the provider must not be contacted"))

    result = _send(_settings(resend_api_key=key))

    assert transport.requests == []
    assert (result.accepted, result.retryable) == (False, False)
    assert result.provider_error_code == "not_configured"
    assert result.http_status is None and result.provider_message_id is None


# Outcomes ---------------------------------------------------------------------------------


def test_an_accepted_response_is_sanitized_to_a_short_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"id": "msg_9", "extra": {"nested": KEY}, "to": [OWNER], "html": "<p>x</p>"}
    _install(monkeypatch, lambda: Response(200, json.dumps(body).encode()))

    result = _send()

    assert result.accepted and result.http_status == 200
    assert result.provider_status == "accepted" and result.error_message is None
    assert result.sanitized_response == {"id": "msg_9"}


@pytest.mark.parametrize("payload", [b"{}", b'{"id": ""}', b'{"id": 5}', b'{"message":"no id"}'])
def test_a_2xx_without_a_message_id_is_not_an_acceptance(
    monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    _install(monkeypatch, lambda: Response(200, payload))
    result = _send()
    assert not result.accepted and result.provider_message_id is None


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(400, False), (401, False), (403, False), (404, False), (422, False)]
    + [(429, True), (500, True), (502, True), (503, True)],
)
def test_http_errors_are_classified_for_retry(
    monkeypatch: pytest.MonkeyPatch, status: int, retryable: bool
) -> None:
    body = json.dumps({"name": "some_error", "message": "Provider said no."}).encode()
    _install(monkeypatch, _http_error(status, body))

    result = _send()

    assert result.accepted is False and result.provider_message_id is None
    assert result.http_status == status and result.retryable is retryable
    assert result.provider_status == "error"
    assert result.sanitized_response["name"] == "some_error"


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_failures_are_generic_and_never_echo_the_key(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    body = json.dumps({"name": "restricted_api_key", "message": f"API key {KEY} is invalid"})
    _install(monkeypatch, _http_error(status, body.encode()))

    result = _send()

    assert result.error_message == "The email provider refused authentication."
    assert result.retryable is False
    assert result.provider_error_code == "restricted_api_key"


def test_a_validation_error_keeps_the_providers_code_and_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps({"name": "validation_error", "message": "Invalid `to` field."})
    _install(monkeypatch, _http_error(422, body.encode()))
    result = _send()
    assert (result.provider_error_code, result.error_message) == (
        "validation_error",
        "Invalid `to` field.",
    )


def test_an_unreadable_error_body_gets_a_generic_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _http_error(500, b"<html>gateway exploded</html>"))
    result = _send()
    assert result.error_message == "The email provider returned an unreadable error."
    assert result.retryable is True and result.http_status == 500


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError(f"connection refused for {KEY}"),
        TimeoutError(f"timed out talking with {KEY}"),
        ConnectionResetError(f"reset by peer {KEY}"),
    ],
)
def test_connection_problems_are_retryable_and_hide_the_exception_text(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def fail() -> Response:
        raise error

    _install(monkeypatch, fail)

    result = _send()

    assert not result.accepted and result.retryable is True
    assert result.http_status is None
    assert result.provider_error_code == "timeout_or_connection"
    assert result.error_message == "The email provider could not be reached."
    assert result.sanitized_response == {"error_type": type(error).__name__}
    assert KEY not in repr(result)


def test_no_result_or_log_record_contains_the_key_or_the_message_content(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    results = []
    for behaviour in (
        _http_error(401, json.dumps({"name": "x", "message": KEY}).encode()),
        _http_error(429, b'{"name":"rate_limit_exceeded"}'),
        _http_error(500, b"not json"),
        lambda: (_ for _ in ()).throw(urllib.error.URLError(KEY)),
        lambda: Response(200, b'{"id":"msg_ok"}'),
    ):
        _install(monkeypatch, behaviour)
        results.append(_send(subject="PRIVATE-SUBJECT", html="<p>PRIVATE-BODY</p>", text="PRIVATE-BODY"))

    assert len(results) == 5
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert logged  # the adapter does log failures
    for blob in (logged, *map(repr, results)):
        assert KEY not in blob
        assert "PRIVATE-BODY" not in blob and "PRIVATE-SUBJECT" not in blob
        assert OWNER not in blob


def test_the_key_never_leaks_through_repr_of_provider_or_settings() -> None:
    provider = ResendEmailProvider(_settings())
    assert KEY not in repr(provider) and KEY not in repr(provider._settings)


def test_messages_and_results_are_immutable_values() -> None:
    message = _message()
    with pytest.raises(FrozenInstanceError):
        message.subject = "changed"  # type: ignore[misc]
    result = ProviderSendResult(False, None, None, None, None, False, {})
    with pytest.raises(FrozenInstanceError):
        result.accepted = True  # type: ignore[misc]
    assert resend_module.ResendEmailProvider.code == "resend"


def test_the_socket_guard_is_active() -> None:
    with pytest.raises(AssertionError, match="network"):
        socket.create_connection(("api.resend.com", 443))


# Delivery modes ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "is_test", "expected"),
    [
        # Disabled in every way that matters.
        ({"email_enabled": False}, False, "disabled"),
        ({"email_enabled": False, "email_delivery_mode": "live"}, False, "disabled"),
        ({"email_delivery_mode": "disabled"}, False, "disabled"),
        ({"email_delivery_mode": "bogus"}, False, "disabled"),
        # Redirect and live, ready.
        ({"email_delivery_mode": "redirect", "email_redirect_to": REDIRECT}, False, "redirect"),
        ({"email_delivery_mode": "redirect", "email_redirect_to": REDIRECT}, True, "test"),
        ({"email_delivery_mode": "live"}, False, "live"),
        ({"email_delivery_mode": "live"}, True, "test"),
    ],
)
def test_effective_delivery_mode(overrides: dict[str, Any], is_test: bool, expected: str) -> None:
    assert outbox._effective_mode(_settings(**overrides), is_test=is_test) == expected


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"email_delivery_mode": "live", "resend_api_key": None}, "live_not_configured"),
        ({"email_delivery_mode": "live", "email_from_address": None}, "live_not_configured"),
        ({"email_delivery_mode": "live", "email_provider": "none"}, "live_not_configured"),
        # A redirect address never rescues an unready live configuration.
        (
            {"email_delivery_mode": "live", "resend_api_key": None, "email_redirect_to": REDIRECT},
            "live_not_configured",
        ),
        ({"email_delivery_mode": "redirect"}, "redirect_not_configured"),
        (
            {"email_delivery_mode": "redirect", "email_redirect_to": REDIRECT, "resend_api_key": None},
            "redirect_not_configured",
        ),
    ],
)
def test_an_unready_mode_fails_loudly_instead_of_falling_back(
    overrides: dict[str, Any], reason: str
) -> None:
    for is_test in (False, True):
        with pytest.raises(RuntimeError, match=reason):
            outbox._effective_mode(_settings(**overrides), is_test=is_test)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"email_enabled": False}, "disabled"),
        ({"email_delivery_mode": "disabled"}, "disabled"),
        ({"email_delivery_mode": "live"}, "test"),
        ({"email_delivery_mode": "live", "resend_api_key": None}, "disabled"),
        ({"email_delivery_mode": "redirect", "email_redirect_to": REDIRECT}, "test"),
        ({"email_delivery_mode": "redirect"}, "disabled"),
    ],
)
def test_the_test_center_sends_only_when_the_mode_is_ready(
    overrides: dict[str, Any], expected: str
) -> None:
    assert service._effective_test_mode(_settings(**overrides)) == expected


# Retry timing ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attempt", "base"), [(0, 30), (1, 30), (2, 120), (3, 480), (4, 1920), (5, 7200), (9, 7200)]
)
def test_backoff_is_exponential_bounded_and_jittered(attempt: int, base: int) -> None:
    for _ in range(50):
        delay = outbox._backoff_seconds(attempt)
        assert base <= delay <= base + min(60, base // 5)


def test_backoff_never_shrinks_between_attempts() -> None:
    floors = [min(7200, 30 * 4 ** max(0, attempt - 1)) for attempt in range(1, 9)]
    assert floors == sorted(floors)
