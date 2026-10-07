"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api-client";

import {
  contactKeys,
  createContact,
  createSupervisor,
  deleteContact,
  deleteSupervisor,
  fetchContactDashboard,
  fetchContactSummary,
  fetchRecentContacts,
  fetchSupervisors,
  updateContact,
  updateSupervisor,
  type ContactInput,
  type SupervisorInput,
} from "./api";

const MAX_RETRIES = 2;

// Authorization and validation failures will not succeed on retry.
function shouldRetry(failureCount: number, error: unknown) {
  if (error instanceof ApiError && error.status < 500) return false;
  return failureCount < MAX_RETRIES;
}

export function useSupervisors() {
  return useQuery({
    queryKey: contactKeys.supervisors(),
    queryFn: ({ signal }) => fetchSupervisors(signal),
    retry: shouldRetry,
  });
}

export function useRecentContacts(limit: number) {
  return useQuery({
    queryKey: contactKeys.recent(limit),
    queryFn: ({ signal }) => fetchRecentContacts(limit, signal),
    retry: shouldRetry,
    placeholderData: keepPreviousData,
  });
}

export function useContactSummary(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: contactKeys.summary(year, month),
    queryFn: ({ signal }) => fetchContactSummary(year, month, signal),
    retry: shouldRetry,
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useContactDashboard(year: number) {
  return useQuery({
    queryKey: contactKeys.dashboard(year),
    queryFn: ({ signal }) => fetchContactDashboard(year, signal),
    retry: shouldRetry,
  });
}

/** Every list, count, and the supervisor list (hasContacts) derive from the same records. */
function useRefreshContacts() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: contactKeys.all });
}

export function useCreateContact() {
  const refresh = useRefreshContacts();
  return useMutation({
    mutationFn: (input: ContactInput & { requestId: string }) => createContact(input),
    onSettled: refresh,
  });
}

export function useUpdateContact() {
  const refresh = useRefreshContacts();
  return useMutation({
    mutationFn: ({
      id,
      input,
      expectedUpdatedAt,
    }: {
      id: number;
      input: ContactInput;
      expectedUpdatedAt: string;
    }) => updateContact(id, input, expectedUpdatedAt),
    // A conflict or missing record also means the list is stale.
    onSettled: refresh,
  });
}

export function useDeleteContact() {
  const refresh = useRefreshContacts();
  return useMutation({
    mutationFn: (id: number) => deleteContact(id),
    onSettled: refresh,
  });
}

export function useSaveSupervisor() {
  const refresh = useRefreshContacts();
  return useMutation({
    mutationFn: ({
      id,
      input,
      expectedUpdatedAt,
    }: {
      id: number | null;
      input: SupervisorInput;
      expectedUpdatedAt: string | null;
    }) =>
      id === null || expectedUpdatedAt === null
        ? createSupervisor(input)
        : updateSupervisor(id, input, expectedUpdatedAt),
    onSettled: refresh,
  });
}

export function useDeleteSupervisor() {
  const refresh = useRefreshContacts();
  return useMutation({
    mutationFn: (id: number) => deleteSupervisor(id),
    onSettled: refresh,
  });
}
