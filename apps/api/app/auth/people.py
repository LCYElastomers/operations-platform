"""People on records: person fields that link platform users, and display names.

A person field stores the name as recorded plus, when known, the user's ID.
New values must be platform users chosen by ID; the server then records the
user's name itself. A name recorded before users existed (for example on an
imported report) is kept unchanged and is never matched to a user by guessing.
"""

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User


@dataclass(frozen=True)
class Person:
    name: str | None
    user_id: uuid.UUID | None


NOBODY = Person(None, None)


class PersonChoiceError(ValueError):
    """The value is neither a platform user nor the unchanged recorded name."""


def _clean(name: str | None) -> str | None:
    if name is None:
        return None
    return name.strip() or None


def resolve(
    db: Callable[[], Session],
    *,
    user_id: uuid.UUID | None,
    name: str | None,
    current: Person = NOBODY,
) -> Person:
    """The person to store for a field.

    - ``user_id`` given: that user, by their current name. Must be active,
      unless it is the user already recorded.
    - no ``user_id``: either nobody (blank name) or the recorded legacy name,
      unchanged. Any other free-text name is refused.

    ``db`` is called only when a user must be looked up.
    """
    if user_id is not None:
        user = db().get(User, user_id)
        if user is None or (user.status != "active" and user_id != current.user_id):
            raise PersonChoiceError
        return Person(user.name, user.id)
    text = _clean(name)
    if text is None:
        return NOBODY
    if current.user_id is None and text == current.name:
        return current
    raise PersonChoiceError


def is_active_user(db: Session, user_id: uuid.UUID | None) -> bool:
    if user_id is None:
        return False
    user = db.get(User, user_id)
    return user is not None and user.status == "active"


def display_names(db: Session, actor_ids: Iterable[str | None]) -> dict[str, str]:
    """Names of the users among ``actor_ids`` (created_by, updated_by...). System
    actors such as ``legacy-import`` are left out; callers show them as they are."""
    ids: set[uuid.UUID] = set()
    for actor_id in actor_ids:
        if not actor_id:
            continue
        try:
            ids.add(uuid.UUID(actor_id))
        except ValueError:
            continue
    if not ids:
        return {}
    return {
        str(user_id): name
        for user_id, name in db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    }


SYSTEM_ACTOR_NAMES = {
    "legacy-import": "Legacy import",
    "operator-cli": "Server administrator",
    "development-user": "Development user (before sign-in)",
}


def actor_label(actor_id: str, names: dict[str, str]) -> str:
    """How an actor is shown: the user's name, a system actor's label, or the ID."""
    return names.get(actor_id) or SYSTEM_ACTOR_NAMES.get(actor_id, actor_id)
