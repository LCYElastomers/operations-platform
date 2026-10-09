"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { authKeys } from "../auth/api";
import {
  adminKeys,
  fetchAudit,
  fetchDirectory,
  fetchPermissions,
  fetchRoles,
  fetchUser,
  fetchUsers,
  type AuditQuery,
} from "./api";

export function useUsers() {
  return useQuery({ queryKey: adminKeys.users(), queryFn: ({ signal }) => fetchUsers(signal) });
}

export function useUser(id: string | null) {
  return useQuery({
    queryKey: adminKeys.user(id ?? ""),
    queryFn: ({ signal }) => fetchUser(id!, signal),
    enabled: id !== null,
  });
}

export function useRoles(enabled = true) {
  return useQuery({ queryKey: adminKeys.roles(), queryFn: ({ signal }) => fetchRoles(signal), enabled });
}

export function usePermissionCatalog() {
  return useQuery({
    queryKey: adminKeys.permissions(),
    queryFn: ({ signal }) => fetchPermissions(signal),
    staleTime: 10 * 60_000,
  });
}

export function useAudit(query: AuditQuery) {
  return useQuery({
    queryKey: adminKeys.audit(query),
    queryFn: ({ signal }) => fetchAudit(query, signal),
    placeholderData: (previous) => previous,
  });
}

/** Active users to choose from; with `includeInactive`, also former users, to name them on older records. */
export function useDirectory(includeInactive = false) {
  return useQuery({
    queryKey: adminKeys.directory(includeInactive),
    queryFn: ({ signal }) => fetchDirectory(includeInactive, signal),
    staleTime: 5 * 60_000,
  });
}

/**
 * An administration change. Afterwards users, roles and the signed-in user's
 * own access are reloaded: an administrator may have changed their own roles.
 */
export function useAdminMutation<TArgs, TResult>(mutationFn: (args: TArgs) => Promise<TResult>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.all });
      void queryClient.invalidateQueries({ queryKey: ["users", "directory"] });
      void queryClient.invalidateQueries({ queryKey: authKeys.all });
    },
  });
}
