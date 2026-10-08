"""Platform permission catalog: the single source of permission names.

Names are ``<module>[.<function>].<action>``. A grant covers its own scope and
every function nested under it, so ``safety.view`` covers
``safety.incidents.view``. Actions are ``view`` < ``edit`` < ``manage``: each
implies the ones before it at the same scope. ``manage`` is for corrections
that change what a record means (void, reclassify) and for administrative
imports, so ``edit`` alone never grants them.
Endpoints require the most specific permission (for example
``safety.incidents.records.edit``), so finer-grained grants can be introduced
later without changing the endpoints.

New functions follow the same scheme. Add them here when the function is built.
"""

from collections.abc import Iterable
from enum import StrEnum


class Permission(StrEnum):
    QUALITY_VIEW = "quality.view"
    QUALITY_MANAGE = "quality.manage"
    # Cost of Poor Quality and the Cost of Quality Matrix (read-only; incl. the estimator).
    QUALITY_COST_VIEW = "quality.cost.view"
    # Cost of Quality imports (operator command; no endpoint writes them).
    QUALITY_COST_MANAGE = "quality.cost.manage"
    SAFETY_VIEW = "safety.view"
    SAFETY_EDIT = "safety.edit"
    SAFETY_MANAGE = "safety.manage"
    SAFETY_INCIDENTS_VIEW = "safety.incidents.view"
    SAFETY_INCIDENTS_EDIT = "safety.incidents.edit"
    # Individual Incident and Near Miss records.
    SAFETY_INCIDENT_RECORDS_VIEW = "safety.incidents.records.view"
    SAFETY_INCIDENT_RECORDS_EDIT = "safety.incidents.records.edit"
    # Void and reclassify.
    SAFETY_INCIDENT_RECORDS_MANAGE = "safety.incidents.records.manage"
    # The audit history of a record.
    SAFETY_INCIDENT_HISTORY_VIEW = "safety.incidents.history.view"
    SAFETY_OBSERVATIONS_VIEW = "safety.observations.view"
    SAFETY_OBSERVATIONS_EDIT = "safety.observations.edit"
    SAFETY_PERFORMANCE_VIEW = "safety.performance.view"
    SAFETY_PERFORMANCE_EDIT = "safety.performance.edit"
    SAFETY_TRIR_VIEW = "safety.trir.view"
    # TRIR historical facts imports (operator command; no endpoint writes them).
    SAFETY_TRIR_MANAGE = "safety.trir.manage"


_IMPLIED_ACTIONS = {
    "view": frozenset({"view"}),
    "edit": frozenset({"view", "edit"}),
    "manage": frozenset({"view", "edit", "manage"}),
}


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
