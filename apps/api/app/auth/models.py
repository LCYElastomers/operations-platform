"""Users, roles, permissions, sessions and password-setup tokens (schema ``core``).

User -> UserRole -> Role -> RolePermission -> Permission. A user's effective
permissions are the union of the permissions of their active roles, read from
the database on every request.

Users are never deleted: records keep their IDs in history, so a user who
leaves is deactivated. Password hashes, session tokens and setup tokens are
stored only as hashes and are never returned by the API or logged.
"""

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CORE_SCHEMA = "core"

USER_STATUSES = ("active", "inactive")
TOKEN_PURPOSES = ("setup", "reset")
ROLE_CODE_PATTERN = "^[A-Z][A-Z0-9_]{1,49}$"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="status"),
        # Emails are stored normalized (trimmed, lower case), so uniqueness is exact.
        CheckConstraint(
            "email = lower(btrim(email)) AND char_length(email) BETWEEN 3 AND 254",
            name="email",
        ),
        CheckConstraint("btrim(name) <> '' AND char_length(name) <= 200", name="name"),
        CheckConstraint("image IS NULL OR char_length(image) <= 2000", name="image"),
        CheckConstraint("failed_logins >= 0", name="failed_logins"),
        Index("uq_users_email", "email", unique=True),
        {"schema": CORE_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    image: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    # Null until the user sets a password through a setup link.
    password_hash: Mapped[str | None] = mapped_column(Text)
    failed_logins: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        CheckConstraint(f"code ~ '{ROLE_CODE_PATTERN}'", name="code"),
        CheckConstraint("btrim(name) <> '' AND char_length(name) <= 100", name="name"),
        CheckConstraint("char_length(description) <= 1000", name="description"),
        {"schema": CORE_SCHEMA},
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    # Standard roles seeded by the platform; they cannot be deleted.
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # An inactive role grants nothing.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PermissionDefinition(Base):
    """The known permissions. Only these can be granted to a role."""

    __tablename__ = "permissions"
    __table_args__ = ({"schema": CORE_SCHEMA},)

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    module: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = ({"schema": CORE_SCHEMA},)

    role_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey(Role.code, name="fk_role_permissions_role", ondelete="CASCADE"),
        primary_key=True,
    )
    permission_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey(
            PermissionDefinition.code, name="fk_role_permissions_permission", ondelete="RESTRICT"
        ),
        primary_key=True,
    )


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        Index("ix_user_roles_role", "role_code"),
        {"schema": CORE_SCHEMA},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(User.id, name="fk_user_roles_user", ondelete="RESTRICT"), primary_key=True
    )
    role_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey(Role.code, name="fk_user_roles_role", ondelete="RESTRICT"),
        primary_key=True,
    )
    assigned_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    assigned_by: Mapped[str] = mapped_column(Text, nullable=False)


class AuthSession(Base):
    """A signed-in browser session. Only the SHA-256 of the token is stored."""

    __tablename__ = "sessions"
    __table_args__ = (
        Index("uq_sessions_token_hash", "token_hash", unique=True),
        Index("ix_sessions_user", "user_id"),
        {"schema": CORE_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(User.id, name="fk_sessions_user", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Absolute limit; the idle limit is measured from last_seen_at.
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordToken(Base):
    """A one-time password setup or reset link. Only the SHA-256 of the token is stored."""

    __tablename__ = "password_tokens"
    __table_args__ = (
        CheckConstraint("purpose IN ('setup', 'reset')", name="purpose"),
        Index("uq_password_tokens_token_hash", "token_hash", unique=True),
        Index("ix_password_tokens_user", "user_id"),
        {"schema": CORE_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(User.id, name="fk_password_tokens_user", ondelete="CASCADE"),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
