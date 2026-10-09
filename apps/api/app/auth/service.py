"""Sign-in, password links and password changes.

Failures never say whether an email is registered, a password is set, or an
account is locked or inactive: every refused sign-in gets the same answer and
takes about the same time. Events are logged with the user ID when known, never
with a password, hash, token or the attempted email.
"""

import datetime as dt
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit.recorder import AuditChange, record_changes
from app.auth import sessions
from app.auth.credentials import (
    check_password_policy,
    hash_password,
    needs_rehash,
    new_token,
    token_hash,
    verify_password,
)
from app.auth.models import PasswordToken, User
from app.core.config import Settings

logger = logging.getLogger(__name__)

USER_ENTITY = "core.user"


def user_key(user_id: uuid.UUID) -> str:
    return f"users/{user_id}"


def normalize_email(email: str) -> str:
    return email.strip().lower()


class SignInFailedError(Exception):
    pass


class PasswordLinkInvalidError(Exception):
    pass


def sign_in(
    db: Session, email: str, password: str, settings: Settings, now: dt.datetime
) -> tuple[User, str]:
    """Check the credentials and open a session; returns the user and the new
    session token. Raises SignInFailedError for every kind of refusal."""
    user = db.execute(
        select(User).where(User.email == normalize_email(email)).with_for_update()
    ).scalar_one_or_none()
    if user is None:
        verify_password(None, password)
        logger.info("event=sign_in result=failed reason=unknown_account")
        raise SignInFailedError
    locked = user.locked_until is not None and user.locked_until > now
    if locked or user.status != "active" or user.password_hash is None:
        verify_password(None, password)
        reason = "locked" if locked else ("inactive" if user.status != "active" else "no_password")
        logger.info("event=sign_in result=failed reason=%s user=%s", reason, user.id)
        db.rollback()
        raise SignInFailedError
    if not verify_password(user.password_hash, password):
        user.failed_logins += 1
        if user.failed_logins >= settings.login_max_failures:
            user.locked_until = now + dt.timedelta(minutes=settings.login_lock_minutes)
            user.failed_logins = 0
            logger.warning("event=sign_in result=locked user=%s", user.id)
        else:
            logger.info("event=sign_in result=failed reason=bad_password user=%s", user.id)
        db.commit()
        raise SignInFailedError
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    token = sessions.create_session(db, user.id, settings, now)
    db.commit()
    logger.info("event=sign_in result=success user=%s", user.id)
    return user, token


def sign_out(db: Session, token: str, now: dt.datetime) -> None:
    sessions.revoke_session(db, token, now)
    db.commit()


@dataclass(frozen=True)
class PasswordLink:
    token: str
    expires_at: dt.datetime


def issue_password_link(
    db: Session,
    user: User,
    purpose: str,
    *,
    issued_by: str,
    settings: Settings,
    now: dt.datetime,
) -> PasswordLink:
    """A one-time link for the user to set a password. Earlier unused links of
    the user stop working. The caller commits."""
    db.execute(
        update(PasswordToken)
        .where(PasswordToken.user_id == user.id, PasswordToken.used_at.is_(None))
        .values(used_at=now)
    )
    token = new_token()
    expires_at = now + dt.timedelta(hours=settings.password_link_hours)
    db.add(
        PasswordToken(
            token_hash=token_hash(token),
            user_id=user.id,
            purpose=purpose,
            created_at=now,
            created_by=issued_by,
            expires_at=expires_at,
        )
    )
    logger.info("event=password_link_issued purpose=%s user=%s by=%s", purpose, user.id, issued_by)
    return PasswordLink(token, expires_at)


def _link_user(db: Session, token: str, now: dt.datetime) -> tuple[PasswordToken, User]:
    row = db.execute(
        select(PasswordToken, User)
        .join(User, User.id == PasswordToken.user_id)
        .where(PasswordToken.token_hash == token_hash(token))
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise PasswordLinkInvalidError
    link, user = row
    if link.used_at is not None or link.expires_at <= now or user.status != "active":
        raise PasswordLinkInvalidError
    return link, user


def check_password_link(db: Session, token: str, now: dt.datetime) -> User:
    """The user a valid, unused link belongs to (for the setup page's greeting)."""
    _, user = _link_user(db, token, now)
    db.rollback()
    return user


def set_password_with_link(db: Session, token: str, password: str, now: dt.datetime) -> User:
    """Use a link: set the password, end the user's sessions, unlock the account."""
    link, user = _link_user(db, token, now)
    check_password_policy(password, email=user.email)
    _set_password(db, user, password, now, actor_id=str(user.id))
    link.used_at = now
    db.commit()
    logger.info("event=password_set via=%s user=%s", link.purpose, user.id)
    return user


def change_password(
    db: Session,
    user_id: uuid.UUID,
    current: str,
    new: str,
    now: dt.datetime,
    *,
    keep_session_id: int | None,
) -> None:
    """A signed-in user's own change; other sessions of the user end."""
    user = db.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one()
    if not verify_password(user.password_hash, current):
        db.rollback()
        logger.info("event=password_change result=failed reason=bad_password user=%s", user.id)
        raise SignInFailedError
    check_password_policy(new, email=user.email)
    _set_password(db, user, new, now, actor_id=str(user.id), keep_session_id=keep_session_id)
    db.commit()
    logger.info("event=password_change result=success user=%s", user.id)


def _set_password(
    db: Session,
    user: User,
    password: str,
    now: dt.datetime,
    *,
    actor_id: str,
    keep_session_id: int | None = None,
) -> None:
    had_password = user.password_hash is not None
    user.password_hash = hash_password(password)
    user.failed_logins = 0
    user.locked_until = None
    user.updated_at = now
    user.updated_by = actor_id
    sessions.revoke_user_sessions(db, user.id, now, keep_session_id=keep_session_id)
    db.flush()
    record_changes(
        db,
        actor_id=actor_id,
        change_set_id=uuid.uuid4(),
        occurred_at=now,
        changes=[
            AuditChange(
                action="update",
                entity_type=USER_ENTITY,
                entity_key=user_key(user.id),
                old_value={"passwordSet": had_password},
                new_value={"passwordSet": True},
            )
        ],
    )
