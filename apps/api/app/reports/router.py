"""The one export endpoint for every report (ReportService).

``POST /api/v1/reports/{key}/export`` with ``{format, period, filters}``:

1. the session must belong to a signed-in, active user (401);
2. the user must hold the report's view permissions and its module's export
   permission, e.g. ``car.view`` + ``car.export`` (403);
3. the format, period and filters are validated against the report (422);
4. the data is read through the module's own repository and services, so the
   file shows what the screen shows for the same period and filters;
5. the file is rendered, a ``core.report_export`` audit event is committed
   (who, which report, format, period and filter summary; never the data), and
   the file is returned.
"""

import datetime as dt
import logging
import re
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import ConfigDict, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit.recorder import AuditChange, record_changes
from app.core.authorization import UserPrincipal, ensure, require_active_user
from app.core.schemas import CamelModel
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker
from app.reports import catalog, theme
from app.reports.definitions import (
    ReportContext,
    ReportDefinition,
    ReportFormat,
    ReportInputError,
)
from app.reports.excel import render_excel
from app.reports.model import Report
from app.reports.pdf import render_pdf
from app.reports.period import PeriodIn
from app.safety.site_calendar import site_today

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])

ENTITY_TYPE = "core.report_export"
MEDIA_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def report_sessions() -> Callable[[], AbstractContextManager[Session]]:
    """Opens database sessions for building a report and for its audit event."""
    try:
        return get_sessionmaker()
    except DatabaseNotConfiguredError:
        raise _unavailable() from None


SignedIn = Annotated[UserPrincipal, Depends(require_active_user)]
Sessions = Annotated[Callable[[], AbstractContextManager[Session]], Depends(report_sessions)]
ReportKey = Annotated[str, Path(pattern=r"^[a-z0-9-]{1,60}$")]


class ExportRequest(CamelModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format: ReportFormat
    period: PeriodIn = PeriodIn()
    filters: dict[str, Any] = Field(default_factory=dict, max_length=30)


def _error(status_code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": error, "message": message})


def _unavailable() -> HTTPException:
    return _error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "database_unavailable",
        "The report could not be generated because the database could not be reached.",
    )


def filename(definition: ReportDefinition, period_part: str, fmt: str) -> str:
    stem = f"{theme.PRODUCT}_{definition.filename}_{period_part}"
    return f"{_UNSAFE_FILENAME.sub('-', stem).strip('-')}.{fmt}"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@router.post(
    "/{key}/export",
    responses={
        200: {"content": {MEDIA_TYPES["pdf"]: {}, MEDIA_TYPES["xlsx"]: {}}},
        401: {"description": "Not signed in"},
        403: {"description": "Missing the report's view or export permission"},
        404: {"description": "No such report"},
        422: {"description": "Invalid format, period or filters"},
        503: {"description": "Database unavailable"},
    },
)
def export_report(
    principal: SignedIn, key: ReportKey, request: ExportRequest, sessions: Sessions
) -> Response:
    definition = catalog.REPORTS.get(key)
    if definition is None:
        raise _error(status.HTTP_404_NOT_FOUND, "report_not_found", "No such report.")
    ensure(principal, *definition.permissions)
    if request.format not in definition.formats:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "format_not_available",
            f"{definition.title} is not available as {request.format.upper()}.",
        )
    if definition.period_modes is not None and request.period.mode not in definition.period_modes:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "period_not_available",
            f"{definition.title} cannot be reported for that period.",
        )
    try:
        filters = definition.filters.model_validate(request.filters)
    except ValidationError:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_filters", "The filters are not valid."
        ) from None
    now = _now()
    today = site_today(now)
    period = request.period.resolve(today)
    try:
        with sessions() as session:
            content = definition.build(
                ReportContext(
                    session=session,
                    principal=principal,
                    period=period,
                    filters=filters,
                    today=today,
                    now=now,
                )
            )
    except ReportInputError as error:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "not_reportable", str(error)) from None
    except SQLAlchemyError:
        logger.exception("event=report_export result=error report=%s", key)
        raise _unavailable() from None
    period_label = content.period_label or period.full_label
    name = filename(definition, content.filename_period or period.filename_part, request.format)
    report = Report(
        key=definition.key,
        title=definition.title,
        module=definition.module,
        period_label=period_label,
        filename=name,
        filters=content.filters,
        generated_at=now,
        generated_by=principal.display_name or principal.email or "Signed-in user",
        kpis=content.kpis,
        charts=content.charts,
        tables=content.tables,
        notes=content.notes,
        subtitle=content.subtitle,
    )
    body = render_pdf(report) if request.format == "pdf" else render_excel(report)
    try:
        with sessions() as session:
            record_changes(
                session,
                actor_id=principal.actor_id,
                change_set_id=uuid.uuid4(),
                occurred_at=now,
                changes=[
                    AuditChange(
                        action="create",
                        entity_type=ENTITY_TYPE,
                        entity_key=f"{definition.key}:{request.format}",
                        old_value=None,
                        new_value={
                            "event": "REPORT_EXPORTED",
                            "actorUserId": principal.actor_id,
                            "reportKey": definition.key,
                            "module": definition.module,
                            "format": request.format,
                            "period": period_label,
                            "filters": [f"{label}: {value}" for label, value in content.filters],
                            "exportedAt": now.isoformat(),
                        },
                    )
                ],
            )
            session.commit()
    except SQLAlchemyError:
        logger.exception("event=report_export result=audit_failed report=%s", key)
        raise _unavailable() from None
    logger.info(
        "event=report_export result=ok report=%s format=%s user=%s",
        definition.key,
        request.format,
        principal.user_id,
    )
    return Response(
        content=body,
        media_type=MEDIA_TYPES[request.format],
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
