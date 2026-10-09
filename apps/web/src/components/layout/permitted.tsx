"use client";

import { usePermissions } from "@/features/auth/use-session";
import type { Requirement } from "@/lib/permissions";

/**
 * Renders its children only for users who meet at least one of the given
 * requirements. Hiding is a convenience; the API enforces access itself.
 */
export function Permitted({
  anyOf,
  fallback = null,
  children,
}: {
  anyOf: Requirement[];
  fallback?: React.ReactNode;
  children: React.ReactNode;
}) {
  const permissions = usePermissions();
  if (permissions.loading) return null;
  return anyOf.some((requirement) => permissions.meets(requirement)) ? children : fallback;
}
