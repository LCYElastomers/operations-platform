"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api-client";
import { meets, type Permission, type Requirement } from "@/lib/permissions";

import { authKeys, fetchSession, signOut, type Session } from "./api";

/** The signed-in user, their roles and effective permissions. */
export function useSession() {
  return useQuery({
    queryKey: authKeys.me(),
    queryFn: ({ signal }) => fetchSession(signal),
    retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });
}

const NONE: ReadonlySet<Permission> = new Set();

/** Permission checks for showing or hiding parts of the interface. */
export function usePermissions() {
  const session = useSession();
  const granted = session.data?.permissions ?? NONE;
  return {
    session: session.data ?? null,
    loading: session.isPending,
    has: (permission: Permission) => granted.has(permission),
    meets: (requirement: Requirement | undefined) => meets(granted, requirement),
  };
}

export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: signOut,
    onSettled: () => {
      queryClient.clear();
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- a full load drops all of the previous user's in-memory state
      window.location.assign("/login");
    },
  });
}

export type { Session };
