"""Connector authentication for machine ingestion. No database required."""

import hmac
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_finishing_ingestion import UNREACHABLE_DB, URL, batch, make_client

from app.core import machine_auth
from app.core.config import ConnectorCredentials, Settings
from app.core.machine_auth import (
    CONNECTOR_ID_HEADER,
    SECRET_PREFIX,
    _main,
    generate_secret,
    secret_digest,
    verify_connector,
)

SOURCE = "access-qryFINISHING-AVG"
CURRENT_SECRET = generate_secret()
NEXT_SECRET = generate_secret()
OTHER_SECRET = generate_secret()


def connector_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "environment": "production",
        "database_url": UNREACHABLE_DB,
        "moisture_data_source": "database",
        "ingestion_auth_mode": "connector",
        "ingestion_connectors": {
            "lcy-access-sync": {
                "secret_sha256": [secret_digest(CURRENT_SECRET), secret_digest(NEXT_SECRET)],
                "source_systems": [SOURCE],
            },
            "other-connector": {
                "secret_sha256": [secret_digest(OTHER_SECRET)],
                "source_systems": ["other-source"],
            },
        },
    }
    values.update(overrides)
    return Settings(**values)


def headers(connector_id: str | None, secret: str | None) -> dict[str, str]:
    result = {}
    if connector_id is not None:
        result[CONNECTOR_ID_HEADER] = connector_id
    if secret is not None:
        result["Authorization"] = f"Bearer {secret}"
    return result


@pytest.fixture
def client() -> Iterator[TestClient]:
    with make_client(connector_settings()) as test_client:
        yield test_client


def authenticated_through(response: Any) -> bool:
    # An empty batch fails envelope validation, which only runs after authentication.
    return response.status_code == 422


# Successful authentication ---------------------------------------------------------


@pytest.mark.parametrize("secret", [CURRENT_SECRET, NEXT_SECRET])
def test_any_active_secret_authenticates(client: TestClient, secret: str) -> None:
    response = client.post(URL, json=batch(rows=[]), headers=headers("lcy-access-sync", secret))

    assert authenticated_through(response)


def test_connector_mode_is_allowed_in_production() -> None:
    assert connector_settings().ingestion_auth_mode == "connector"


# Failures are fail-closed and indistinguishable ------------------------------------------


@pytest.mark.parametrize(
    ("connector_id", "secret"),
    [
        ("lcy-access-sync", "opc_wrong-secret"),
        ("unknown-connector", CURRENT_SECRET),
        ("other-connector", CURRENT_SECRET),
        ("lcy-access-sync", None),
        (None, CURRENT_SECRET),
        (None, None),
        ("lcy-access-sync", ""),
        ("lcy-access-sync", "x" * 300),
        ("x" * 101, CURRENT_SECRET),
    ],
)
def test_invalid_credentials_get_one_generic_response(
    client: TestClient, connector_id: str | None, secret: str | None
) -> None:
    response = client.post(URL, json=batch(), headers=headers(connector_id, secret))

    assert response.status_code == 401
    assert response.json() == {
        "detail": {"error": "invalid_credentials", "message": "Connector authentication failed."}
    }
    assert response.headers["www-authenticate"] == "Bearer"


def test_non_bearer_authorization_is_rejected(client: TestClient) -> None:
    response = client.post(
        URL,
        json=batch(),
        headers={
            CONNECTOR_ID_HEADER: "lcy-access-sync",
            "Authorization": f"Basic {CURRENT_SECRET}",
        },
    )

    assert response.status_code == 401


def test_secret_digest_cannot_be_used_as_the_secret(client: TestClient) -> None:
    response = client.post(
        URL, json=batch(), headers=headers("lcy-access-sync", secret_digest(CURRENT_SECRET))
    )

    assert response.status_code == 401


def test_authentication_happens_before_the_body_is_read(client: TestClient) -> None:
    response = client.post(URL, content=b"not json", headers={"content-type": "text/plain"})

    assert response.status_code == 401


def test_verification_does_the_same_work_for_unknown_and_known_connectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    real_compare = hmac.compare_digest

    def counting_compare(a: Any, b: Any) -> bool:
        calls.append(1)
        return real_compare(a, b)

    monkeypatch.setattr(machine_auth.hmac, "compare_digest", counting_compare)
    connectors = connector_settings().ingestion_connectors
    counts = []
    for connector_id, secret in [
        ("lcy-access-sync", CURRENT_SECRET),
        ("lcy-access-sync", "wrong"),
        ("other-connector", "wrong"),
        ("unknown", "wrong"),
    ]:
        calls.clear()
        verify_connector(connectors, connector_id, secret)
        counts.append(len(calls))

    assert len(set(counts)) == 1


