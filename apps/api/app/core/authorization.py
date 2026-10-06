"""Authorization for interactive (human) user requests.

There is no login yet. Every protected endpoint depends on
``require_permission(...)``, which resolves the requesting user through
``get_user_principal``. When authentication is added, only
``get_user_principal`` changes; endpoints and permission checks stay as they
are.

``USER_AUTH_MODE``:

- ``disabled`` (default): requests are anonymous and every protected endpoint
  answers 401.
- ``development-unauthenticated``: requests act as a fixed development user
  holding ``DEVELOPMENT_USER_PERMISSIONS``. Refused in production.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.core.config import Settings, get_settings
from app.core.permissions import Permission, grants

logger = logging.getLogger(__name__)

DEVELOPMENT_USER_ID = "development-user"


@dataclass(frozen=True)
class UserPrincipal:
    """The user a request is attributed to, and the permissions granted to them."""

    # None for anonymous requests.
    user_id: str | None
    authenticated: bool
    granted: frozenset[Permission]

    def has(self, permission: Permission) -> bool:
        return any(grants(held, permission) for held in self.granted)


ANONYMOUS = UserPrincipal(user_id=None, authenticated=False, granted=frozenset())


def get_user_principal(settings: Annotated[Settings, Depends(get_settings)]) -> UserPrincipal:
    # Settings already refuse the development mode in production; this check
    # keeps the dependency fail-closed even if settings are constructed directly.
    if (
        settings.user_auth_mode == "development-unauthenticated"
        and settings.environment != "production"
    ):
        return UserPrincipal(
            user_id=DEVELOPMENT_USER_ID,
            authenticated=False,
            granted=frozenset(settings.development_user_permissions),
        )
    return ANONYMOUS


def require_permission(permission: Permission) -> Callable[..., UserPrincipal]:
    """Dependency that admits only users holding ``permission``."""

    def dependency(
        principal: Annotated[UserPrincipal, Depends(get_user_principal)],
    ) -> UserPrincipal:
        if principal.has(permission):
            return principal
        if principal.user_id is None:
            logger.warning(
                "event=authorization result=denied reason=anonymous permission=%s", permission
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "authentication_required",
                    "message": "Sign-in is required. User authentication is not enabled yet.",
                },
            )
        logger.warning(
            "event=authorization result=denied reason=missing_permission permission=%s user=%s",
            permission,
            principal.user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "permission_denied",
                "message": "You do not have permission to perform this action.",
                "permission": permission.value,
            },
        )

    return dependency
