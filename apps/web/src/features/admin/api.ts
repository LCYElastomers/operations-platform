import { ApiError, apiGet, apiSend } from "@/lib/api-client";

import type { RoleRef } from "../auth/api";

export type UserStatus = "active" | "inactive";

export type AdminUser = {
  id: string;
  email: string;
  name: string;
  image: string | null;
  status: UserStatus;
  roles: RoleRef[];
  /** False until the user sets a password with their setup link. */
  passwordSet: boolean;
  locked: boolean;
  lastLoginAt: string | null;
  createdAt: string;
  updatedAt: string;
};

export type AdminUserDetail = AdminUser & { permissions: string[] };

/** Returned once; the token is never stored in readable form. */
export type PasswordLink = { token: string; expiresAt: string };

export type Role = {
  code: string;
  name: string;
  description: string;
  isSystem: boolean;
  active: boolean;
  permissions: string[];
  /** Active users holding the role. */
  userCount: number;
};

export type PermissionInfo = { code: string; module: string; description: string };

export type AuditEvent = {
  id: number;
  occurredAt: string;
  actorId: string;
  actorName: string | null;
  action: string;
  entityType: string;
  entityKey: string;
  oldValue: Record<string, unknown> | null;
  newValue: Record<string, unknown> | null;
};

export type DirectoryUser = { id: string; name: string; active: boolean };

export const ROLE_CODE_PATTERN = /^[A-Z][A-Z0-9_]{1,49}$/;

const BASE = "/api/v1/admin";

export const adminKeys = {
  all: ["admin"] as const,
  users: () => [...adminKeys.all, "users"] as const,
  user: (id: string) => [...adminKeys.users(), id] as const,
  roles: () => [...adminKeys.all, "roles"] as const,
  permissions: () => [...adminKeys.all, "permissions"] as const,
  audit: (query: AuditQuery) => [...adminKeys.all, "audit", query] as const,
  directory: (includeInactive: boolean) => ["users", "directory", includeInactive] as const,
};

export const fetchUsers = (signal?: AbortSignal) =>
  apiGet<{ users: AdminUser[] }>(`${BASE}/users`, { signal }).then((body) => body.users);

export const fetchUser = (id: string, signal?: AbortSignal) =>
  apiGet<AdminUserDetail>(`${BASE}/users/${encodeURIComponent(id)}`, { signal });

export const createUser = (body: { email: string; name: string; roleCodes: string[] }) =>
  apiSend<{ user: AdminUserDetail; passwordLink: PasswordLink }>("POST", `${BASE}/users`, body);

export const updateUser = (id: string, body: { email: string; name: string; image: string | null }) =>
  apiSend<AdminUserDetail>("PUT", `${BASE}/users/${encodeURIComponent(id)}`, body);

export const setUserActive = (id: string, active: boolean) =>
  apiSend<AdminUserDetail>("POST", `${BASE}/users/${encodeURIComponent(id)}/${active ? "activate" : "deactivate"}`);

export const setUserRoles = (id: string, roleCodes: string[]) =>
  apiSend<AdminUserDetail>("PUT", `${BASE}/users/${encodeURIComponent(id)}/roles`, { roleCodes });

export const issuePasswordLink = (id: string) =>
  apiSend<PasswordLink>("POST", `${BASE}/users/${encodeURIComponent(id)}/password-link`);

export const fetchRoles = (signal?: AbortSignal) =>
  apiGet<{ roles: Role[] }>(`${BASE}/roles`, { signal }).then((body) => body.roles);

export const fetchPermissions = (signal?: AbortSignal) =>
  apiGet<{ permissions: PermissionInfo[] }>(`${BASE}/permissions`, { signal }).then((body) => body.permissions);

export const createRole = (body: { code: string; name: string; description: string; permissions: string[] }) =>
  apiSend<Role>("POST", `${BASE}/roles`, body);

export const updateRole = (code: string, body: { name: string; description: string; active: boolean }) =>
  apiSend<Role>("PUT", `${BASE}/roles/${encodeURIComponent(code)}`, body);

export const setRolePermissions = (code: string, permissions: string[]) =>
  apiSend<Role>("PUT", `${BASE}/roles/${encodeURIComponent(code)}/permissions`, { permissions });

export const deleteRole = (code: string) => apiSend<void>("DELETE", `${BASE}/roles/${encodeURIComponent(code)}`);

export type AuditQuery = { entityType: string; offset: number; limit: number };

export function fetchAudit(query: AuditQuery, signal?: AbortSignal) {
  const params = new URLSearchParams({ limit: String(query.limit), offset: String(query.offset) });
  if (query.entityType) params.set("entityType", query.entityType);
  return apiGet<{ events: AuditEvent[]; total: number }>(`${BASE}/audit?${params}`, { signal });
}

export const fetchDirectory = (includeInactive: boolean, signal?: AbortSignal) =>
  apiGet<{ users: DirectoryUser[] }>(`/api/v1/users/directory${includeInactive ? "?includeInactive=true" : ""}`, {
    signal,
  }).then((body) => body.users);

/** The one-time link an administrator sends to a user. The token travels in the fragment, which browsers never send to servers. */
export function passwordLinkUrl(link: PasswordLink): string {
  return `${window.location.origin}/setup-password#token=${encodeURIComponent(link.token)}`;
}

export function describeAdminError(error: unknown): string {
  if (!(error instanceof ApiError)) return "The API could not be reached.";
  if (error.detail?.message) return error.detail.message;
  switch (error.status) {
    case 401:
      return "Your session has ended. Sign in again to continue.";
    case 403:
      return "You do not have permission for this action.";
    case 404:
      return "This record no longer exists.";
    case 409:
      return "This change conflicts with existing data.";
    case 503:
      return "Administration is unavailable because the database could not be reached.";
    default:
      return "The request failed. Try again.";
  }
}
