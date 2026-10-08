"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api-client";

import {
  createRecord,
  fetchHistory,
  fetchReconciliation,
  fetchRecordOptions,
  fetchRecords,
  reclassifyRecord,
  recordKeys,
  updateRecord,
  voidRecord,
  type EventType,
  type MonthContext,
  type ReclassifyBody,
  type RecordFields,
  type RecordFilter,
} from "./api";

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
  return useRecordMutation((body: RecordFields & { eventType: EventType } & Partial<MonthContext>) =>
    createRecord(body),
  );
}

export function useUpdateRecord() {
  return useRecordMutation(({ id, body }: { id: number; body: RecordFields & MonthContext & { version: number } }) =>
    updateRecord(id, body),
  );
}

export function useVoidRecord() {
  return useRecordMutation(({ id, body }: { id: number; body: { version: number; reason: string } }) =>
    voidRecord(id, body),
  );
}

export function useReclassifyRecord() {
  return useRecordMutation(({ id, body }: { id: number; body: ReclassifyBody }) => reclassifyRecord(id, body));
}
