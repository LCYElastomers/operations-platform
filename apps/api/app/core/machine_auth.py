"""Authentication for machine-to-machine (connector) endpoints.

Connector credentials are not implemented yet. Until they are, every request
is refused unless INGESTION_AUTH_MODE=development-unauthenticated is set in a
non-production environment. The next iteration replaces the development mode
with verified connector credentials behind this same dependency.
"""

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

DEVELOPMENT_CONNECTOR_ID = "development-unauthenticated"


@dataclass(frozen=True)
class MachinePrincipal:
    """The connector a request is attributed to."""

    connector_id: str
    authenticated: bool


def require_machine_principal(
    settings: Annotated[Settings, Depends(get_settings)],
) -> MachinePrincipal:
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
        return MachinePrincipal(connector_id=DEVELOPMENT_CONNECTOR_ID, authenticated=False)

    logger.warning("event=machine_auth result=rejected reason=ingestion_disabled")
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error": "ingestion_disabled",
            "message": "Machine ingestion is not enabled on this server.",
        },
    )
