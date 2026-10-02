import ssl

import httpx
import pytest
import truststore

from access_finishing_sync.transport import (
    MAX_RESPONSE_BYTES,
    HttpxTransport,
    TransportError,
    build_ssl_context,
)

URL = "https://ops.example.test/api/v1/ingestion/quality/finishing/batches"


def test_tls_certificates_are_verified_with_the_os_trust_store() -> None:
    context = build_ssl_context()

    assert isinstance(context, truststore.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_transport_uses_a_verifying_context_by_default() -> None:
    transport = HttpxTransport(3, 7)
    try:
        assert transport.ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert transport.ssl_context.check_hostname is True
    finally:
        transport.close()


def test_connect_and_read_timeouts_are_separate() -> None:
    transport = HttpxTransport(3, 7)
    try:
        assert (transport.timeout.connect, transport.timeout.read) == (3, 7)
    finally:
        transport.close()


def mock(handler) -> HttpxTransport:
    return HttpxTransport(3, 7, mock_transport=httpx.MockTransport(handler))


def test_posts_exact_bytes_and_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True}, headers={"Retry-After": "3"})

    response = mock(handler).post(URL, b'{"a":1}', {"X-Connector-Id": "lcy-access-sync"})

    assert seen[0].content == b'{"a":1}'
    assert seen[0].headers["x-connector-id"] == "lcy-access-sync"
    assert seen[0].headers["user-agent"].startswith("access-finishing-sync/")
    assert (response.status, response.headers["retry-after"]) == (200, "3")


def test_redirects_are_not_followed() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(307, headers={"Location": "https://elsewhere.example.test/"})

    response = mock(handler).post(URL, b"{}", {"Authorization": "Bearer x"})

    assert response.status == 307
    assert calls == [URL]


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (httpx.ConnectError("refused"), "connect"),
        (httpx.ConnectTimeout("slow"), "connect"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.RemoteProtocolError("bad"), "network"),
    ],
)
def test_network_failures_become_transport_errors(error: Exception, kind: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(TransportError) as caught:
        mock(handler).post(URL, b"{}", {"Authorization": "Bearer do-not-show"})

    assert caught.value.kind == kind
    assert "do-not-show" not in str(caught.value)


def test_oversized_responses_are_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))

    with pytest.raises(TransportError) as caught:
        mock(handler).post(URL, b"{}", {})

    assert caught.value.kind == "response_too_large"
