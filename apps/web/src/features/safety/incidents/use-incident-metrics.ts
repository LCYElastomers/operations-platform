"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api-client";

import {
  behaviorCountKeys,
  fetchBehaviorCounts,
  fetchIncidentAnalytics,
  fetchIncidentMetrics,
  incidentAnalyticsKeys,
  incidentMetricKeys,
  saveBehaviorCounts,
  saveIncidentMetrics,
  type BehaviorChange,
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

/** Analytics for January..through; `through` null asks for the latest started month. */
export function useIncidentAnalytics(year: number, through: number | null) {
  return useQuery({
    queryKey: incidentAnalyticsKeys.period(year, through),
    queryFn: ({ signal }) => fetchIncidentAnalytics(year, through, signal),
    retry: shouldRetry,
  });
}

/** Stored annual Behavior tag counts for one year. */
export function useBehaviorCounts(year: number) {
  return useQuery({
    queryKey: behaviorCountKeys.year(year),
    queryFn: ({ signal }) => fetchBehaviorCounts(year, signal),
    retry: shouldRetry,
  });
}

export function useSaveBehaviorCounts(year: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (changes: BehaviorChange[]) => saveBehaviorCounts(year, changes),
    onSuccess: (response) => {
      queryClient.setQueryData(behaviorCountKeys.year(year), response.counts);
      void queryClient.invalidateQueries({ queryKey: incidentAnalyticsKeys.all });
    },
  });
}

export function useSaveIncidentMetrics(year: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (changes: CellChange[]) => saveIncidentMetrics(year, changes),
    onSuccess: (response) => {
      queryClient.setQueryData(incidentMetricKeys.year(year), response.metrics);
      void queryClient.invalidateQueries({ queryKey: incidentAnalyticsKeys.all });
    },
  });
}
