"""users, roles, permissions and sessions

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-09 19:00:00

Platform sign-in and authorization, shared by every module (schema ``core``):

- ``core.users``: people who sign in. Never deleted; deactivated instead.
- ``core.roles``, ``core.permissions``, ``core.role_permissions``,
  ``core.user_roles``: a user's effective permissions are the union of the
  permissions of their active roles.
- ``core.sessions``, ``core.password_tokens``: sign-in sessions and one-time
  password setup/reset links, stored as SHA-256 hashes only.

Seeds the permission catalog and the seven standard roles with their initial
permissions. No user is created: the first administrator is created with
``python -m app.auth.cli bootstrap-admin``.

Also links records to users without rewriting history:

- ``core.audit_events`` gains ``actor_user_id`` and ``actor_name``. Existing
  events keep their ``actor_id`` text and get no link.
- Person fields of CARs and Quality Cost records gain a ``*_user_id`` link next
  to the recorded name. Existing records keep their names and get no link; a
  name is never matched to a user by guessing.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CORE = "core"
QUALITY = "quality"

# Frozen copy of app.core.permissions.Permission at this revision.
PERMISSIONS = (
    "app.view",
    "users.view",
    "users.create",
    "users.edit",
    "users.activate",
    "users.deactivate",
    "users.assignRoles",
    "users.manage",
    "roles.view",
    "roles.create",
    "roles.edit",
    "roles.delete",
    "roles.assignPermissions",
    "roles.manage",
    "audit.view",
    "quality.view",
    "quality.admin",
    "qualityCost.view",
    "qualityCost.create",
    "qualityCost.edit",
    "qualityCost.delete",
    "qualityCost.assign",
    "qualityCost.confirmFinancial",
    "qualityCost.close",
    "qualityCost.export",
    "car.view",
    "car.create",
    "car.edit",
    "car.delete",
    "car.assign",
    "car.manageActions",
    "car.completeAction",
    "car.reviewEffectiveness",
    "car.approve",
    "car.close",
    "car.reopen",
    "car.export",
    "car.admin",
    "safety.view",
    "safety.admin",
    "safetyRecord.view",
    "safetyRecord.create",
    "safetyRecord.edit",
    "safetyRecord.delete",
    "safetyRecord.assign",
    "safetyRecord.review",
    "safetyRecord.approve",
    "safetyRecord.close",
    "safetyRecord.reopen",
    "safetyRecord.export",
    "incident.view",
    "incident.create",
    "incident.edit",
    "incident.delete",
    "incident.assign",
    "incident.classify",
    "incident.investigate",
    "incident.review",
    "incident.approve",
    "incident.close",
    "incident.reopen",
    "incident.export",
    "nearMiss.view",
    "nearMiss.create",
    "nearMiss.edit",
    "nearMiss.delete",
    "nearMiss.assign",
    "nearMiss.investigate",
    "nearMiss.review",
    "nearMiss.close",
    "nearMiss.reopen",
    "nearMiss.export",
    "safetyObservation.view",
    "safetyObservation.create",
    "safetyObservation.edit",
    "safetyObservation.delete",
    "safetyObservation.assign",
    "safetyObservation.review",
    "safetyObservation.close",
    "safetyObservation.export",
    "safetyAction.view",
    "safetyAction.create",
    "safetyAction.edit",
    "safetyAction.delete",
    "safetyAction.assign",
    "safetyAction.complete",
    "safetyAction.verify",
    "safetyAction.approve",
    "safetyAction.close",
    "safetyAction.reopen",
    "safetyAction.export",
    "safetyInvestigation.view",
    "safetyInvestigation.create",
    "safetyInvestigation.edit",
    "safetyInvestigation.assign",
    "safetyInvestigation.complete",
    "safetyInvestigation.review",
    "safetyInvestigation.approve",
    "safetyInvestigation.close",
    "safetyInvestigation.reopen",
    "safetyInvestigation.export",
    "qualityDashboard.view",
    "safetyDashboard.view",
    "assignments.viewOwn",
    "assignments.updateOwn",
    "assignments.viewAll",
    "assignments.reassign",
    "attachments.view",
    "attachments.upload",
    "attachments.deleteOwn",
    "attachments.deleteAny",
    "comments.view",
    "comments.create",
    "comments.editOwn",
    "comments.deleteOwn",
    "comments.moderate",
)

MODULE_LABELS = {
    "app": "Application",
    "users": "Users",
    "roles": "Roles",
    "audit": "Audit",
    "quality": "Quality",
    "qualityCost": "Quality Cost",
    "car": "Corrective Action Reports",
    "safety": "Safety",
    "safetyRecord": "Safety records",
    "incident": "Incidents",
    "nearMiss": "Near misses",
    "safetyObservation": "Safety observations",
    "safetyAction": "Safety actions",
    "safetyInvestigation": "Safety investigations",
    "qualityDashboard": "Quality dashboards",
    "safetyDashboard": "Safety dashboards",
    "assignments": "Assignments",
    "attachments": "Attachments",
    "comments": "Comments",
}

_OWN = ("assignments.viewOwn", "assignments.updateOwn")
_ALL = (*_OWN, "assignments.viewAll", "assignments.reassign")
_ATTACH = ("attachments.view", "attachments.upload", "attachments.deleteOwn")
_ATTACH_ADMIN = (*_ATTACH, "attachments.deleteAny")
_COMMENT = ("comments.view", "comments.create", "comments.editOwn", "comments.deleteOwn")
_COMMENT_ADMIN = (*_COMMENT, "comments.moderate")


def _group(*prefixes: str) -> tuple[str, ...]:
    return tuple(p for p in PERMISSIONS if p.split(".", 1)[0] in prefixes)


ROLES = (
    (
        "ADMIN",
        "Administrator",
        "Full Operations Platform administration: users, roles and permissions, and every "
        "Quality and Safety function.",
    ),
    (
        "QUALITY_ADMIN",
        "Quality Administrator",
        "Administers Quality: Quality Cost, CARs, assignment, approval and closure. No user, "
        "role or Safety administration.",
    ),
    (
        "QUALITY_USER",
        "Quality User",
        "Views Quality, enters Quality Cost records and CARs, and works assigned corrective "
        "actions. Does not approve or close CARs.",
    ),
    (
        "SAFETY_ADMIN",
        "Safety Administrator",
        "Administers Safety records, incidents, near misses and observations, including "
        "review, approval and closure. No user, role or Quality administration.",
    ),
    (
        "SAFETY_USER",
        "Safety User",
        "Views Safety and enters and updates Safety records and observations. Does not "
        "approve or close records.",
    ),
    (
        "CONTRIBUTOR",
        "Contributor",
        "Works the records and actions assigned to them. No module administration.",
    ),
    ("VIEWER", "Viewer", "Read-only access to Quality and Safety."),
)

ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "ADMIN": PERMISSIONS,
    "QUALITY_ADMIN": (
        "app.view",
        "quality.view",
        "quality.admin",
        "qualityDashboard.view",
        *_group("qualityCost", "car"),
        *_ALL,
        *_ATTACH_ADMIN,
        *_COMMENT_ADMIN,
    ),
    "QUALITY_USER": (
        "app.view",
        "quality.view",
        "qualityDashboard.view",
        "qualityCost.view",
        "qualityCost.create",
        "qualityCost.edit",
        "qualityCost.export",
        "car.view",
        "car.create",
        "car.edit",
        "car.manageActions",
        "car.completeAction",
        *_OWN,
        *_ATTACH,
        *_COMMENT,
    ),
    "SAFETY_ADMIN": (
        "app.view",
        "safety.view",
        "safety.admin",
        "safetyDashboard.view",
        *_group(
            "safetyRecord",
            "incident",
            "nearMiss",
            "safetyObservation",
            "safetyAction",
            "safetyInvestigation",
        ),
        *_ALL,
        *_ATTACH_ADMIN,
        *_COMMENT_ADMIN,
    ),
    "SAFETY_USER": (
        "app.view",
        "safety.view",
        "safetyDashboard.view",
        "safetyRecord.view",
        "safetyRecord.create",
        "safetyRecord.edit",
        "incident.view",
        "incident.create",
        "incident.edit",
        "incident.investigate",
        "nearMiss.view",
        "nearMiss.create",
        "nearMiss.edit",
        "nearMiss.investigate",
        "safetyObservation.view",
        "safetyObservation.create",
        "safetyObservation.edit",
        "safetyAction.view",
        "safetyAction.create",
        "safetyAction.edit",
        "safetyAction.complete",
        "safetyInvestigation.view",
        "safetyInvestigation.create",
        "safetyInvestigation.edit",
        "safetyInvestigation.complete",
        *_OWN,
        *_ATTACH,
        *_COMMENT,
    ),
    "CONTRIBUTOR": ("app.view", *_OWN, *_ATTACH, *_COMMENT),
    "VIEWER": (
        "app.view",
        "quality.view",
        "qualityDashboard.view",
        "qualityCost.view",
        "car.view",
        "safety.view",
        "safetyDashboard.view",
        "safetyRecord.view",
        "incident.view",
        "nearMiss.view",
        "safetyObservation.view",
        "safetyAction.view",
        "safetyInvestigation.view",
        "attachments.view",
        "comments.view",
        "assignments.viewOwn",
    ),
}

# (table, column) person fields that gain a user link.
USER_LINKS = (
    ("cars", "requested_by_user_id"),
    ("cars", "assigned_to_user_id"),
    ("cars", "closure_approved_by_user_id"),
    ("cars", "containment_owner_user_id"),
    ("cars", "reviewer_user_id"),
    ("car_actions", "owner_user_id"),
    ("car_approvals", "user_id"),
    ("cost_records", "owner_user_id"),
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _description(code: str) -> str:
    module, action = code.split(".", 1)
    return f"{MODULE_LABELS[module]}: {action}"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("image", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("failed_logins", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_users_status"),
        sa.CheckConstraint(
            "email = lower(btrim(email)) AND char_length(email) BETWEEN 3 AND 254",
            name="ck_users_email",
        ),
        sa.CheckConstraint("btrim(name) <> '' AND char_length(name) <= 200", name="ck_users_name"),
        sa.CheckConstraint("image IS NULL OR char_length(image) <= 2000", name="ck_users_image"),
        sa.CheckConstraint("failed_logins >= 0", name="ck_users_failed_logins"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        schema=CORE,
    )
    op.create_index("uq_users_email", "users", ["email"], unique=True, schema=CORE)

    op.create_table(
        "roles",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("code ~ '^[A-Z][A-Z0-9_]{1,49}$'", name="ck_roles_code"),
        sa.CheckConstraint("btrim(name) <> '' AND char_length(name) <= 100", name="ck_roles_name"),
        sa.CheckConstraint("char_length(description) <= 1000", name="ck_roles_description"),
        sa.PrimaryKeyConstraint("code", name="pk_roles"),
        schema=CORE,
    )

    op.create_table(
        "permissions",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("module", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code", name="pk_permissions"),
        schema=CORE,
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_code", sa.Text(), nullable=False),
        sa.Column("permission_code", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_code"], [f"{CORE}.roles.code"], name="fk_role_permissions_role", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["permission_code"],
            [f"{CORE}.permissions.code"],
            name="fk_role_permissions_permission",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("role_code", "permission_code", name="pk_role_permissions"),
        schema=CORE,
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_code", sa.Text(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("assigned_by", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{CORE}.users.id"], name="fk_user_roles_user", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["role_code"], [f"{CORE}.roles.code"], name="fk_user_roles_role", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("user_id", "role_code", name="pk_user_roles"),
        schema=CORE,
    )
    op.create_index("ix_user_roles_role", "user_roles", ["role_code"], schema=CORE)

    op.create_table(
        "sessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{CORE}.users.id"], name="fk_sessions_user", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        schema=CORE,
    )
    op.create_index("uq_sessions_token_hash", "sessions", ["token_hash"], unique=True, schema=CORE)
    op.create_index("ix_sessions_user", "sessions", ["user_id"], schema=CORE)

    op.create_table(
        "password_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("purpose IN ('setup', 'reset')", name="ck_password_tokens_purpose"),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{CORE}.users.id"], name="fk_password_tokens_user", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_password_tokens"),
        schema=CORE,
    )
    op.create_index(
        "uq_password_tokens_token_hash", "password_tokens", ["token_hash"], unique=True, schema=CORE
    )
    op.create_index("ix_password_tokens_user", "password_tokens", ["user_id"], schema=CORE)

    permissions = sa.table(
        "permissions",
        sa.column("code", sa.Text()),
        sa.column("module", sa.Text()),
        sa.column("description", sa.Text()),
        schema=CORE,
    )
    op.bulk_insert(
        permissions,
        [
            {"code": code, "module": code.split(".", 1)[0], "description": _description(code)}
            for code in PERMISSIONS
        ],
    )
    roles = sa.table(
        "roles",
        sa.column("code", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("description", sa.Text()),
        sa.column("is_system", sa.Boolean()),
        schema=CORE,
    )
    op.bulk_insert(
        roles,
        [
            {"code": code, "name": name, "description": description, "is_system": True}
            for code, name, description in ROLES
        ],
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_code", sa.Text()),
        sa.column("permission_code", sa.Text()),
        schema=CORE,
    )
    op.bulk_insert(
        role_permissions,
        [
            {"role_code": role, "permission_code": code}
            for role, codes in ROLE_PERMISSIONS.items()
            for code in dict.fromkeys(codes)
        ],
    )

    op.add_column("audit_events", sa.Column("actor_user_id", sa.Uuid(), nullable=True), schema=CORE)
    op.add_column("audit_events", sa.Column("actor_name", sa.Text(), nullable=True), schema=CORE)
    op.create_foreign_key(
        "fk_audit_events_actor_user",
        "audit_events",
        "users",
        ["actor_user_id"],
        ["id"],
        source_schema=CORE,
        referent_schema=CORE,
        ondelete="RESTRICT",
    )

    for table, column in USER_LINKS:
        op.add_column(table, sa.Column(column, sa.Uuid(), nullable=True), schema=QUALITY)
        op.create_foreign_key(
            f"fk_{table}_{column}_users",
            table,
            "users",
            [column],
            ["id"],
            source_schema=QUALITY,
            referent_schema=CORE,
            ondelete="RESTRICT",
        )
        op.create_index(f"ix_{QUALITY}_{table}_{column}", table, [column], schema=QUALITY)


# Removing users would lose who did what.
DOWNGRADE_GUARD = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM {CORE}.users) THEN
            RAISE EXCEPTION 'Cannot downgrade: platform users exist';
        END IF;
    END
    $$
"""


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_GUARD))
    for table, column in reversed(USER_LINKS):
        op.drop_index(f"ix_{QUALITY}_{table}_{column}", table_name=table, schema=QUALITY)
        op.drop_constraint(f"fk_{table}_{column}_users", table, type_="foreignkey", schema=QUALITY)
        op.drop_column(table, column, schema=QUALITY)
    op.drop_constraint("fk_audit_events_actor_user", "audit_events", type_="foreignkey", schema=CORE)
    op.drop_column("audit_events", "actor_name", schema=CORE)
    op.drop_column("audit_events", "actor_user_id", schema=CORE)
    op.drop_table("password_tokens", schema=CORE)
    op.drop_table("sessions", schema=CORE)
    op.drop_table("user_roles", schema=CORE)
    op.drop_table("role_permissions", schema=CORE)
    op.drop_table("permissions", schema=CORE)
    op.drop_table("roles", schema=CORE)
    op.drop_table("users", schema=CORE)
