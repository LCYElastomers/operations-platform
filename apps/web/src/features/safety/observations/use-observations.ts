"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api-client";

import {
  createObservation,
  deleteObservation,
  fetchObservationCategories,
  fetchObservationDashboard,
  fetchObservations,
  fetchObservationSummary,
  observationKeys,
  updateObservation,
  type ObservationInput,
  type ObservationListParams,
} from "./api";

const MAX_RETRIES = 2;

// Authorization and validation failures will not succeed on retry.
function shouldRetry(failureCount: number, error: unknown) {
  if (error instanceof ApiError && error.status < 500) return false;
  return failureCount < MAX_RETRIES;
}

export function useObservationCategories() {
  return useQuery({
    queryKey: observationKeys.categories(),
    queryFn: ({ signal }) => fetchObservationCategories(signal),
    retry: shouldRetry,
    staleTime: 5 * 60_000,
  });
}

export function useObservations(params: ObservationListParams) {
  return useQuery({
    queryKey: observationKeys.list(params),
    queryFn: ({ signal }) => fetchObservations(params, signal),
    retry: shouldRetry,
    placeholderData: keepPreviousData,
  });
}

export function useObservationSummary(year: number, month: number) {
  return useQuery({
    queryKey: observationKeys.summary(year, month),
    queryFn: ({ signal }) => fetchObservationSummary(year, month, signal),
    retry: shouldRetry,
    placeholderData: keepPreviousData,
  });
}

export function useObservationDashboard(year: number) {
  return useQuery({
    queryKey: observationKeys.dashboard(year),
    queryFn: ({ signal }) => fetchObservationDashboard(year, signal),
    retry: shouldRetry,
  });
}

/** Lists, summaries, and dashboards are all derived from the same records; refresh them together. */
function useRefreshObservations() {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({
      predicate: (query) =>
        query.queryKey[0] === observationKeys.all[0] &&
        query.queryKey[1] === observationKeys.all[1] &&
        query.queryKey[2] !== "categories",
    });
}

export function useCreateObservation() {
  const refresh = useRefreshObservations();
  return useMutation({
    mutationFn: (input: ObservationInput) => createObservation(input),
    onSuccess: refresh,
  });
}

export function useUpdateObservation() {
  const refresh = useRefreshObservations();
  return useMutation({
    mutationFn: ({
      id,
      input,
      expectedUpdatedAt,
    }: {
      id: number;
      input: ObservationInput;
      expectedUpdatedAt: string;
    }) => updateObservation(id, input, expectedUpdatedAt),
    // A conflict or missing record also means the list is stale.
    onSettled: refresh,
  });
}

export function useDeleteObservation() {
  const refresh = useRefreshObservations();
  return useMutation({
    mutationFn: (id: number) => deleteObservation(id),
    onSettled: refresh,
  });
}
