"""Platform permission catalog: the single source of permission names.

Roles grant permissions and permissions authorize actions. A user's effective
permissions are the union of the permissions of their active roles; nothing is
implied by a name, so ``qualityCost.edit`` does not include ``qualityCost.view``
unless a role grants both.

Persistent copies live in ``core.permissions`` (seeded by migration 0013); a
test keeps the two in step. Groups for features not built yet (attachments,
comments, Safety actions and investigations) are defined so roles can hold them
when the features arrive; no endpoint uses them today.
"""

from enum import StrEnum


class Permission(StrEnum):
    APP_VIEW = "app.view"

    USERS_VIEW = "users.view"
    USERS_CREATE = "users.create"
    USERS_EDIT = "users.edit"
    USERS_ACTIVATE = "users.activate"
    USERS_DEACTIVATE = "users.deactivate"
    USERS_ASSIGN_ROLES = "users.assignRoles"
    USERS_MANAGE = "users.manage"

    ROLES_VIEW = "roles.view"
    ROLES_CREATE = "roles.create"
    ROLES_EDIT = "roles.edit"
    ROLES_DELETE = "roles.delete"
    ROLES_ASSIGN_PERMISSIONS = "roles.assignPermissions"
    ROLES_MANAGE = "roles.manage"

    AUDIT_VIEW = "audit.view"

    QUALITY_VIEW = "quality.view"
    QUALITY_ADMIN = "quality.admin"

    QUALITY_COST_VIEW = "qualityCost.view"
    QUALITY_COST_CREATE = "qualityCost.create"
    QUALITY_COST_EDIT = "qualityCost.edit"
    QUALITY_COST_DELETE = "qualityCost.delete"
    QUALITY_COST_ASSIGN = "qualityCost.assign"
    QUALITY_COST_CONFIRM_FINANCIAL = "qualityCost.confirmFinancial"
    QUALITY_COST_CLOSE = "qualityCost.close"
    QUALITY_COST_EXPORT = "qualityCost.export"

    CAR_VIEW = "car.view"
    CAR_CREATE = "car.create"
    CAR_EDIT = "car.edit"
    CAR_DELETE = "car.delete"
    CAR_ASSIGN = "car.assign"
    CAR_MANAGE_ACTIONS = "car.manageActions"
    CAR_COMPLETE_ACTION = "car.completeAction"
    CAR_REVIEW_EFFECTIVENESS = "car.reviewEffectiveness"
    CAR_APPROVE = "car.approve"
    CAR_CLOSE = "car.close"
    CAR_REOPEN = "car.reopen"
    CAR_EXPORT = "car.export"
    CAR_ADMIN = "car.admin"

    SAFETY_VIEW = "safety.view"
    SAFETY_ADMIN = "safety.admin"

    SAFETY_RECORD_VIEW = "safetyRecord.view"
    SAFETY_RECORD_CREATE = "safetyRecord.create"
    SAFETY_RECORD_EDIT = "safetyRecord.edit"
    SAFETY_RECORD_DELETE = "safetyRecord.delete"
    SAFETY_RECORD_ASSIGN = "safetyRecord.assign"
    SAFETY_RECORD_REVIEW = "safetyRecord.review"
    SAFETY_RECORD_APPROVE = "safetyRecord.approve"
    SAFETY_RECORD_CLOSE = "safetyRecord.close"
    SAFETY_RECORD_REOPEN = "safetyRecord.reopen"
    SAFETY_RECORD_EXPORT = "safetyRecord.export"

    INCIDENT_VIEW = "incident.view"
    INCIDENT_CREATE = "incident.create"
    INCIDENT_EDIT = "incident.edit"
    INCIDENT_DELETE = "incident.delete"
    INCIDENT_ASSIGN = "incident.assign"
    INCIDENT_CLASSIFY = "incident.classify"
    INCIDENT_INVESTIGATE = "incident.investigate"
    INCIDENT_REVIEW = "incident.review"
    INCIDENT_APPROVE = "incident.approve"
    INCIDENT_CLOSE = "incident.close"
    INCIDENT_REOPEN = "incident.reopen"
    INCIDENT_EXPORT = "incident.export"

    NEAR_MISS_VIEW = "nearMiss.view"
    NEAR_MISS_CREATE = "nearMiss.create"
    NEAR_MISS_EDIT = "nearMiss.edit"
    NEAR_MISS_DELETE = "nearMiss.delete"
    NEAR_MISS_ASSIGN = "nearMiss.assign"
    NEAR_MISS_INVESTIGATE = "nearMiss.investigate"
    NEAR_MISS_REVIEW = "nearMiss.review"
    NEAR_MISS_CLOSE = "nearMiss.close"
    NEAR_MISS_REOPEN = "nearMiss.reopen"
    NEAR_MISS_EXPORT = "nearMiss.export"

    SAFETY_OBSERVATION_VIEW = "safetyObservation.view"
    SAFETY_OBSERVATION_CREATE = "safetyObservation.create"
    SAFETY_OBSERVATION_EDIT = "safetyObservation.edit"
    SAFETY_OBSERVATION_DELETE = "safetyObservation.delete"
    SAFETY_OBSERVATION_ASSIGN = "safetyObservation.assign"
    SAFETY_OBSERVATION_REVIEW = "safetyObservation.review"
    SAFETY_OBSERVATION_CLOSE = "safetyObservation.close"
    SAFETY_OBSERVATION_EXPORT = "safetyObservation.export"

    SAFETY_ACTION_VIEW = "safetyAction.view"
    SAFETY_ACTION_CREATE = "safetyAction.create"
    SAFETY_ACTION_EDIT = "safetyAction.edit"
    SAFETY_ACTION_DELETE = "safetyAction.delete"
    SAFETY_ACTION_ASSIGN = "safetyAction.assign"
    SAFETY_ACTION_COMPLETE = "safetyAction.complete"
    SAFETY_ACTION_VERIFY = "safetyAction.verify"
    SAFETY_ACTION_APPROVE = "safetyAction.approve"
    SAFETY_ACTION_CLOSE = "safetyAction.close"
    SAFETY_ACTION_REOPEN = "safetyAction.reopen"
    SAFETY_ACTION_EXPORT = "safetyAction.export"

    SAFETY_INVESTIGATION_VIEW = "safetyInvestigation.view"
    SAFETY_INVESTIGATION_CREATE = "safetyInvestigation.create"
    SAFETY_INVESTIGATION_EDIT = "safetyInvestigation.edit"
    SAFETY_INVESTIGATION_ASSIGN = "safetyInvestigation.assign"
    SAFETY_INVESTIGATION_COMPLETE = "safetyInvestigation.complete"
    SAFETY_INVESTIGATION_REVIEW = "safetyInvestigation.review"
    SAFETY_INVESTIGATION_APPROVE = "safetyInvestigation.approve"
    SAFETY_INVESTIGATION_CLOSE = "safetyInvestigation.close"
    SAFETY_INVESTIGATION_REOPEN = "safetyInvestigation.reopen"
    SAFETY_INVESTIGATION_EXPORT = "safetyInvestigation.export"

    QUALITY_DASHBOARD_VIEW = "qualityDashboard.view"
    SAFETY_DASHBOARD_VIEW = "safetyDashboard.view"

    ASSIGNMENTS_VIEW_OWN = "assignments.viewOwn"
    ASSIGNMENTS_UPDATE_OWN = "assignments.updateOwn"
    ASSIGNMENTS_VIEW_ALL = "assignments.viewAll"
    ASSIGNMENTS_REASSIGN = "assignments.reassign"

    ATTACHMENTS_VIEW = "attachments.view"
    ATTACHMENTS_UPLOAD = "attachments.upload"
    ATTACHMENTS_DELETE_OWN = "attachments.deleteOwn"
    ATTACHMENTS_DELETE_ANY = "attachments.deleteAny"

    COMMENTS_VIEW = "comments.view"
    COMMENTS_CREATE = "comments.create"
    COMMENTS_EDIT_OWN = "comments.editOwn"
    COMMENTS_DELETE_OWN = "comments.deleteOwn"
    COMMENTS_MODERATE = "comments.moderate"


def module_of(permission: Permission) -> str:
    """The group a permission belongs to, e.g. ``qualityCost`` for ``qualityCost.edit``."""
    return permission.value.split(".", 1)[0]
