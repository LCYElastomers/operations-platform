"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api-client";

import {
  createRecord,
  fetchHistory,
  fetchReconciliation,
  fetchRecord,
  fetchRecordOptions,
  fetchRecords,
  reclassifyRecord,
  recordKeys,
  updateRecord,
  voidRecord,
  type CreateBody,
  type ReclassifyBody,
  type RecordFilter,
  type UpdateBody,
} from "./api";
import { fetchEventExperience, fetchLopcRecords, fetchSeriousRisk } from "./insights-api";

const MAX_RETRIES = 2;

function shouldRetry(failureCount: number, error: unknown) {
  if (error instanceof ApiError && error.status < 500) return false;
  return failureCount < MAX_RETRIES;
}

export function useRecords(filter: RecordFilter, enabled = true) {
  return useQuery({
    queryKey: recordKeys.list(filter),
    queryFn: ({ signal }) => fetchRecords(filter, signal),
    retry: shouldRetry,
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useRecordOptions(enabled = true) {
  return useQuery({
    queryKey: recordKeys.options(),
    queryFn: ({ signal }) => fetchRecordOptions(signal),
    retry: shouldRetry,
    staleTime: 5 * 60_000,
    enabled,
  });
}

/** Monthly totals against documented records; a 403 means records are not available to the user. */
export function useRecordReconciliation(year: number) {
  return useQuery({
    queryKey: recordKeys.reconciliation(year),
    queryFn: ({ signal }) => fetchReconciliation(year, signal),
    retry: shouldRetry,
  });
}

export function useRecord(id: number | null) {
  return useQuery({
    queryKey: recordKeys.record(id ?? 0),
    queryFn: ({ signal }) => fetchRecord(id!, signal),
    retry: shouldRetry,
    enabled: id !== null,
  });
}

/** Event Experience for a year, as of today in Baytown (31 December for a past year). */
export function useEventExperience(year: number, enabled = true) {
  return useQuery({
    queryKey: recordKeys.insights("event-experience", year, null),
    queryFn: ({ signal }) => fetchEventExperience(year, signal),
    retry: shouldRetry,
    enabled,
  });
}

export function useLopcRecords(year: number, through: number | null, enabled = true) {
  return useQuery({
    queryKey: recordKeys.insights("lopc-records", year, through),
    queryFn: ({ signal }) => fetchLopcRecords(year, through, signal),
    retry: shouldRetry,
    enabled,
  });
}

export function useSeriousRisk(year: number, through: number | null, enabled = true) {
  return useQuery({
    queryKey: recordKeys.insights("serious-risk", year, through),
    queryFn: ({ signal }) => fetchSeriousRisk(year, through, signal),
    retry: shouldRetry,
    enabled,
  });
}

export function useRecordHistory(id: number | null) {
  return useQuery({
    queryKey: recordKeys.history(id ?? 0),
    queryFn: ({ signal }) => fetchHistory(id!, signal),
    retry: shouldRetry,
    enabled: id !== null,
  });
}

/** Every write refreshes the lists, the reconciliation and any open history. */
function useRecordMutation<A, R>(mutationFn: (args: A) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSettled: () => queryClient.invalidateQueries({ queryKey: recordKeys.all }),
  });
}

export function useCreateRecord() {
  return useRecordMutation((body: CreateBody) => createRecord(body));
}

export function useUpdateRecord() {
  return useRecordMutation(({ id, body }: { id: number; body: UpdateBody }) => updateRecord(id, body));
}

export function useVoidRecord() {
  return useRecordMutation(({ id, body }: { id: number; body: { version: number; reason: string } }) =>
    voidRecord(id, body),
  );
}

export function useReclassifyRecord() {
  return useRecordMutation(({ id, body }: { id: number; body: ReclassifyBody }) => reclassifyRecord(id, body));
}
