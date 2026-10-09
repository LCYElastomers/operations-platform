"""Sign-in sessions and the user they belong to.

A session is an opaque random token in an HttpOnly cookie; the database keeps
only its SHA-256. On every request the session, the user's status and the
permissions of the user's active roles are read again, so deactivating a user,
removing a role or changing a role's permissions takes effect immediately.
"""

import datetime as dt
import uuid
from dataclasses import dataclass

from fastapi import Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.credentials import new_token, token_hash
from app.auth.models import AuthSession, Role, RolePermission, User, UserRole
from app.core.config import Settings
from app.core.permissions import Permission

# Only refresh last_seen_at this often, so reads do not write on every request.
TOUCH_INTERVAL = dt.timedelta(minutes=1)


def cookie_name(settings: Settings) -> str:
    # The __Host- prefix makes browsers accept the cookie only over HTTPS, for
    # this host only (no Domain) and for the whole site.
    return "__Host-op_session" if settings.session_cookie_secure else "op_session"


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        cookie_name(settings),
        token,
        max_age=settings.session_absolute_hours * 3600,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        cookie_name(settings),
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def create_session(db: Session, user_id: uuid.UUID, settings: Settings, now: dt.datetime) -> str:
    """A new session for the user; returns the token for the cookie (never stored)."""
    token = new_token()
    db.add(
        AuthSession(
            token_hash=token_hash(token),
            user_id=user_id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + dt.timedelta(hours=settings.session_absolute_hours),
        )
    )
    return token


def revoke_session(db: Session, token: str, now: dt.datetime) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.token_hash == token_hash(token), AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def revoke_user_sessions(
    db: Session, user_id: uuid.UUID, now: dt.datetime, *, keep_session_id: int | None = None
) -> None:
    statement = update(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
    )
    if keep_session_id is not None:
        statement = statement.where(AuthSession.id != keep_session_id)
    db.execute(statement.values(revoked_at=now))


@dataclass(frozen=True)
class Access:
    """A user's active roles and the permissions they grant."""

    roles: tuple[str, ...]
    permissions: frozenset[Permission]


_KNOWN = {p.value: p for p in Permission}


def access_of(db: Session, user_id: uuid.UUID) -> Access:
    """Effective access: the union of the permissions of the user's active roles.

    Permission codes not in the catalog grant nothing."""
    rows = db.execute(
        select(Role.code, RolePermission.permission_code)
        .join(UserRole, UserRole.role_code == Role.code)
        .outerjoin(RolePermission, RolePermission.role_code == Role.code)
        .where(UserRole.user_id == user_id, Role.active.is_(True))
    ).all()
    roles = tuple(sorted({code for code, _ in rows}))
    permissions = frozenset(_KNOWN[p] for _, p in rows if p in _KNOWN)
    return Access(roles, permissions)


@dataclass(frozen=True)
class SessionUser:
    session_id: int
    user: User
    access: Access


def resolve(db: Session, token: str, settings: Settings, now: dt.datetime) -> SessionUser | None:
    """The active user of a valid session, or None (unknown, revoked, expired,
    idle too long, or the user is inactive)."""
    row = db.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(AuthSession.token_hash == token_hash(token))
    ).one_or_none()
    if row is None:
        return None
    session, user = row
    idle_limit = session.last_seen_at + dt.timedelta(minutes=settings.session_idle_minutes)
    if (
        session.revoked_at is not None
        or session.expires_at <= now
        or idle_limit <= now
        or user.status != "active"
    ):
        return None
    if now - session.last_seen_at >= TOUCH_INTERVAL:
        db.execute(update(AuthSession).where(AuthSession.id == session.id).values(last_seen_at=now))
        db.commit()
    return SessionUser(session.id, user, access_of(db, user.id))
