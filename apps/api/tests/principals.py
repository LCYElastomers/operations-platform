"""Test fixture identities. ``TESTER`` is a fixture user, not a real account."""

import uuid

from app.core.authorization import UserPrincipal
from app.core.permissions import Permission

TESTER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
# The actor ID the API writes to created_by / updated_by / audit events.
TESTER = str(TESTER_ID)
TESTER_NAME = "Test User (fixture)"


def as_user(
    *permissions: Permission, user_id: uuid.UUID = TESTER_ID, name: str = TESTER_NAME
) -> UserPrincipal:
    """A signed-in fixture user holding exactly ``permissions``."""
    return UserPrincipal(
        user_id=user_id,
        name=name,
        email=f"{user_id.hex[:8]}@fixture.test",
        granted=frozenset(permissions),
    )
