"""User and role administration.

Rules enforced here, on the server, for every change:

- Users are never deleted; they are deactivated. Deactivation ends their sessions.
- Only roles and permissions that exist can be assigned.
- No escalation: without ``users.manage`` a user may only assign roles whose
  permissions they hold themselves; without ``roles.manage`` they may only grant
  permissions they hold themselves.
- Standard roles cannot be deleted or renamed, and ADMIN always holds every
  permission and cannot be deactivated.
- At least one active user always holds both ``users.manage`` and
  ``roles.manage`` (checked inside the transaction, under a lock that
  serializes administration changes).
- Every change is audited (``core.user`` / ``core.role``) with the acting user.
"""

import datetime as dt
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.recorder import AuditAction, AuditChange, record_changes
from app.auth import sessions
from app.auth.models import PermissionDefinition, Role, RolePermission, User, UserRole
from app.auth.roles import ADMIN_CODE
from app.auth.service import USER_ENTITY, normalize_email, user_key
from app.core.authorization import UserPrincipal
from app.core.permissions import Permission

ROLE_ENTITY = "core.role"
SUPER_PERMISSIONS = (Permission.USERS_MANAGE, Permission.ROLES_MANAGE)


def role_key(code: str) -> str:
    return f"roles/{code}"


class AdminRuleError(ValueError):
    """The change breaks an administration rule. Nothing was written."""

    def __init__(self, error: str, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.error = error
        self.message = message
        self.field = field


class AdminNotFoundError(LookupError):
    pass


class AdminForbiddenError(PermissionError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Actor:
    principal: UserPrincipal
    now: dt.datetime

    @property
    def actor_id(self) -> str:
        return self.principal.actor_id


# Reading ---------------------------------------------------------------------------


def roles_of_users(db: Session, user_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    ids = list(user_ids)
    result: dict[uuid.UUID, list[str]] = {i: [] for i in ids}
    if not ids:
        return result
    for user_id, code in db.execute(
        select(UserRole.user_id, UserRole.role_code)
        .where(UserRole.user_id.in_(ids))
        .order_by(UserRole.role_code)
    ):
        result[user_id].append(code)
    return result


def role_permissions(db: Session) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {code: set() for code in db.scalars(select(Role.code))}
    for role, permission in db.execute(
        select(RolePermission.role_code, RolePermission.permission_code)
    ):
        result[role].add(permission)
    return result


def role_user_counts(db: Session) -> dict[str, int]:
    return dict(
        db.execute(
            select(UserRole.role_code, func.count())
            .join(User, User.id == UserRole.user_id)
            .where(User.status == "active")
            .group_by(UserRole.role_code)
        ).all()
    )


def _user_value(user: User, roles: list[str]) -> dict[str, Any]:
    return {
        "email": user.email,
        "name": user.name,
        "image": user.image,
        "status": user.status,
        "roles": sorted(roles),
    }


def _role_value(role: Role, permissions: Iterable[str]) -> dict[str, Any]:
    return {
        "name": role.name,
        "description": role.description,
        "active": role.active,
        "isSystem": role.is_system,
        "permissions": sorted(permissions),
    }


# Guards ----------------------------------------------------------------------------


def lock_administration(db: Session) -> None:
    """Serialize user and role changes until the transaction ends."""
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('core.access_administration'))"))


_lock = lock_administration


def administrator_exists(db: Session) -> bool:
    """Whether an active user holds users.manage and roles.manage through active roles."""
    holders = (
        select(UserRole.user_id)
        .join(User, User.id == UserRole.user_id)
        .join(Role, Role.code == UserRole.role_code)
        .join(RolePermission, RolePermission.role_code == Role.code)
        .where(
            User.status == "active",
            Role.active.is_(True),
            RolePermission.permission_code.in_([p.value for p in SUPER_PERMISSIONS]),
        )
        .group_by(UserRole.user_id)
        .having(func.count(func.distinct(RolePermission.permission_code)) == len(SUPER_PERMISSIONS))
    )
    return db.execute(select(func.count()).select_from(holders.subquery())).scalar_one() > 0


def _ensure_administrator_remains(db: Session) -> None:
    if not administrator_exists(db):
        raise AdminRuleError(
            "last_administrator",
            "This change would leave no active user able to manage users and roles. "
            "Give another active user the Administrator role first.",
        )


def _known_roles(db: Session, codes: Iterable[str]) -> list[str]:
    wanted = sorted(set(codes))
    found = set(db.scalars(select(Role.code).where(Role.code.in_(wanted))))
    missing = [c for c in wanted if c not in found]
    if missing:
        raise AdminRuleError("unknown_role", "Choose roles from the list.", field="roleCodes")
    return wanted


def _known_permissions(db: Session, codes: Iterable[str]) -> list[str]:
    wanted = sorted(set(codes))
    catalog = {p.value for p in Permission}
    stored = set(
        db.scalars(select(PermissionDefinition.code).where(PermissionDefinition.code.in_(wanted)))
    )
    if any(c not in catalog or c not in stored for c in wanted):
        raise AdminRuleError(
            "unknown_permission", "Choose permissions from the list.", field="permissions"
        )
    return wanted


def _refuse_escalation_by_roles(db: Session, actor: Actor, added: Iterable[str]) -> None:
    if actor.principal.has(Permission.USERS_MANAGE):
        return
    held = {p.value for p in actor.principal.granted}
    by_role = role_permissions(db)
    for code in added:
        if not by_role.get(code, set()) <= held:
            raise AdminForbiddenError(
                "You can only assign roles whose permissions you hold yourself."
            )


def refuse_acting_on_stronger(db: Session, actor: Actor, user_id: uuid.UUID) -> None:
    """Without users.manage, a user may only change users whose permissions they hold."""
    if actor.principal.has(Permission.USERS_MANAGE):
        return
    if not sessions.access_of(db, user_id).permissions <= actor.principal.granted:
        raise AdminForbiddenError("You can only change users whose permissions you hold yourself.")


def _refuse_escalation_by_permissions(actor: Actor, added: Iterable[str]) -> None:
    if actor.principal.has(Permission.ROLES_MANAGE):
        return
    held = {p.value for p in actor.principal.granted}
    if not set(added) <= held:
        raise AdminForbiddenError("You can only grant permissions you hold yourself.")


def _audit(
    db: Session,
    actor: Actor,
    action: AuditAction,
    entity_type: str,
    key: str,
    old: dict[str, Any] | None,
    new: dict[str, Any] | None,
) -> None:
    record_changes(
        db,
        actor_id=actor.actor_id,
        change_set_id=uuid.uuid4(),
        occurred_at=actor.now,
        changes=[AuditChange(action, entity_type, key, old, new)],
    )


def audit_password_link(db: Session, actor: Actor, user: User, purpose: str) -> None:
    """Record that a setup or reset link was issued (never the link itself)."""
    _audit(
        db,
        actor,
        "update",
        USER_ENTITY,
        user_key(user.id),
        {"passwordSet": user.password_hash is not None},
        {"passwordSet": user.password_hash is not None, "passwordLinkIssued": purpose},
    )


def _locked_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one_or_none()
    if user is None:
        raise AdminNotFoundError(user_id)
    return user


def _locked_role(db: Session, code: str) -> Role:
    role = db.execute(select(Role).where(Role.code == code).with_for_update()).scalar_one_or_none()
    if role is None:
        raise AdminNotFoundError(code)
    return role


def _set_user_roles(db: Session, user_id: uuid.UUID, codes: list[str], actor: Actor) -> None:
    db.execute(delete(UserRole).where(UserRole.user_id == user_id))
    if codes:
        db.execute(
            insert(UserRole),
            [
                {
                    "user_id": user_id,
                    "role_code": code,
                    "assigned_at": actor.now,
                    "assigned_by": actor.actor_id,
                }
                for code in codes
            ],
        )


def _email_taken(error: IntegrityError) -> bool:
    return "uq_users_email" in str(error.orig)


# Users -----------------------------------------------------------------------------


def create_user(
    db: Session,
    *,
    email: str,
    name: str,
    role_codes: list[str],
    actor: Actor,
) -> User:
    """A new active user without a password; the caller issues a setup link and commits."""
    _lock(db)
    codes = _known_roles(db, role_codes)
    if codes and not actor.principal.has(Permission.USERS_ASSIGN_ROLES):
        raise AdminForbiddenError("Assigning roles needs the users.assignRoles permission.")
    _refuse_escalation_by_roles(db, actor, codes)
    user = User(
        id=uuid.uuid4(),
        email=normalize_email(email),
        name=name.strip(),
        status="active",
        created_at=actor.now,
        created_by=actor.actor_id,
        updated_at=actor.now,
        updated_by=actor.actor_id,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as error:
        if _email_taken(error):
            raise AdminRuleError(
                "email_taken", "A user with this email already exists.", field="email"
            ) from None
        raise
    _set_user_roles(db, user.id, codes, actor)
    _audit(db, actor, "create", USER_ENTITY, user_key(user.id), None, _user_value(user, codes))
    return user


def update_user(
    db: Session, user_id: uuid.UUID, *, email: str, name: str, image: str | None, actor: Actor
) -> User:
    _lock(db)
    user = _locked_user(db, user_id)
    refuse_acting_on_stronger(db, actor, user_id)
    roles = roles_of_users(db, [user_id])[user_id]
    before = _user_value(user, roles)
    user.email = normalize_email(email)
    user.name = name.strip()
    user.image = image
    if _user_value(user, roles) == before:
        return user
    user.updated_at = actor.now
    user.updated_by = actor.actor_id
    try:
        db.flush()
    except IntegrityError as error:
        if _email_taken(error):
            raise AdminRuleError(
                "email_taken", "A user with this email already exists.", field="email"
            ) from None
        raise
    _audit(db, actor, "update", USER_ENTITY, user_key(user_id), before, _user_value(user, roles))
    return user


def set_user_status(db: Session, user_id: uuid.UUID, status: str, actor: Actor) -> User:
    _lock(db)
    user = _locked_user(db, user_id)
    if user.status == status:
        return user
    if status == "inactive" and user.id == actor.principal.user_id:
        raise AdminRuleError("deactivate_self", "You cannot deactivate your own account.")
    refuse_acting_on_stronger(db, actor, user_id)
    roles = roles_of_users(db, [user_id])[user_id]
    before = _user_value(user, roles)
    user.status = status
    user.updated_at = actor.now
    user.updated_by = actor.actor_id
    if status == "inactive":
        sessions.revoke_user_sessions(db, user.id, actor.now)
    db.flush()
    _ensure_administrator_remains(db)
    _audit(db, actor, "update", USER_ENTITY, user_key(user_id), before, _user_value(user, roles))
    return user


def set_user_roles(db: Session, user_id: uuid.UUID, role_codes: list[str], actor: Actor) -> User:
    _lock(db)
    user = _locked_user(db, user_id)
    codes = _known_roles(db, role_codes)
    current = roles_of_users(db, [user_id])[user_id]
    if set(current) == set(codes):
        return user
    added = set(codes) - set(current)
    removed = set(current) - set(codes)
    refuse_acting_on_stronger(db, actor, user_id)
    _refuse_escalation_by_roles(db, actor, added | removed)
    before = _user_value(user, current)
    _set_user_roles(db, user_id, codes, actor)
    user.updated_at = actor.now
    user.updated_by = actor.actor_id
    db.flush()
    _ensure_administrator_remains(db)
    _audit(db, actor, "update", USER_ENTITY, user_key(user_id), before, _user_value(user, codes))
    return user


# Roles -----------------------------------------------------------------------------


def create_role(
    db: Session,
    *,
    code: str,
    name: str,
    description: str,
    permissions: list[str],
    actor: Actor,
) -> Role:
    _lock(db)
    granted = _known_permissions(db, permissions)
    if granted and not actor.principal.has(Permission.ROLES_ASSIGN_PERMISSIONS):
        raise AdminForbiddenError(
            "Granting permissions needs the roles.assignPermissions permission."
        )
    _refuse_escalation_by_permissions(actor, granted)
    if db.get(Role, code) is not None:
        raise AdminRuleError(
            "role_code_taken", "A role with this code already exists.", field="code"
        )
    role = Role(
        code=code,
        name=name.strip(),
        description=description.strip(),
        is_system=False,
        active=True,
        created_at=actor.now,
        updated_at=actor.now,
    )
    db.add(role)
    db.flush()
    if granted:
        db.execute(
            insert(RolePermission), [{"role_code": code, "permission_code": p} for p in granted]
        )
    _audit(db, actor, "create", ROLE_ENTITY, role_key(code), None, _role_value(role, granted))
    return role


def update_role(
    db: Session, code: str, *, name: str, description: str, active: bool, actor: Actor
) -> Role:
    _lock(db)
    role = _locked_role(db, code)
    permissions = role_permissions(db)[code]
    before = _role_value(role, permissions)
    if code == ADMIN_CODE and not active:
        raise AdminRuleError(
            "protected_role", "The Administrator role cannot be deactivated.", field="active"
        )
    if role.is_system and name.strip() != role.name:
        raise AdminRuleError("protected_role", "Standard roles keep their names.", field="name")
    role.name = name.strip()
    role.description = description.strip()
    role.active = active
    if _role_value(role, permissions) == before:
        return role
    role.updated_at = actor.now
    db.flush()
    _ensure_administrator_remains(db)
    _audit(db, actor, "update", ROLE_ENTITY, role_key(code), before, _role_value(role, permissions))
    return role


def set_role_permissions(db: Session, code: str, permissions: list[str], actor: Actor) -> Role:
    _lock(db)
    role = _locked_role(db, code)
    if code == ADMIN_CODE:
        raise AdminRuleError(
            "protected_role", "The Administrator role always holds every permission."
        )
    granted = _known_permissions(db, permissions)
    current = role_permissions(db)[code]
    if set(granted) == current:
        return role
    _refuse_escalation_by_permissions(actor, set(granted) ^ current)
    before = _role_value(role, current)
    db.execute(delete(RolePermission).where(RolePermission.role_code == code))
    if granted:
        db.execute(
            insert(RolePermission), [{"role_code": code, "permission_code": p} for p in granted]
        )
    role.updated_at = actor.now
    db.flush()
    _ensure_administrator_remains(db)
    _audit(db, actor, "update", ROLE_ENTITY, role_key(code), before, _role_value(role, granted))
    return role


def delete_role(db: Session, code: str, actor: Actor) -> None:
    _lock(db)
    role = _locked_role(db, code)
    if role.is_system:
        raise AdminRuleError("protected_role", "Standard roles cannot be deleted.")
    holders = db.execute(
        select(func.count()).select_from(UserRole).where(UserRole.role_code == code)
    ).scalar_one()
    if holders:
        raise AdminRuleError(
            "role_in_use",
            f"{holders} user(s) have this role. Remove it from them first, or deactivate the role.",
        )
    permissions = role_permissions(db)[code]
    before = _role_value(role, permissions)
    db.delete(role)
    db.flush()
    _audit(db, actor, "delete", ROLE_ENTITY, role_key(code), before, None)