def test_padding_slots_never_authenticate() -> None:
    connectors = {
        "c": ConnectorCredentials(secret_sha256=[secret_digest("real")], source_systems=["s"])
    }

    assert verify_connector(connectors, "c", "real") is not None
    assert verify_connector(connectors, "c", machine_auth._PADDING_DIGEST) is None


# Credentials never reach logs ------------------------------------------------------------


def test_credentials_are_never_logged(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    client.post(URL, json=batch(rows=[]), headers=headers("lcy-access-sync", CURRENT_SECRET))
    client.post(URL, json=batch(), headers=headers("lcy-access-sync", "opc_wrong-secret"))
    client.post(URL, json=batch(), headers=headers(CURRENT_SECRET, CURRENT_SECRET))

    assert CURRENT_SECRET not in caplog.text
    assert "opc_wrong-secret" not in caplog.text
    assert secret_digest(CURRENT_SECRET) not in caplog.text
    assert "result=authenticated connector=lcy-access-sync" in caplog.text
    assert "reason=invalid_credentials connector=lcy-access-sync" in caplog.text
    assert "reason=invalid_credentials connector=unrecognized" in caplog.text


# Source-system authorization -----------------------------------------------------------


def test_connector_may_only_write_its_source_systems(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    response = client.post(
        URL,
        json=batch(sourceSystem="other-source"),
        headers=headers("lcy-access-sync", CURRENT_SECRET),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "source_system_not_allowed"
    assert "reason=source_system_not_allowed" in caplog.text


# Configuration ------------------------------------------------------------------


def test_connector_mode_requires_connectors() -> None:
    with pytest.raises(ValueError, match="requires INGESTION_CONNECTORS"):
        connector_settings(ingestion_connectors={})


def test_connector_mode_requires_a_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="requires DATABASE_URL"):
        connector_settings(database_url=None)


@pytest.mark.parametrize(
    "connectors",
    [
        {"lcy-access-sync": {"secret_sha256": ["not-a-digest"], "source_systems": [SOURCE]}},
        {"lcy-access-sync": {"secret_sha256": [], "source_systems": [SOURCE]}},
        {"lcy-access-sync": {"secret_sha256": ["a" * 64] * 6, "source_systems": [SOURCE]}},
        {"lcy-access-sync": {"secret_sha256": ["a" * 64], "source_systems": []}},
        {"lcy-access-sync": {"secret_sha256": ["a" * 64]}},
        {"bad id!": {"secret_sha256": ["a" * 64], "source_systems": [SOURCE]}},
        {"lcy-access-sync": {"secret_sha256": ["a" * 64], "source_systems": [SOURCE], "x": 1}},
        {
            "one": {"secret_sha256": ["a" * 64], "source_systems": [SOURCE]},
            "two": {"secret_sha256": ["a" * 64], "source_systems": [SOURCE]},
        },
    ],
)
def test_invalid_connector_configuration_is_rejected(connectors: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        connector_settings(ingestion_connectors=connectors)


def test_connectors_load_from_environment_json(monkeypatch: pytest.MonkeyPatch) -> None:
    digest = secret_digest(CURRENT_SECRET)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DB)
    monkeypatch.setenv("MOISTURE_DATA_SOURCE", "database")
    monkeypatch.setenv("INGESTION_AUTH_MODE", "connector")
    monkeypatch.setenv(
        "INGESTION_CONNECTORS",
        f'{{"lcy-access-sync": {{"secret_sha256": ["{digest}"], "source_systems": ["{SOURCE}"]}}}}',
    )

    settings = Settings(_env_file=None)

    assert settings.ingestion_connectors["lcy-access-sync"].secret_sha256 == [digest]


def test_configuration_errors_do_not_echo_digests(monkeypatch: pytest.MonkeyPatch) -> None:
    digest = secret_digest(CURRENT_SECRET)
    with pytest.raises(ValueError) as error:
        connector_settings(
            ingestion_connectors={
                "one": {"secret_sha256": [digest], "source_systems": [SOURCE]},
                "two": {"secret_sha256": [digest], "source_systems": [SOURCE]},
            }
        )

    assert digest not in str(error.value)


# Secret generation -------------------------------------------------------------------


def test_generated_secrets_are_unique_and_high_entropy() -> None:
    secrets = {generate_secret() for _ in range(100)}

    assert len(secrets) == 100
    assert all(s.startswith(SECRET_PREFIX) and len(s) >= 40 for s in secrets)


def test_new_secret_command_prints_a_matching_digest(capsys: pytest.CaptureFixture[str]) -> None:
    assert _main(["machine_auth", "new-secret"]) == 0

    lines = capsys.readouterr().out.splitlines()
    secret, digest = lines[1], lines[3]
    assert secret.startswith(SECRET_PREFIX)
    assert digest == secret_digest(secret)
