"""Resend HTTP adapter. The only module allowed to contact Resend or hold its key."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from app.core.config import Settings
from app.notifications.providers.base import EmailMessage, ProviderSendResult

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
TIMEOUT_SECONDS = 20


def _sanitize(payload: object) -> dict[str, Any]:
    """Keep a short, secret-free summary of the provider response."""
    if not isinstance(payload, dict):
        return {"type": type(payload).__name__}
    out: dict[str, Any] = {}
    for key in ("id", "name", "statusCode", "message", "status"):
        if key in payload:
            value = payload[key]
            if isinstance(value, (str, int, float, bool)) or value is None:
                out[key] = value
    if "id" in payload and "id" not in out:
        out["id"] = str(payload["id"])[:80]
    return out


def _classify(http_status: int | None, body: dict[str, Any]) -> tuple[bool, str | None, str]:
    """Return (retryable, error_code, message). Never includes authorization material."""
    name = str(body.get("name") or body.get("error") or "")
    message = str(body.get("message") or "The email provider refused the request.")
    if http_status is None:
        return True, "connection_error", message
    if http_status == 429 or http_status >= 500:
        return True, name or f"http_{http_status}", message
    if http_status in {401, 403}:
        return False, name or "unauthorized", "The email provider refused authentication."
    if http_status == 422:
        return False, name or "validation_error", message
    if 400 <= http_status < 500:
        return False, name or f"http_{http_status}", message
    return True, name or f"http_{http_status}", message


class ResendEmailProvider:
    code = "resend"

    def __init__(self, settings: Settings, *, timeout: float = TIMEOUT_SECONDS) -> None:
        self._settings = settings
        self._timeout = timeout

    def send(self, message: EmailMessage) -> ProviderSendResult:
        key = self._settings.resend_api_key
        if key is None or not key.get_secret_value().strip():
            return ProviderSendResult(
                accepted=False,
                provider_message_id=None,
                provider_status="not_configured",
                provider_error_code="not_configured",
                error_message="The email provider is not configured.",
                retryable=False,
                sanitized_response={},
                http_status=None,
            )
        from_addr = (
            f"{message.from_name} <{message.from_email}>"
            if message.from_name
            else message.from_email
        )
        body: dict[str, Any] = {
            "from": from_addr,
            "to": list(message.to),
            "subject": message.subject,
            "html": message.html,
            "text": message.text,
        }
        if message.cc:
            body["cc"] = list(message.cc)
        if message.bcc:
            body["bcc"] = list(message.bcc)
        if message.reply_to:
            body["reply_to"] = message.reply_to
        if message.headers:
            body["headers"] = message.headers
        request = urllib.request.Request(
            RESEND_URL,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {key.get_secret_value()}",
                "Content-Type": "application/json",
                "User-Agent": "operations-platform-notifications/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                raw = response.read()
                status = response.status
                payload = json.loads(raw.decode("utf-8") or "{}")
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                payload = {"message": "The email provider returned an unreadable error."}
            # Never log headers or the request body (may contain recipient content);
            # never log the API key.
            logger.warning(
                "Resend HTTP error status=%s code=%s",
                error.code,
                payload.get("name") or payload.get("statusCode"),
            )
            retryable, code, message = _classify(error.code, payload)
            return ProviderSendResult(
                accepted=False,
                provider_message_id=None,
                provider_status="error",
                provider_error_code=code,
                error_message=message,
                retryable=retryable,
                sanitized_response=_sanitize(payload),
                http_status=error.code,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            logger.warning("Resend connection error type=%s", type(error).__name__)
            return ProviderSendResult(
                accepted=False,
                provider_message_id=None,
                provider_status="error",
                provider_error_code="timeout_or_connection",
                error_message="The email provider could not be reached.",
                retryable=True,
                sanitized_response={"error_type": type(error).__name__},
                http_status=None,
            )
        message_id = payload.get("id")
        if status and 200 <= status < 300 and isinstance(message_id, str) and message_id:
            return ProviderSendResult(
                accepted=True,
                provider_message_id=message_id,
                provider_status="accepted",
                provider_error_code=None,
                error_message=None,
                retryable=False,
                sanitized_response=_sanitize(payload),
                http_status=status,
            )
        retryable, code, message = _classify(status, payload)
        return ProviderSendResult(
            accepted=False,
            provider_message_id=None,
            provider_status="error",
            provider_error_code=code,
            error_message=message,
            retryable=retryable,
            sanitized_response=_sanitize(payload),
            http_status=status,
        )
