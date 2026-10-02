"""Machine-to-machine ingestion endpoint for finishing measurements."""

import json
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.machine_auth import MachinePrincipal, require_machine_principal
from app.db.session import get_sessionmaker
from app.quality.moisture import ingestion_service
from app.quality.moisture.ingestion_schemas import (
    FinishingBatchIn,
    IngestionResult,
    batch_request_json_schema,
)
from app.quality.moisture.ingestion_service import IngestionDatabaseError, SessionFactory

router = APIRouter(prefix="/ingestion/quality/finishing", tags=["ingestion"])

MAX_BODY_BYTES = 5 * 1024 * 1024


class _InvalidJson(ValueError):
    pass


def _new_session() -> Session:
    return get_sessionmaker()()


def get_ingestion_session_factory() -> SessionFactory:
    """Sessions are opened only after the batch has been validated."""
    return _new_session


def _error(status_code: int, error: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error": error, "message": message, **extra}
    )


async def _read_body(request: Request) -> bytes:
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type != "application/json":
        raise _error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "unsupported_media_type",
            "Content-Type must be application/json.",
        )
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > MAX_BODY_BYTES):
        raise _error(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "payload_too_large",
            f"Request body must be at most {MAX_BODY_BYTES} bytes.",
        )
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise _error(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "payload_too_large",
                f"Request body must be at most {MAX_BODY_BYTES} bytes.",
            )
    return bytes(body)


def _reject_constant(name: str) -> Any:
    raise _InvalidJson(f"{name} is not allowed")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidJson("duplicate key")
        result[key] = value
    return result


def _parse_json(body: bytes) -> Any:
    # Decimal parsing keeps measurements exactly as written in the JSON text.
    try:
        return json.loads(
            body,
            parse_float=Decimal,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (ValueError, RecursionError):
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "invalid_json",
            "Request body must be valid JSON without duplicate keys, NaN, or Infinity.",
        ) from None


def _validate_batch(payload: Any) -> FinishingBatchIn:
    try:
        return FinishingBatchIn.model_validate(payload)
    except ValidationError as error:
        issues = [
            {
                "field": ".".join(str(part) for part in e["loc"]) or None,
                "message": e["msg"],
            }
            for e in error.errors(include_input=False)
        ]
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_error",
            "The batch is invalid; no rows were processed.",
            errors=issues,
        ) from None


@router.post(
    "/batches",
    response_model=IngestionResult,
    summary="Ingest a batch of qryFINISHING-AVG rows",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": batch_request_json_schema()}},
        }
    },
    responses={
        400: {"description": "Body is not valid JSON"},
        413: {"description": "Body too large"},
        415: {"description": "Content-Type is not application/json"},
        422: {"description": "Batch envelope invalid; nothing processed"},
        503: {"description": "Ingestion disabled, or database failure (nothing committed)"},
    },
)
async def ingest_finishing_batch(
    request: Request,
    principal: Annotated[MachinePrincipal, Depends(require_machine_principal)],
    session_factory: Annotated[SessionFactory, Depends(get_ingestion_session_factory)],
) -> IngestionResult:
    batch = _validate_batch(_parse_json(await _read_body(request)))
    try:
        return await run_in_threadpool(
            ingestion_service.ingest_batch,
            batch,
            session_factory,
            connector_id=principal.connector_id,
        )
    except IngestionDatabaseError:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "database_unavailable",
            "The batch was not stored and no rows were committed. It is safe to resubmit.",
            batchId=batch.batch_id,
        ) from None
