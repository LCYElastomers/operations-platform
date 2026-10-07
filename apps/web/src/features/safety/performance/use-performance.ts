"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api-client";

import {
  clearMonth,
  fetchPerformanceDashboard,
  fetchPerformanceMonths,
  performanceKeys,
  saveMonth,
  type SaveMonthRequest,
} from "./api";

const MAX_RETRIES = 2;

// Authorization and validation failures will not succeed on retry.
function shouldRetry(failureCount: number, error: unknown) {
  if (error instanceof ApiError && error.status < 500) return false;
  return failureCount < MAX_RETRIES;
}

export function usePerformanceMonths(year: number) {
  return useQuery({
    queryKey: performanceKeys.months(year),
    queryFn: ({ signal }) => fetchPerformanceMonths(year, signal),
    retry: shouldRetry,
  });
}

export function usePerformanceDashboard(year: number, throughMonth: number | null) {
  return useQuery({
    queryKey: performanceKeys.dashboard(year, throughMonth),
    queryFn: ({ signal }) => fetchPerformanceDashboard(year, throughMonth, signal),
    retry: shouldRetry,
  });
}

type MonthChange =
  | { kind: "save"; month: number; request: SaveMonthRequest }
  | { kind: "clear"; month: number; expectedUpdatedAt: string };

/** Saves or clears one month; afterwards the year and every dashboard reload. */
export function useChangeMonth(year: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (change: MonthChange): Promise<void> => {
      if (change.kind === "save") await saveMonth(year, change.month, change.request);
      else await clearMonth(year, change.month, change.expectedUpdatedAt);
    },
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: performanceKeys.months(year) }),
        queryClient.invalidateQueries({ queryKey: performanceKeys.dashboards() }),
      ]),
  });
}
