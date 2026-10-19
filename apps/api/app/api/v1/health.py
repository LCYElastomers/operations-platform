from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.db.schema_state import schema_state
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.notifications import service as notifications_service

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ok", "not_configured", "unavailable", "migrations_pending"]
    notifications: dict[str, Any] | None = None


@router.get("/health", response_model=HealthResponse)
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Liveness check. Does not touch the database."""
    return HealthResponse(status="ok", service=settings.app_name, version=settings.app_version)


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "Not ready"}},
)
def ready(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReadinessResponse:
    """Readiness: the database answers and its schema is at the migration head
    shipped with this code. A pending migration means stored data may not be
    readable, so the service reports not ready instead of serving partial data."""
    notifications_detail: dict[str, Any] | None = None
    try:
        with get_sessionmaker()() as session:
            at_head = schema_state(session.connection()).at_head
            if (
                settings.environment == "production"
                and settings.email_delivery_mode == "live"
                and not settings.email_live_ready
            ):
                overview = notifications_service.overview(session, settings, days=1)
                notifications_detail = {
                    "provider": overview.provider,
                    "apiKeyConfigured": overview.api_key_configured,
                    "deliveryMode": overview.delivery_mode,
                    "emailEnabled": overview.email_enabled,
                    "emergencyPause": overview.emergency_pause,
                    "warnings": overview.warnings,
                }
    except DatabaseNotConfiguredError:
        state: Literal["not_configured", "unavailable", "migrations_pending", "ok"] = (
            "not_configured"
        )
    except SQLAlchemyError:
        state = "unavailable"
    else:
        state = "ok" if at_head else "migrations_pending"
    if notifications_detail is not None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="not_ready",
            database=state,
            notifications=notifications_detail,
        )
    if state != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="not_ready", database=state)
    return ReadinessResponse(status="ready", database="ok")
