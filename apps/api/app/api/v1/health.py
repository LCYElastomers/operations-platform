from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.db.schema_state import schema_state
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ok", "not_configured", "unavailable", "migrations_pending"]


@router.get("/health", response_model=HealthResponse)
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Liveness check. Does not touch the database."""
    return HealthResponse(status="ok", service=settings.app_name, version=settings.app_version)


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "Not ready"}},
)
def ready(response: Response) -> ReadinessResponse:
    """Readiness: the database answers and its schema is at the migration head
    shipped with this code. A pending migration means stored data may not be
    readable, so the service reports not ready instead of serving partial data."""
    try:
        with get_sessionmaker()() as session:
            at_head = schema_state(session.connection()).at_head
    except DatabaseNotConfiguredError:
        state: Literal["not_configured", "unavailable", "migrations_pending", "ok"] = (
            "not_configured"
        )
    except SQLAlchemyError:
        state = "unavailable"
    else:
        state = "ok" if at_head else "migrations_pending"
    if state != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="not_ready", database=state)
    return ReadinessResponse(status="ready", database="ok")
