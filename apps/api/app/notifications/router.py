"""Administration endpoints for the shared Notifications domain."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.router import database
from app.core.authorization import UserPrincipal, require_permission
from app.core.config import Settings, get_settings
from app.core.permissions import Permission
from app.notifications import context_providers, service
from app.notifications.schemas import (
    DeliveryDetailOut,
    DeliveryFilters,
    DeliveryListResponse,
    EventTypeOut,
    OverviewOut,
    PreviewIn,
    PreviewOut,
    PsmActionPickerItem,
    PsmActionPickerResponse,
    PublishIn,
    RetryOut,
    SettingsOut,
    SettingsUpdate,
    TemplateDraftUpdate,
    TemplateListResponse,
    TemplateOut,
    TemplateRevisionOut,
    TestPreviewIn,
    TestPreviewOut,
    TestSendIn,
    TestSendOut,
    ValidateOut,
    WorkflowListResponse,
    WorkflowOut,
    WorkflowUpdate,
)

router = APIRouter(prefix="/admin/notifications", tags=["notifications"])

Db = Annotated[Session, Depends(database)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _user(permission: Permission) -> Any:
    return Annotated[UserPrincipal, Depends(require_permission(permission))]


Viewer = _user(Permission.NOTIFICATIONS_VIEW)
TemplatesManager = _user(Permission.NOTIFICATIONS_TEMPLATES_MANAGE)
WorkflowsManager = _user(Permission.NOTIFICATIONS_WORKFLOWS_MANAGE)
DeliveryViewer = _user(Permission.NOTIFICATIONS_DELIVERY_VIEW)
DeliveryRetrier = _user(Permission.NOTIFICATIONS_DELIVERY_RETRY)
TestSender = _user(Permission.NOTIFICATIONS_TEST_SEND)
SettingsManager = _user(Permission.NOTIFICATIONS_SETTINGS_MANAGE)


def _error(status_code: int, error: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error": error, "message": message, **extra}
    )


def _actor(user: UserPrincipal) -> service.Actor:
    return service.Actor(actor_id=user.actor_id, user_id=user.user_id)


def _write[T](db: Session, change: Callable[[], T]) -> T:
    try:
        result = change()
        db.commit()
        return result
    except service.NotificationsNotFoundError:
        db.rollback()
        raise _error(
            status.HTTP_404_NOT_FOUND, "not_found", "No such notification record."
        ) from None
    except service.NotificationsRuleError as error:
        db.rollback()
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, error.error, error.message) from None
    except SQLAlchemyError:
        db.rollback()
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "database_unavailable",
            (
                "Notifications administration is unavailable because the "
                "database could not be reached."
            ),
        ) from None


@router.get("/overview", response_model=OverviewOut)
def notifications_overview(
    db: Db,
    settings: SettingsDep,
    _: Viewer,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> OverviewOut:
    return service.overview(db, settings, days=days)


@router.get("/event-types", response_model=list[EventTypeOut])
def list_event_types(db: Db, _: Viewer) -> list[EventTypeOut]:
    return service.list_event_types(db)


@router.get("/templates", response_model=TemplateListResponse)
def list_templates(db: Db, _: Viewer) -> TemplateListResponse:
    return TemplateListResponse(templates=service.list_templates(db))


@router.get("/templates/{template_id}", response_model=TemplateOut)
def get_template(db: Db, template_id: int, _: Viewer) -> TemplateOut:
    try:
        return service.get_template(db, template_id)
    except service.NotificationsNotFoundError:
        raise _error(status.HTTP_404_NOT_FOUND, "not_found", "No such template.") from None


@router.get("/templates/{template_id}/revisions/{revision_id}", response_model=TemplateRevisionOut)
def get_revision(db: Db, template_id: int, revision_id: int, _: Viewer) -> TemplateRevisionOut:
    try:
        return service.get_revision(db, template_id, revision_id)
    except service.NotificationsNotFoundError:
        raise _error(status.HTTP_404_NOT_FOUND, "not_found", "No such template revision.") from None


@router.post(
    "/templates/{template_id}/draft",
    response_model=TemplateRevisionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_draft(db: Db, template_id: int, user: TemplatesManager) -> TemplateRevisionOut:
    return _write(
        db,
        lambda: service.create_draft_from_published(db, template_id, actor=_actor(user)),
    )


@router.patch(
    "/templates/{template_id}/revisions/{revision_id}",
    response_model=TemplateRevisionOut,
)
def update_draft(
    db: Db,
    template_id: int,
    revision_id: int,
    body: TemplateDraftUpdate,
    user: TemplatesManager,
) -> TemplateRevisionOut:
    return _write(
        db,
        lambda: service.update_draft(
            db,
            template_id,
            revision_id,
            actor=_actor(user),
            subject_template=body.subject_template,
            html_template=body.html_template,
            text_template=body.text_template,
        ),
    )


@router.post(
    "/templates/{template_id}/revisions/{revision_id}/validate",
    response_model=ValidateOut,
)
def validate_revision(
    db: Db,
    template_id: int,
    revision_id: int,
    body: PublishIn,
    _: Viewer,
) -> ValidateOut:
    try:
        return service.validate_revision(
            db, template_id, revision_id, event_type_code=body.event_type_code
        )
    except service.NotificationsNotFoundError:
        raise _error(status.HTTP_404_NOT_FOUND, "not_found", "No such template revision.") from None


@router.post("/templates/{template_id}/revisions/{revision_id}/preview", response_model=PreviewOut)
def preview_revision(
    db: Db,
    settings: SettingsDep,
    template_id: int,
    revision_id: int,
    body: PreviewIn,
    _: Viewer,
) -> PreviewOut:
    try:
        return service.preview_revision(
            db,
            settings,
            template_id,
            revision_id,
            event_type_code=body.event_type_code,
            context=body.context,
            psm_action_id=body.psm_action_id,
        )
    except service.NotificationsNotFoundError:
        raise _error(status.HTTP_404_NOT_FOUND, "not_found", "No such template revision.") from None
    except service.NotificationsRuleError as error:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, error.error, error.message) from None


@router.post("/templates/{template_id}/revisions/{revision_id}/publish", response_model=TemplateOut)
def publish_revision(
    db: Db,
    template_id: int,
    revision_id: int,
    body: PublishIn,
    user: TemplatesManager,
) -> TemplateOut:
    return _write(
        db,
        lambda: service.publish_revision(
            db,
            template_id,
            revision_id,
            actor=_actor(user),
            event_type_code=body.event_type_code,
        ),
    )


@router.get("/workflows", response_model=WorkflowListResponse)
def list_workflows(db: Db, _: Viewer) -> WorkflowListResponse:
    return WorkflowListResponse(workflows=service.list_workflows(db))


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut)
def get_workflow(db: Db, workflow_id: int, _: Viewer) -> WorkflowOut:
    try:
        return service.get_workflow(db, workflow_id)
    except service.NotificationsNotFoundError:
        raise _error(status.HTTP_404_NOT_FOUND, "not_found", "No such workflow.") from None


@router.patch("/workflows/{workflow_id}", response_model=WorkflowOut)
def update_workflow(
    db: Db,
    workflow_id: int,
    body: WorkflowUpdate,
    user: WorkflowsManager,
) -> WorkflowOut:
    return _write(
        db,
        lambda: service.update_workflow(
            db,
            workflow_id,
            actor=_actor(user),
            display_name=body.display_name,
            enabled=body.enabled,
            delivery_timing_code=body.delivery_timing_code,
            schedule_config_json=body.schedule_config_json,
            recipient_rules=body.recipient_rules,
        ),
    )


def delivery_filters(
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    from_date: Annotated[dt.date | None, Query(alias="fromDate")] = None,
    to_date: Annotated[dt.date | None, Query(alias="toDate")] = None,
    event_type_code: Annotated[str | None, Query(alias="eventTypeCode")] = None,
    module_code: Annotated[str | None, Query(alias="moduleCode")] = None,
    workflow_id: Annotated[int | None, Query(alias="workflowId")] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DeliveryFilters:
    return DeliveryFilters(
        status=status_filter,
        from_date=from_date,
        to_date=to_date,
        event_type_code=event_type_code,
        module_code=module_code,
        workflow_id=workflow_id,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/deliveries", response_model=DeliveryListResponse)
def list_deliveries(
    db: Db,
    _: DeliveryViewer,
    filters: Annotated[DeliveryFilters, Depends(delivery_filters)],
) -> DeliveryListResponse:
    items, total = service.list_deliveries(db, filters)
    return DeliveryListResponse(deliveries=items, total=total)


@router.get("/deliveries/{delivery_id}", response_model=DeliveryDetailOut)
def get_delivery(
    db: Db,
    delivery_id: uuid.UUID,
    user: DeliveryViewer,
) -> DeliveryDetailOut:
    include_bcc = user.has(Permission.NOTIFICATIONS_SETTINGS_MANAGE)
    try:
        return service.get_delivery_detail(db, delivery_id, include_bcc=include_bcc)
    except service.NotificationsNotFoundError:
        raise _error(status.HTTP_404_NOT_FOUND, "not_found", "No such delivery.") from None


@router.post("/deliveries/{delivery_id}/retry", response_model=RetryOut)
def retry_delivery(
    db: Db,
    delivery_id: uuid.UUID,
    user: DeliveryRetrier,
) -> RetryOut:
    return _write(db, lambda: service.retry_delivery(db, delivery_id, actor=_actor(user)))


@router.get("/test/psm-actions", response_model=PsmActionPickerResponse)
def list_psm_actions_for_test(
    db: Db,
    _: TestSender,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> PsmActionPickerResponse:
    rows = context_providers.list_psm_actions_for_test(db, limit=limit)
    return PsmActionPickerResponse(
        actions=[PsmActionPickerItem(**row) for row in rows]  # type: ignore[arg-type]
    )


@router.post("/test/preview", response_model=TestPreviewOut)
def test_preview(
    db: Db,
    settings: SettingsDep,
    body: TestPreviewIn,
    _: TestSender,
) -> TestPreviewOut:
    if body.template_id is None and body.workflow_id is None:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "template_required",
            "Provide templateId or workflowId.",
        )
    try:
        return service.test_preview(
            db,
            settings,
            template_id=body.template_id,
            workflow_id=body.workflow_id,
            template_revision_id=body.template_revision_id,
            event_type_code=body.event_type_code,
            context=body.context,
            psm_action_id=body.psm_action_id,
            to_email=body.to_email,
        )
    except service.NotificationsNotFoundError:
        raise _error(
            status.HTTP_404_NOT_FOUND, "not_found", "Template or workflow was not found."
        ) from None
    except service.NotificationsRuleError as error:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, error.error, error.message) from None


@router.post("/test/send", response_model=TestSendOut)
def test_send(
    db: Db,
    settings: SettingsDep,
    body: TestSendIn,
    user: TestSender,
) -> TestSendOut:
    if body.template_id is None and body.workflow_id is None:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "template_required",
            "Provide templateId or workflowId.",
        )
    return _write(
        db,
        lambda: service.test_send(
            db,
            settings,
            actor=_actor(user),
            template_id=body.template_id,
            workflow_id=body.workflow_id,
            template_revision_id=body.template_revision_id,
            event_type_code=body.event_type_code,
            context=body.context,
            psm_action_id=body.psm_action_id,
            to_email=body.to_email,
        ),
    )


@router.get("/settings", response_model=SettingsOut)
def read_settings(db: Db, settings: SettingsDep, _: Viewer) -> SettingsOut:
    return service.get_settings(db, settings)


@router.patch("/settings", response_model=SettingsOut)
def patch_settings(
    db: Db,
    settings: SettingsDep,
    body: SettingsUpdate,
    user: SettingsManager,
) -> SettingsOut:
    return _write(
        db,
        lambda: service.update_settings(
            db,
            settings,
            actor=_actor(user),
            emergency_pause=body.emergency_pause,
        ),
    )
