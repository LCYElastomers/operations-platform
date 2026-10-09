"""Authorization for interactive (human) user requests.

Every protected endpoint depends on one of the ``require_*`` dependencies,
which resolve the requesting user through ``get_user_principal``:

1. read the session cookie and look the session up (``app.auth.sessions``);
2. refuse it if revoked, expired, idle too long, or the user is inactive;
3. load the user's active roles and the union of their permissions;
4. check the required permission(s).

Record-level rules (for example "only the action owner completes it") are
checked by the module after this, on the record itself. Permissions decide;
code never tests role names.

Unsafe methods (POST, PUT, PATCH, DELETE) carrying a session must also send
``X-Requested-With: operations-platform``. Browsers cannot add that header to a
cross-site request without a CORS preflight, which this API never grants.

Unauthenticated requests get 401 ``authentication_required``; authenticated
users lacking a permission get 403 ``permission_denied``. Neither says who could
perform the operation.
"""

import datetime as dt
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError

from app.auth import sessions
from app.core.config import Settings, get_settings
from app.core.permissions import Permission
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker

logger = logging.getLogger(__name__)

CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "operations-platform"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class UserPrincipal:
    """The signed-in user a request acts as, and what they may do."""

    # None for anonymous requests.
    user_id: uuid.UUID | None
    name: str | None = None
    email: str | None = None
    image: str | None = None
    roles: tuple[str, ...] = ()
    granted: frozenset[Permission] = frozenset()
    session_id: int | None = None

    @property
    def authenticated(self) -> bool:
        return self.user_id is not None

    @property
    def actor_id(self) -> str:
        """The ID written to created_by / updated_by / audit events."""
        if self.user_id is None:
            raise RuntimeError("anonymous requests do not act")
        return str(self.user_id)

    @property
    def display_name(self) -> str:
        return self.name or ""

    def has(self, permission: Permission) -> bool:
        return permission in self.granted

    def has_any(self, *permissions: Permission) -> bool:
        return any(p in self.granted for p in permissions)

    def has_all(self, *permissions: Permission) -> bool:
        return all(p in self.granted for p in permissions)


ANONYMOUS = UserPrincipal(user_id=None)


def has_permission(principal: UserPrincipal, permission: Permission) -> bool:
    return principal.has(permission)


def get_effective_permissions(principal: UserPrincipal) -> frozenset[Permission]:
    return principal.granted


def _error(status_code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": error, "message": message})


def _unauthenticated() -> HTTPException:
    return _error(status.HTTP_401_UNAUTHORIZED, "authentication_required", "Sign in to continue.")


def get_user_principal(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> UserPrincipal:
    token = request.cookies.get(sessions.cookie_name(settings))
    if not token or len(token) > 200:
        return ANONYMOUS
    if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        logger.warning("event=authorization result=denied reason=csrf_header_missing")
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "csrf_check_failed",
            "This request was refused because it did not come from the application.",
        )
    try:
        maker = get_sessionmaker()
    except DatabaseNotConfiguredError:
        return ANONYMOUS
    try:
        with maker() as db:
            found = sessions.resolve(db, token, settings, dt.datetime.now(dt.UTC))
    except SQLAlchemyError:
        logger.exception("event=authorization result=error reason=session_lookup_failed")
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "database_unavailable",
            "Sign-in could not be checked because the database could not be reached.",
        ) from None
    if found is None:
        return ANONYMOUS
    return UserPrincipal(
        user_id=found.user.id,
        name=found.user.name,
        email=found.user.email,
        image=found.user.image,
        roles=found.access.roles,
        granted=found.access.permissions,
        session_id=found.session_id,
    )


Principal = Annotated[UserPrincipal, Depends(get_user_principal)]


def require_user(principal: Principal) -> UserPrincipal:
    """Admits any signed-in, active user."""
    if not principal.authenticated:
        raise _unauthenticated()
    return principal


# Inactive users have no valid session, so every signed-in principal is active.
require_active_user = require_user


def _deny(principal: UserPrincipal, required: tuple[Permission, ...]) -> HTTPException:
    if not principal.authenticated:
        logger.warning(
            "event=authorization result=denied reason=anonymous permission=%s",
            ",".join(required),
        )
        return _unauthenticated()
    logger.warning(
        "event=authorization result=denied reason=missing_permission permission=%s user=%s",
        ",".join(required),
        principal.user_id,
    )
    return forbidden()


def forbidden(message: str = "You do not have permission to perform this action.") -> HTTPException:
    return _error(status.HTTP_403_FORBIDDEN, "permission_denied", message)


def require_permission(permission: Permission) -> Callable[..., UserPrincipal]:
    """Dependency that admits only users holding ``permission``."""

    def dependency(principal: Principal) -> UserPrincipal:
        if principal.authenticated and principal.has(permission):
            return principal
        raise _deny(principal, (permission,))

    return dependency


def require_any_permission(*permissions: Permission) -> Callable[..., UserPrincipal]:
    def dependency(principal: Principal) -> UserPrincipal:
        if principal.authenticated and principal.has_any(*permissions):
            return principal
        raise _deny(principal, permissions)

    return dependency


def require_all_permissions(*permissions: Permission) -> Callable[..., UserPrincipal]:
    def dependency(principal: Principal) -> UserPrincipal:
        if principal.authenticated and principal.has_all(*permissions):
            return principal
        raise _deny(principal, permissions)

    return dependency


def ensure(principal: UserPrincipal, *permissions: Permission) -> None:
    """Inside an endpoint: refuse unless the user holds every permission."""
    if not principal.has_all(*permissions):
        raise _deny(principal, permissions)
