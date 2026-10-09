"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api-client";

import {
  costKeys,
  createCostRecord,
  fetchCostRecord,
  fetchCostRecordHistory,
  fetchCostRecordOptions,
  fetchCostRecords,
  fetchCostSummary,
  updateCostRecord,
  type CostRecordFields,
  type CostRecordQuery,
  type CostSummaryQuery,
} from "./api";

const MAX_RETRIES = 2;

export function shouldRetry(failureCount: number, error: unknown) {
  if (error instanceof ApiError && error.status < 500) return false;
  return failureCount < MAX_RETRIES;
}

export function useCostSummary(query: CostSummaryQuery) {
  return useQuery({
    queryKey: costKeys.summary(query),
    queryFn: ({ signal }) => fetchCostSummary(query, signal),
    retry: shouldRetry,
    placeholderData: keepPreviousData,
  });
}

export function useCostRecords(query: CostRecordQuery, enabled = true) {
  return useQuery({
    queryKey: costKeys.records(query),
    queryFn: ({ signal }) => fetchCostRecords(query, signal),
    retry: shouldRetry,
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useCostRecordOptions() {
  return useQuery({
    queryKey: costKeys.options(),
    queryFn: ({ signal }) => fetchCostRecordOptions(signal),
    retry: shouldRetry,
    staleTime: 5 * 60_000,
  });
}

export function useCostRecord(id: number | null) {
  return useQuery({
    queryKey: costKeys.record(id ?? 0),
    queryFn: ({ signal }) => fetchCostRecord(id!, signal),
    retry: shouldRetry,
    enabled: id !== null,
  });
}

export function useCostRecordHistory(id: number | null) {
  return useQuery({
    queryKey: costKeys.history(id ?? 0),
    queryFn: ({ signal }) => fetchCostRecordHistory(id!, signal),
    retry: shouldRetry,
    enabled: id !== null,
  });
}

/** Every write refreshes the Register, both dashboards, the options and any open record. */
function useCostMutation<A, R>(mutationFn: (args: A) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSettled: () => queryClient.invalidateQueries({ queryKey: costKeys.all }),
  });
}

export function useCreateCostRecord() {
  return useCostMutation((body: CostRecordFields) => createCostRecord(body));
}

export function useUpdateCostRecord() {
  return useCostMutation(({ id, body }: { id: number; body: CostRecordFields & { version: number } }) =>
    updateCostRecord(id, body),
  );
}
