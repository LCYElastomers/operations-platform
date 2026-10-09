"""Administration endpoints: users, roles, permissions, audit log (``/admin``),
and the user directory used by pickers (``/users/directory``).

Each endpoint requires its own permission; the rules that span records (no
escalation, protected roles, an administrator always remains) are enforced in
``app.auth.admin``.
"""

import datetime as dt
import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.auth import admin, service
from app.auth.models import PermissionDefinition, Role, User
from app.auth.router import database
from app.auth.schemas import (
    AuditEventOut,
    AuditListResponse,
    DirectoryResponse,
    DirectoryUserOut,
    PasswordLinkOut,
    PermissionListResponse,
    PermissionOut,
    RoleCreate,
    RoleListResponse,
    RoleOut,
    RolePermissionsUpdate,
    RoleRefOut,
    RoleUpdate,
    UserCreate,
    UserCreatedResponse,
    UserDetailOut,
    UserListResponse,
    UserOut,
    UserRolesUpdate,
    UserUpdate,
)
from app.auth.sessions import access_of
from app.core.authorization import UserPrincipal, require_permission
from app.core.config import Settings, get_settings
from app.core.permissions import Permission

router = APIRouter(prefix="/admin", tags=["administration"])
directory_router = APIRouter(prefix="/users", tags=["administration"])

