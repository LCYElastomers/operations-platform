"""Authentication for machine-to-machine (connector) endpoints.

A connector sends its identity and its secret separately:

    X-Connector-Id: lcy-access-sync
    Authorization: Bearer <secret>

The API stores only SHA-256 digests of secrets (INGESTION_CONNECTORS). Secrets
are high-entropy random tokens, so a fast digest is sufficient; comparison is
constant-time and always performs the same amount of work, and every failure
returns the same response whether the connector ID or the secret was wrong.
Secrets and Authorization headers are never logged.

Generate a secret and its digest:

    python -m app.core.machine_auth new-secret
"""

import getpass
import hashlib
import hmac
import logging
import secrets
import sys
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import (
    MAX_SECRETS_PER_CONNECTOR,
    ConnectorCredentials,
    Settings,
    get_settings,
)

logger = logging.getLogger(__name__)

CONNECTOR_ID_HEADER = "X-Connector-Id"
DEVELOPMENT_CONNECTOR_ID = "development-unauthenticated"
SECRET_PREFIX = "opc_"  # noqa: S105 - marks generated tokens for secret scanners
MAX_PRESENTED_SECRET_LENGTH = 256
MAX_PRESENTED_ID_LENGTH = 100
# Compared against when a connector has fewer digests than the maximum (or is
# unknown), so verification time does not depend on which part was wrong.
_PADDING_DIGEST = secrets.token_hex(32)

_bearer = HTTPBearer(auto_error=False, description="Connector secret")
_connector_id_header = APIKeyHeader(
    name=CONNECTOR_ID_HEADER, auto_error=False, description="Connector ID"
)


@dataclass(frozen=True)
class MachinePrincipal:
    """The connector a request is attributed to."""

    connector_id: str
    authenticated: bool
    # None means unrestricted (development mode only).
    source_systems: frozenset[str] | None

    def may_write(self, source_system: str) -> bool:
        return self.source_systems is None or source_system in self.source_systems


def generate_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def secret_digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_connector(
    connectors: dict[str, ConnectorCredentials], connector_id: str, secret: str
) -> ConnectorCredentials | None:
    presented = secret_digest(secret)
    credentials = connectors.get(connector_id)
    real = list(credentials.secret_sha256) if credentials is not None else []
    slots = real + [_PADDING_DIGEST] * (MAX_SECRETS_PER_CONNECTOR - len(real))
    results = [hmac.compare_digest(presented, digest) for digest in slots]
    if credentials is not None and any(results[: len(real)]):
        return credentials
    return None


def _reject(connector_id: str | None, settings: Settings) -> HTTPException:
    # The attempted ID is logged only when it is a configured connector, so a
    # secret pasted into the wrong header never reaches the logs.
    known = connector_id if connector_id in settings.ingestion_connectors else "unrecognized"
    logger.warning(
        "event=machine_auth result=rejected reason=invalid_credentials connector=%s", known
    )
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "invalid_credentials", "message": "Connector authentication failed."},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _authenticate_connector(
    settings: Settings,
    connector_id: str | None,
    authorization: HTTPAuthorizationCredentials | None,
) -> MachinePrincipal:
    secret = authorization.credentials if authorization is not None else None
    if (
        not connector_id
        or not secret
        or len(connector_id) > MAX_PRESENTED_ID_LENGTH
        or len(secret) > MAX_PRESENTED_SECRET_LENGTH
    ):
        raise _reject(connector_id, settings)
    credentials = verify_connector(settings.ingestion_connectors, connector_id, secret)
    if credentials is None:
        raise _reject(connector_id, settings)
    logger.info("event=machine_auth result=authenticated connector=%s", connector_id)
    return MachinePrincipal(
        connector_id=connector_id,
        authenticated=True,
        source_systems=frozenset(credentials.source_systems),
    )


def require_machine_principal(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    connector_id: Annotated[str | None, Depends(_connector_id_header)],
) -> MachinePrincipal:
    if settings.ingestion_auth_mode == "connector":
        return _authenticate_connector(settings, connector_id, authorization)

    # Settings already refuse the development mode in production; this check
    # keeps the dependency fail-closed even if settings are constructed directly.
    if (
        settings.ingestion_auth_mode == "development-unauthenticated"
        and settings.environment != "production"
    ):
        logger.warning(
            "event=machine_auth result=allowed_unauthenticated connector=%s",
            DEVELOPMENT_CONNECTOR_ID,
        )
        return MachinePrincipal(
            connector_id=DEVELOPMENT_CONNECTOR_ID, authenticated=False, source_systems=None
        )

    logger.warning("event=machine_auth result=rejected reason=ingestion_disabled")
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error": "ingestion_disabled",
            "message": "Machine ingestion is not enabled on this server.",
        },
    )


def _main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    if command == "new-secret":
        secret = generate_secret()
        print("Connector secret (give to the connector; it is not stored by the API):")
        print(secret)
        print("SHA-256 digest (add to INGESTION_CONNECTORS secret_sha256):")
        print(secret_digest(secret))
        return 0
    if command == "digest":
        print(secret_digest(getpass.getpass("Connector secret: ")))
        return 0
    print("usage: python -m app.core.machine_auth new-secret | digest", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
