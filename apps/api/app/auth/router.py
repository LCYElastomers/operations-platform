"""Sign-in endpoints (``/auth``).

The session lives in an HttpOnly cookie set here; the browser never sees the
token through JavaScript. Every POST must carry the application header (see
``app.core.authorization``), including sign-in, so another site cannot sign a
visitor in or out.
"""

import datetime as dt
import logging
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import service, sessions
from app.auth.credentials import WeakPasswordError
from app.auth.models import Role
from app.auth.schemas import (
    MeResponse,
    PasswordChangeRequest,
    PasswordLinkCheckRequest,
    PasswordLinkSetRequest,
    PasswordLinkUserOut,
    RoleRefOut,
    SessionUserOut,
    SignInRequest,
)
from app.core.authorization import (
    CSRF_HEADER,
    CSRF_VALUE,
    UserPrincipal,
    require_user,
)
from app.core.config import Settings, get_settings
from app.db.session import DatabaseNotConfiguredError, get_sessionmaker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

SIGN_IN_FAILED = "The email or password is incorrect."
LINK_INVALID = (
    "This link is invalid, has expired or has already been used. "
    "Ask an administrator for a new one."
)


def _error(status_code: int, error: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error": error, "message": message, **extra}
    )


def _unavailable() -> HTTPException:
    return _error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "database_unavailable",
        "Sign-in is unavailable because the database could not be reached.",
    )


def database() -> Iterator[Session]:
    try:
        maker = get_sessionmaker()
    except DatabaseNotConfiguredError:
        raise _unavailable() from None
    with maker() as db:
        yield db


def require_app_header(request: Request) -> None:
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "csrf_check_failed",
            "This request was refused because it did not come from the application.",
        )


Db = Annotated[Session, Depends(database)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
SignedIn = Annotated[UserPrincipal, Depends(require_user)]
AppHeader = Depends(require_app_header)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def me_response(db: Session, principal: UserPrincipal) -> MeResponse:
    names = dict(
        db.execute(select(Role.code, Role.name).where(Role.code.in_(principal.roles))).all()
    )
    assert principal.user_id is not None  # noqa: S101 - signed in
    return MeResponse(
        user=SessionUserOut(
            id=principal.user_id,
            name=principal.name or "",
            email=principal.email or "",
            image=principal.image,
            status="active",
        ),
        roles=[RoleRefOut(code=c, name=names.get(c, c)) for c in principal.roles],
        permissions=sorted(p.value for p in principal.granted),
    )


@router.post("/sign-in", status_code=status.HTTP_204_NO_CONTENT, dependencies=[AppHeader])
def sign_in(request: SignInRequest, response: Response, db: Db, settings: SettingsDep) -> Response:
    """Check the email and password and start a session (cookie)."""
    try:
        _, token = service.sign_in(db, request.email, request.password, settings, _now())
    except service.SignInFailedError:
        raise _error(status.HTTP_401_UNAUTHORIZED, "sign_in_failed", SIGN_IN_FAILED) from None
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    response.status_code = status.HTTP_204_NO_CONTENT
    sessions.set_session_cookie(response, token, settings)
    return response


@router.post("/sign-out", status_code=status.HTTP_204_NO_CONTENT, dependencies=[AppHeader])
def sign_out(http: Request, response: Response, db: Db, settings: SettingsDep) -> Response:
    token = http.cookies.get(sessions.cookie_name(settings))
    if token and len(token) <= 200:
        try:
            service.sign_out(db, token, _now())
        except SQLAlchemyError:
            db.rollback()
            raise _unavailable() from None
    response.status_code = status.HTTP_204_NO_CONTENT
    sessions.clear_session_cookie(response, settings)
    return response


@router.get("/me", response_model=MeResponse)
def me(principal: SignedIn, db: Db) -> MeResponse:
    """The signed-in user, their roles and effective permissions; 401 when signed out."""
    try:
        return me_response(db, principal)
    except SQLAlchemyError:
        raise _unavailable() from None


@router.post("/password-link/check", response_model=PasswordLinkUserOut, dependencies=[AppHeader])
def check_password_link(request: PasswordLinkCheckRequest, db: Db) -> PasswordLinkUserOut:
    """Whom a setup or reset link belongs to, if it is still valid."""
    try:
        user = service.check_password_link(db, request.token, _now())
    except service.PasswordLinkInvalidError:
        raise _error(status.HTTP_400_BAD_REQUEST, "link_invalid", LINK_INVALID) from None
    except SQLAlchemyError:
        raise _unavailable() from None
    return PasswordLinkUserOut(name=user.name, email=user.email)


@router.post("/password-link", status_code=status.HTTP_204_NO_CONTENT, dependencies=[AppHeader])
def set_password_with_link(request: PasswordLinkSetRequest, db: Db) -> Response:
    """Set a password with a one-time link. The user then signs in."""
    try:
        service.set_password_with_link(db, request.token, request.password, _now())
    except service.PasswordLinkInvalidError:
        db.rollback()
        raise _error(status.HTTP_400_BAD_REQUEST, "link_invalid", LINK_INVALID) from None
    except WeakPasswordError as error:
        db.rollback()
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "weak_password", str(error), field="password"
        ) from None
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(principal: SignedIn, request: PasswordChangeRequest, db: Db) -> Response:
    """Change your own password. Your other sessions end."""
    assert principal.user_id is not None  # noqa: S101 - signed in
    try:
        service.change_password(
            db,
            principal.user_id,
            request.current_password,
            request.new_password,
            _now(),
            keep_session_id=principal.session_id,
        )
    except service.SignInFailedError:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "current_password_incorrect",
            "The current password is incorrect.",
            field="currentPassword",
        ) from None
    except WeakPasswordError as error:
        db.rollback()
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "weak_password", str(error), field="newPassword"
        ) from None
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
