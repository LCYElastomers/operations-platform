"""The standard roles and their initial permissions.

Migration 0013 seeds these into ``core.roles`` and ``core.role_permissions``
(with its own frozen copy; a test keeps the two equal). After that the
database is authoritative: administrators may change a role's permissions,
but standard roles cannot be deleted. ADMIN is the only standard role holding
``users.manage`` and ``roles.manage``.
"""

from dataclasses import dataclass

from app.core.permissions import Permission as P


@dataclass(frozen=True)
class RoleDefinition:
    code: str
    name: str
    description: str
    permissions: frozenset[P]


ADMIN_CODE = "ADMIN"

_ASSIGNMENTS_OWN = {P.ASSIGNMENTS_VIEW_OWN, P.ASSIGNMENTS_UPDATE_OWN}
_ASSIGNMENTS_ALL = _ASSIGNMENTS_OWN | {P.ASSIGNMENTS_VIEW_ALL, P.ASSIGNMENTS_REASSIGN}
_ATTACHMENTS_USER = {P.ATTACHMENTS_VIEW, P.ATTACHMENTS_UPLOAD, P.ATTACHMENTS_DELETE_OWN}
_ATTACHMENTS_ADMIN = _ATTACHMENTS_USER | {P.ATTACHMENTS_DELETE_ANY}
_COMMENTS_USER = {P.COMMENTS_VIEW, P.COMMENTS_CREATE, P.COMMENTS_EDIT_OWN, P.COMMENTS_DELETE_OWN}
_COMMENTS_ADMIN = _COMMENTS_USER | {P.COMMENTS_MODERATE}


def _group(prefix: str) -> set[P]:
    return {p for p in P if p.value.startswith(f"{prefix}.")}


QUALITY_ADMIN = (
    {P.APP_VIEW, P.QUALITY_VIEW, P.QUALITY_ADMIN, P.QUALITY_DASHBOARD_VIEW}
    | _group("qualityCost")
    | _group("car")
    | _ASSIGNMENTS_ALL
    | _ATTACHMENTS_ADMIN
    | _COMMENTS_ADMIN
)

QUALITY_USER = (
    {
        P.APP_VIEW,
        P.QUALITY_VIEW,
        P.QUALITY_DASHBOARD_VIEW,
        P.QUALITY_COST_VIEW,
        P.QUALITY_COST_CREATE,
        P.QUALITY_COST_EDIT,
        P.QUALITY_COST_EXPORT,
        P.CAR_VIEW,
        P.CAR_CREATE,
        P.CAR_EDIT,
        P.CAR_MANAGE_ACTIONS,
        P.CAR_COMPLETE_ACTION,
    }
    | _ASSIGNMENTS_OWN
    | _ATTACHMENTS_USER
    | _COMMENTS_USER
)

SAFETY_ADMIN = (
    {P.APP_VIEW, P.SAFETY_VIEW, P.SAFETY_ADMIN, P.SAFETY_DASHBOARD_VIEW}
    | _group("safetyRecord")
    | _group("incident")
    | _group("nearMiss")
    | _group("safetyObservation")
    | _group("safetyAction")
    | _group("safetyInvestigation")
    | _ASSIGNMENTS_ALL
    | _ATTACHMENTS_ADMIN
    | _COMMENTS_ADMIN
)

SAFETY_USER = (
    {
        P.APP_VIEW,
        P.SAFETY_VIEW,
        P.SAFETY_DASHBOARD_VIEW,
        P.SAFETY_RECORD_VIEW,
        P.SAFETY_RECORD_CREATE,
        P.SAFETY_RECORD_EDIT,
        P.INCIDENT_VIEW,
        P.INCIDENT_CREATE,
        P.INCIDENT_EDIT,
        P.INCIDENT_INVESTIGATE,
        P.NEAR_MISS_VIEW,
        P.NEAR_MISS_CREATE,
        P.NEAR_MISS_EDIT,
        P.NEAR_MISS_INVESTIGATE,
        P.SAFETY_OBSERVATION_VIEW,
        P.SAFETY_OBSERVATION_CREATE,
        P.SAFETY_OBSERVATION_EDIT,
        P.SAFETY_ACTION_VIEW,
        P.SAFETY_ACTION_CREATE,
        P.SAFETY_ACTION_EDIT,
        P.SAFETY_ACTION_COMPLETE,
        P.SAFETY_INVESTIGATION_VIEW,
        P.SAFETY_INVESTIGATION_CREATE,
        P.SAFETY_INVESTIGATION_EDIT,
        P.SAFETY_INVESTIGATION_COMPLETE,
    }
    | _ASSIGNMENTS_OWN
    | _ATTACHMENTS_USER
    | _COMMENTS_USER
)

CONTRIBUTOR = {P.APP_VIEW} | _ASSIGNMENTS_OWN | _ATTACHMENTS_USER | _COMMENTS_USER

VIEWER = {
    P.APP_VIEW,
    P.QUALITY_VIEW,
    P.QUALITY_DASHBOARD_VIEW,
    P.QUALITY_COST_VIEW,
    P.CAR_VIEW,
    P.SAFETY_VIEW,
    P.SAFETY_DASHBOARD_VIEW,
    P.SAFETY_RECORD_VIEW,
    P.INCIDENT_VIEW,
    P.NEAR_MISS_VIEW,
    P.SAFETY_OBSERVATION_VIEW,
    P.SAFETY_ACTION_VIEW,
    P.SAFETY_INVESTIGATION_VIEW,
    P.ATTACHMENTS_VIEW,
    P.COMMENTS_VIEW,
    P.ASSIGNMENTS_VIEW_OWN,
}

STANDARD_ROLES: tuple[RoleDefinition, ...] = (
    RoleDefinition(
        ADMIN_CODE,
        "Administrator",
        "Full Operations Platform administration: users, roles and permissions, and every "
        "Quality and Safety function.",
        frozenset(P),
    ),
    RoleDefinition(
        "QUALITY_ADMIN",
        "Quality Administrator",
        "Administers Quality: Quality Cost, CARs, assignment, approval and closure. No user, "
        "role or Safety administration.",
        frozenset(QUALITY_ADMIN),
    ),
    RoleDefinition(
        "QUALITY_USER",
        "Quality User",
        "Views Quality, enters Quality Cost records and CARs, and works assigned corrective "
        "actions. Does not approve or close CARs.",
        frozenset(QUALITY_USER),
    ),
    RoleDefinition(
        "SAFETY_ADMIN",
        "Safety Administrator",
        "Administers Safety records, incidents, near misses and observations, including "
        "review, approval and closure. No user, role or Quality administration.",
        frozenset(SAFETY_ADMIN),
    ),
    RoleDefinition(
        "SAFETY_USER",
        "Safety User",
        "Views Safety and enters and updates Safety records and observations. Does not "
        "approve or close records.",
        frozenset(SAFETY_USER),
    ),
    RoleDefinition(
        "CONTRIBUTOR",
        "Contributor",
        "Works the records and actions assigned to them. No module administration.",
        frozenset(CONTRIBUTOR),
    ),
    RoleDefinition(
        "VIEWER",
        "Viewer",
        "Read-only access to Quality and Safety.",
        frozenset(VIEWER),
    ),
)
