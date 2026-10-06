"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api-client";

import {
  fetchIncidentMetrics,
  incidentMetricKeys,
  saveIncidentMetrics,
  type CellChange,
} from "./api";

const MAX_RETRIES = 2;

// Authorization and validation failures will not succeed on retry.
function shouldRetry(failureCount: number, error: unknown) {
  if (error instanceof ApiError && error.status < 500) return false;
  return failureCount < MAX_RETRIES;
}

/** Stored Incident & Near Miss values for one year. Shared by Data Entry and Dashboard. */
export function useIncidentMetrics(year: number) {
  return useQuery({
    queryKey: incidentMetricKeys.year(year),
    queryFn: ({ signal }) => fetchIncidentMetrics(year, signal),
    retry: shouldRetry,
  });
}

export function useSaveIncidentMetrics(year: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (changes: CellChange[]) => saveIncidentMetrics(year, changes),
    onSuccess: (response) => {
      queryClient.setQueryData(incidentMetricKeys.year(year), response.metrics);
    },
  });
}
