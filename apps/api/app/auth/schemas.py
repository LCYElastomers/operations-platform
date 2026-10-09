"""Sign-in, current-user and administration API models.

No response carries a password, password hash, session token or the hash of a
token. A password link token is returned once, to the administrator who
created it, so they can send it to the user.
"""

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from app.auth.models import ROLE_CODE_PATTERN
from app.core.schemas import CamelModel

Email = Annotated[str, Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
Name = Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]
Password = Annotated[str, Field(min_length=1, max_length=256)]
Token = Annotated[str, Field(min_length=20, max_length=200, pattern=r"^[A-Za-z0-9_\-]+$")]
RoleCode = Annotated[str, Field(pattern=ROLE_CODE_PATTERN)]
PermissionCode = Annotated[str, Field(max_length=100, pattern=r"^[a-zA-Z]+\.[a-zA-Z]+$")]
UserStatus = Literal["active", "inactive"]


class _Input(CamelModel):
    model_config = ConfigDict(extra="forbid")


class SignInRequest(_Input):
    email: Annotated[str, Field(min_length=1, max_length=254)]
    password: Password


class PasswordLinkSetRequest(_Input):
    token: Token
    password: Password


class PasswordLinkCheckRequest(_Input):
    token: Token


class PasswordChangeRequest(_Input):
    current_password: Password
    new_password: Password


class RoleRefOut(CamelModel):
    code: str
    name: str


class SessionUserOut(CamelModel):
    id: uuid.UUID
    name: str
    email: str
    image: str | None
    status: UserStatus


class MeResponse(CamelModel):
    """The signed-in user, their active roles and effective permissions."""

    user: SessionUserOut
    roles: list[RoleRefOut]
    permissions: list[str]


class PasswordLinkUserOut(CamelModel):
    name: str
    email: str


# --- Administration ---


class UserCreate(_Input):
    email: Email
    name: Name
    role_codes: Annotated[list[RoleCode], Field(max_length=20)] = []


class UserUpdate(_Input):
    email: Email
    name: Name
    image: Annotated[str, Field(max_length=2000, pattern=r"^https://\S+$")] | None = None


class UserRolesUpdate(_Input):
    role_codes: Annotated[list[RoleCode], Field(max_length=20)]


class UserOut(CamelModel):
    id: uuid.UUID
    email: str
    name: str
    image: str | None
    status: UserStatus
    roles: list[RoleRefOut]
    # False until the user sets a password with their setup link.
    password_set: bool
    locked: bool
    last_login_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime


class UserDetailOut(UserOut):
    permissions: list[str]


class UserListResponse(CamelModel):
    users: list[UserOut]


class PasswordLinkOut(CamelModel):
    """Shown once: the administrator sends it to the user. Not stored in readable form."""

    token: str
    expires_at: dt.datetime


class UserCreatedResponse(CamelModel):
    user: UserDetailOut
    password_link: PasswordLinkOut


class RoleCreate(_Input):
    code: RoleCode
    name: Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")]
    description: Annotated[str, Field(max_length=1000)] = ""
    permissions: Annotated[list[PermissionCode], Field(max_length=500)] = []


class RoleUpdate(_Input):
    name: Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")]
    description: Annotated[str, Field(max_length=1000)]
    active: bool


class RolePermissionsUpdate(_Input):
    permissions: Annotated[list[PermissionCode], Field(max_length=500)]


class RoleOut(CamelModel):
    code: str
    name: str
    description: str
    is_system: bool
    active: bool
    permissions: list[str]
    # Active users holding the role.
    user_count: int


class RoleListResponse(CamelModel):
    roles: list[RoleOut]


class PermissionOut(CamelModel):
    code: str
    module: str
    description: str


class PermissionListResponse(CamelModel):
    permissions: list[PermissionOut]


class DirectoryUserOut(CamelModel):
    """A user as offered in pickers: no email, roles or sign-in details."""

    id: uuid.UUID
    name: str
    active: bool


class DirectoryResponse(CamelModel):
    users: list[DirectoryUserOut]


class AuditEventOut(CamelModel):
    id: int
    occurred_at: dt.datetime
    actor_id: str
    actor_name: str | None
    action: str
    entity_type: str
    entity_key: str
    old_value: dict | None
    new_value: dict | None


class AuditListResponse(CamelModel):
    events: list[AuditEventOut]
    total: int