Db = Annotated[Session, Depends(database)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _user(permission: Permission) -> Any:
    return Annotated[UserPrincipal, Depends(require_permission(permission))]


UsersViewer = _user(Permission.USERS_VIEW)
UsersCreator = _user(Permission.USERS_CREATE)
UsersEditor = _user(Permission.USERS_EDIT)
UsersActivator = _user(Permission.USERS_ACTIVATE)
UsersDeactivator = _user(Permission.USERS_DEACTIVATE)
RoleAssigner = _user(Permission.USERS_ASSIGN_ROLES)
RolesViewer = _user(Permission.ROLES_VIEW)
RolesCreator = _user(Permission.ROLES_CREATE)
RolesEditor = _user(Permission.ROLES_EDIT)
RolesDeleter = _user(Permission.ROLES_DELETE)
PermissionAssigner = _user(Permission.ROLES_ASSIGN_PERMISSIONS)
AuditViewer = _user(Permission.AUDIT_VIEW)
AppUser = _user(Permission.APP_VIEW)


def _error(status_code: int, error: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error": error, "message": message, **extra}
    )


def _unavailable() -> HTTPException:
    return _error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "database_unavailable",
        "Administration is unavailable because the database could not be reached.",
    )


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _write[T](db: Session, change: Callable[[], T]) -> T:
    """Run an administration change and commit it, mapping rule errors to responses."""
    try:
        result = change()
        db.commit()
        return result
    except admin.AdminNotFoundError:
        db.rollback()
        raise _error(status.HTTP_404_NOT_FOUND, "not_found", "No such user or role.") from None
    except admin.AdminForbiddenError as error:
        db.rollback()
        raise _error(status.HTTP_403_FORBIDDEN, "permission_denied", error.message) from None
    except admin.AdminRuleError as error:
        db.rollback()
        code = (
            status.HTTP_409_CONFLICT
            if error.error in {"email_taken", "role_code_taken", "role_in_use"}
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise _error(code, error.error, error.message, field=error.field) from None
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None


def _role_names(db: Session) -> dict[str, str]:
    return dict(db.execute(select(Role.code, Role.name)).all())


def _user_out(user: User, roles: list[str], names: dict[str, str], now: dt.datetime) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        image=user.image,
        status=user.status,  # type: ignore[arg-type]
        roles=[RoleRefOut(code=c, name=names.get(c, c)) for c in roles],
        password_set=user.password_hash is not None,
        locked=user.locked_until is not None and user.locked_until > now,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _user_detail(db: Session, user_id: uuid.UUID) -> UserDetailOut:
    user = db.get(User, user_id, populate_existing=True)
    if user is None:
        raise _error(status.HTTP_404_NOT_FOUND, "not_found", "No such user.")
    roles = admin.roles_of_users(db, [user_id])[user_id]
    base = _user_out(user, roles, _role_names(db), _now())
    permissions = (
        sorted(p.value for p in access_of(db, user_id).permissions)
        if user.status == "active"
        else []
    )
    return UserDetailOut(**base.model_dump(), permissions=permissions)


def _actor(principal: UserPrincipal) -> admin.Actor:
    return admin.Actor(principal, _now())


# Users -----------------------------------------------------------------------------


@router.get("/users", response_model=UserListResponse)
def list_users(principal: UsersViewer, db: Db) -> UserListResponse:
    """Every user, active and inactive, by name."""
    try:
        users = list(db.scalars(select(User).order_by(func.lower(User.name), User.email)))
        roles = admin.roles_of_users(db, [u.id for u in users])
        names = _role_names(db)
    except SQLAlchemyError:
        raise _unavailable() from None
    now = _now()
    return UserListResponse(users=[_user_out(u, roles[u.id], names, now) for u in users])


@router.get("/users/{user_id}", response_model=UserDetailOut)
def get_user(principal: UsersViewer, db: Db, user_id: uuid.UUID) -> UserDetailOut:
    """A user with their effective permissions (none while inactive)."""
    try:
        return _user_detail(db, user_id)
    except SQLAlchemyError:
        raise _unavailable() from None


@router.post("/users", response_model=UserCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    principal: UsersCreator, db: Db, settings: SettingsDep, request: UserCreate
) -> UserCreatedResponse:
    """A new user and a one-time setup link (shown once) for them to set a password."""
    actor = _actor(principal)

    def change() -> tuple[uuid.UUID, service.PasswordLink]:
        user = admin.create_user(
            db, email=request.email, name=request.name, role_codes=request.role_codes, actor=actor
        )
        link = service.issue_password_link(
            db, user, "setup", issued_by=actor.actor_id, settings=settings, now=actor.now
        )
        return user.id, link

    user_id, link = _write(db, change)
    return UserCreatedResponse(
        user=_user_detail(db, user_id),
        password_link=PasswordLinkOut(token=link.token, expires_at=link.expires_at),
    )


@router.put("/users/{user_id}", response_model=UserDetailOut)
def update_user(
    principal: UsersEditor, db: Db, user_id: uuid.UUID, request: UserUpdate
) -> UserDetailOut:
    actor = _actor(principal)
    _write(
        db,
        lambda: admin.update_user(
            db, user_id, email=request.email, name=request.name, image=request.image, actor=actor
        ),
    )
    return _user_detail(db, user_id)


@router.post("/users/{user_id}/activate", response_model=UserDetailOut)
def activate_user(principal: UsersActivator, db: Db, user_id: uuid.UUID) -> UserDetailOut:
    actor = _actor(principal)
    _write(db, lambda: admin.set_user_status(db, user_id, "active", actor))
    return _user_detail(db, user_id)


@router.post("/users/{user_id}/deactivate", response_model=UserDetailOut)
def deactivate_user(principal: UsersDeactivator, db: Db, user_id: uuid.UUID) -> UserDetailOut:
    """Deactivate a user: they cannot sign in and their sessions end. Their name
    stays on the records and history they appear in."""
    actor = _actor(principal)
    _write(db, lambda: admin.set_user_status(db, user_id, "inactive", actor))
    return _user_detail(db, user_id)


@router.put("/users/{user_id}/roles", response_model=UserDetailOut)
def set_user_roles(
    principal: RoleAssigner, db: Db, user_id: uuid.UUID, request: UserRolesUpdate
) -> UserDetailOut:
    actor = _actor(principal)
    _write(db, lambda: admin.set_user_roles(db, user_id, request.role_codes, actor))
    return _user_detail(db, user_id)


@router.post("/users/{user_id}/password-link", response_model=PasswordLinkOut)
def issue_password_link(
    principal: UsersEditor, db: Db, settings: SettingsDep, user_id: uuid.UUID
) -> PasswordLinkOut:
    """A new one-time link for the user to set a new password (shown once).
    Earlier links stop working; the current password keeps working until used."""
    actor = _actor(principal)

    def change() -> service.PasswordLink:
        user = db.get(User, user_id)
        if user is None:
            raise admin.AdminNotFoundError(user_id)
        if user.status != "active":
            raise admin.AdminRuleError("user_inactive", "Activate the user first.")
        admin.refuse_acting_on_stronger(db, actor, user_id)
        purpose = "reset" if user.password_hash is not None else "setup"
        admin.audit_password_link(db, actor, user, purpose)
        return service.issue_password_link(
            db, user, purpose, issued_by=actor.actor_id, settings=settings, now=actor.now
        )

    link = _write(db, change)
    return PasswordLinkOut(token=link.token, expires_at=link.expires_at)


# Roles -----------------------------------------------------------------------------


def _roles(db: Session) -> list[RoleOut]:
    permissions = admin.role_permissions(db)
    counts = admin.role_user_counts(db)
    return [
        RoleOut(
            code=r.code,
            name=r.name,
            description=r.description,
            is_system=r.is_system,
            active=r.active,
            permissions=sorted(permissions.get(r.code, set())),
            user_count=counts.get(r.code, 0),
        )
        for r in db.scalars(
            select(Role)
            .order_by(Role.is_system.desc(), Role.name)
            .execution_options(populate_existing=True)
        )
    ]


def _role(db: Session, code: str) -> RoleOut:
    found = next((r for r in _roles(db) if r.code == code), None)
    if found is None:
        raise _error(status.HTTP_404_NOT_FOUND, "not_found", "No such role.")
    return found


@router.get("/roles", response_model=RoleListResponse)
def list_roles(principal: RolesViewer, db: Db) -> RoleListResponse:
    try:
        return RoleListResponse(roles=_roles(db))
    except SQLAlchemyError:
        raise _unavailable() from None


@router.get("/permissions", response_model=PermissionListResponse)
def list_permissions(principal: RolesViewer, db: Db) -> PermissionListResponse:
    """The permissions that can be granted to roles."""
    known = {p.value for p in Permission}
    try:
        rows = list(db.scalars(select(PermissionDefinition)))
    except SQLAlchemyError:
        raise _unavailable() from None
    order = {p.value: i for i, p in enumerate(Permission)}
    return PermissionListResponse(
        permissions=[
            PermissionOut(code=r.code, module=r.module, description=r.description)
            for r in sorted(rows, key=lambda r: order.get(r.code, len(order)))
            if r.code in known
        ]
    )


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(principal: RolesCreator, db: Db, request: RoleCreate) -> RoleOut:
    actor = _actor(principal)
    _write(
        db,
        lambda: admin.create_role(
            db,
            code=request.code,
            name=request.name,
            description=request.description,
            permissions=request.permissions,
            actor=actor,
        ),
    )
    return _role(db, request.code)


@router.put("/roles/{code}", response_model=RoleOut)
def update_role(principal: RolesEditor, db: Db, code: str, request: RoleUpdate) -> RoleOut:
    actor = _actor(principal)
    _write(
        db,
        lambda: admin.update_role(
            db,
            code,
            name=request.name,
            description=request.description,
            active=request.active,
            actor=actor,
        ),
    )
    return _role(db, code)


@router.put("/roles/{code}/permissions", response_model=RoleOut)
def set_role_permissions(
    principal: PermissionAssigner, db: Db, code: str, request: RolePermissionsUpdate
) -> RoleOut:
    actor = _actor(principal)
    _write(db, lambda: admin.set_role_permissions(db, code, request.permissions, actor))
    return _role(db, code)


@router.delete("/roles/{code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(principal: RolesDeleter, db: Db, code: str) -> None:
    actor = _actor(principal)
    _write(db, lambda: admin.delete_role(db, code, actor))


# Audit log -------------------------------------------------------------------------


@router.get("/audit", response_model=AuditListResponse)
def audit_log(
    principal: AuditViewer,
    db: Db,
    entity_type: Annotated[str | None, Query(alias="entityType", max_length=100)] = None,
    actor_user_id: Annotated[uuid.UUID | None, Query(alias="actorUserId")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditListResponse:
    """Audit events, newest first."""
    conditions = []
    if entity_type:
        conditions.append(AuditEvent.entity_type == entity_type)
    if actor_user_id:
        conditions.append(AuditEvent.actor_user_id == actor_user_id)
    try:
        total = db.execute(
            select(func.count()).select_from(AuditEvent).where(*conditions)
        ).scalar_one()
        rows = db.scalars(
            select(AuditEvent)
            .where(*conditions)
            .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
        events = [
            AuditEventOut(
                id=e.id,
                occurred_at=e.occurred_at,
                actor_id=e.actor_id,
                actor_name=e.actor_name,
                action=e.action,
                entity_type=e.entity_type,
                entity_key=e.entity_key,
                old_value=_public(e.old_value),
                new_value=_public(e.new_value),
            )
            for e in rows
        ]
    except SQLAlchemyError:
        raise _unavailable() from None
    return AuditListResponse(events=events, total=total)


def _public(value: dict[str, Any] | None) -> dict[str, Any] | None:
    # Import provenance (file locations) is kept for audit but not shown.
    if value is None:
        return None
    return {k: v for k, v in value.items() if k != "source_reference"}


# Directory -------------------------------------------------------------------------


@directory_router.get("/directory", response_model=DirectoryResponse)
def directory(
    principal: AppUser,
    db: Db,
    include_inactive: Annotated[bool, Query(alias="includeInactive")] = False,
) -> DirectoryResponse:
    """Users to choose from when assigning people (names only). Inactive users
    are included on request, to label names on older records."""
    statement = select(User.id, User.name, User.status).order_by(func.lower(User.name))
    if not include_inactive:
        statement = statement.where(User.status == "active")
    try:
        rows = db.execute(statement).all()
    except SQLAlchemyError:
        raise _unavailable() from None
    return DirectoryResponse(
        users=[DirectoryUserOut(id=i, name=n, active=s == "active") for i, n, s in rows]
    )
