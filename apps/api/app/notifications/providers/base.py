"""Provider-neutral email send interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class EmailMessage:
    from_email: str
    from_name: str | None
    to: tuple[str, ...]
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()
    reply_to: str | None = None
    subject: str = ""
    html: str = ""
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderSendResult:
    accepted: bool
    provider_message_id: str | None
    provider_status: str | None
    provider_error_code: str | None
    error_message: str | None
    retryable: bool
    sanitized_response: dict[str, Any]
    http_status: int | None = None


class EmailProvider(Protocol):
    code: str

    def send(self, message: EmailMessage) -> ProviderSendResult: ...
