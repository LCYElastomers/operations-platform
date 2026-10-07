"""Platform permission catalog: the single source of permission names.

Names are ``<module>[.<function>].<action>``. A grant covers its own scope and
every function nested under it, so ``safety.view`` covers
``safety.incidents.view``; ``edit`` implies ``view`` at the same scope.
Endpoints require the most specific permission (for example
``safety.incidents.edit``), so finer-grained grants can be introduced later
without changing the endpoints.

Planned Safety functions follow the same scheme: ``safety.contacts.*``,
``safety.performance.view``. Add them here when the function is built.
"""

from collections.abc import Iterable
from enum import StrEnum


class Permission(StrEnum):
    SAFETY_VIEW = "safety.view"
    SAFETY_EDIT = "safety.edit"
    SAFETY_INCIDENTS_VIEW = "safety.incidents.view"
    SAFETY_INCIDENTS_EDIT = "safety.incidents.edit"
    SAFETY_OBSERVATIONS_VIEW = "safety.observations.view"
    SAFETY_OBSERVATIONS_EDIT = "safety.observations.edit"


_IMPLIED_ACTIONS = {"view": frozenset({"view"}), "edit": frozenset({"view", "edit"})}


def grants(granted: Permission, required: Permission) -> bool:
    """Whether holding ``granted`` satisfies a requirement for ``required``."""
    granted_scope, _, granted_action = granted.rpartition(".")
    required_scope, _, required_action = required.rpartition(".")
    if required_action not in _IMPLIED_ACTIONS.get(granted_action, frozenset()):
        return False
    return required_scope == granted_scope or required_scope.startswith(f"{granted_scope}.")


def effective_permissions(granted: Iterable[Permission]) -> frozenset[Permission]:
    """Every catalog permission satisfied by the granted set."""
    held = tuple(granted)
    return frozenset(p for p in Permission if any(grants(g, p) for g in held))
