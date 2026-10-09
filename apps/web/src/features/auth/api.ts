import { ApiError, apiGet, apiSend } from "@/lib/api-client";
import { isPermission, type Permission } from "@/lib/permissions";

export type RoleRef = { code: string; name: string };

/** The signed-in user as the API reports them; never a password, hash or token. */
export type SessionUser = {
  id: string;
  name: string;
  email: string;
  image: string | null;
  status: "active" | "inactive";
};

export type Me = { user: SessionUser; roles: RoleRef[]; permissions: string[] };

export type Session = {
  user: SessionUser;
  roles: RoleRef[];
  permissions: ReadonlySet<Permission>;
};

export const authKeys = {
  all: ["auth"] as const,
  me: () => [...authKeys.all, "me"] as const,
};

const BASE = "/api/v1/auth";

export function toSession(me: Me): Session {
  return { user: me.user, roles: me.roles, permissions: new Set(me.permissions.filter(isPermission)) };
}

export async function fetchSession(signal?: AbortSignal): Promise<Session> {
  return toSession(await apiGet<Me>(`${BASE}/me`, { signal }));
}

export function signIn(email: string, password: string) {
  return apiSend<void>("POST", `${BASE}/sign-in`, { email, password });
}

export function signOut() {
  return apiSend<void>("POST", `${BASE}/sign-out`);
}

export function checkPasswordLink(token: string) {
  return apiSend<{ name: string; email: string }>("POST", `${BASE}/password-link/check`, { token });
}

export function setPasswordWithLink(token: string, password: string) {
  return apiSend<void>("POST", `${BASE}/password-link`, { token, password });
}

export function changePassword(currentPassword: string, newPassword: string) {
  return apiSend<void>("POST", `${BASE}/password`, { currentPassword, newPassword });
}

/** The API's message for a refused request, or a plain fallback. */
export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.status === 503) return "The service is unavailable because the database could not be reached.";
    if (error.detail?.message) return error.detail.message;
  }
  if (!(error instanceof ApiError)) return "The API could not be reached.";
  return fallback;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0][0] ?? "";
  const last = parts.length > 1 ? (parts.at(-1)?.[0] ?? "") : "";
  return (first + last).toUpperCase();
}
