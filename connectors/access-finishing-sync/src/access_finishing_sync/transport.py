"""HTTP transport.

TLS certificates are always verified against the operating-system trust store
(Windows certificate store via truststore). There is deliberately no option to
disable verification. Redirects are not followed, so credentials are only ever
sent to the configured URL.
"""

import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx
import truststore

from access_finishing_sync import __version__

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
USER_AGENT = f"access-finishing-sync/{__version__}"

FailureKind = Literal["connect", "timeout", "network", "response_too_large"]


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)  # lower-case names
    body: bytes = b""


class TransportError(Exception):
    """No complete HTTP response was received. Carries no request details."""

    def __init__(self, kind: FailureKind, error_type: str) -> None:
        super().__init__(f"{kind} failure ({error_type})")
        self.kind = kind
        self.error_type = error_type


class Transport(Protocol):
    def post(self, url: str, body: bytes, headers: Mapping[str, str]) -> HttpResponse: ...

    def close(self) -> None: ...


def build_ssl_context() -> ssl.SSLContext:
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # PROTOCOL_TLS_CLIENT already requires these; asserted so they cannot regress.
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise RuntimeError("TLS certificate verification must be enabled")
    return context


class HttpxTransport:
    def __init__(
        self,
        connect_timeout: float,
        read_timeout: float,
        *,
        ssl_context: ssl.SSLContext | None = None,
        mock_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.ssl_context = ssl_context or build_ssl_context()
        self.timeout = httpx.Timeout(
            connect=connect_timeout, read=read_timeout, write=read_timeout, pool=connect_timeout
        )
        self._client = httpx.Client(
            verify=self.ssl_context,
            timeout=self.timeout,
            follow_redirects=False,
            transport=mock_transport,
        )

    def post(self, url: str, body: bytes, headers: Mapping[str, str]) -> HttpResponse:
        try:
            with self._client.stream(
                "POST", url, content=body, headers={**headers, "User-Agent": USER_AGENT}
            ) as response:
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise TransportError("response_too_large", "ResponseTooLarge")
                    chunks.append(chunk)
                return HttpResponse(
                    status=response.status_code,
                    headers={k.lower(): v for k, v in response.headers.items()},
                    body=b"".join(chunks),
                )
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            raise TransportError("connect", type(error).__name__) from None
        except httpx.TimeoutException as error:
            raise TransportError("timeout", type(error).__name__) from None
        except httpx.HTTPError as error:
            raise TransportError("network", type(error).__name__) from None

    def close(self) -> None:
        self._client.close()
