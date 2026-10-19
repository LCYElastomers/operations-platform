"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchDelivery,
  fetchDeliveries,
  fetchEventTypes,
  fetchOverview,
  fetchPsmActionsForTest,
  fetchSettings,
  fetchTemplate,
  fetchTemplates,
  fetchWorkflow,
  fetchWorkflows,
  notificationKeys,
  type DeliveryQuery,
} from "./api";

export function useOverview(days = 7) {
  return useQuery({
    queryKey: notificationKeys.overview(days),
    queryFn: ({ signal }) => fetchOverview(days, signal),
  });
}

export function useEventTypes() {
  return useQuery({
    queryKey: notificationKeys.eventTypes(),
    queryFn: ({ signal }) => fetchEventTypes(signal),
    staleTime: 10 * 60_000,
  });
}

export function useTemplates() {
  return useQuery({
    queryKey: notificationKeys.templates(),
    queryFn: ({ signal }) => fetchTemplates(signal),
  });
}

export function useTemplate(id: number | null) {
  return useQuery({
    queryKey: notificationKeys.template(id ?? 0),
    queryFn: ({ signal }) => fetchTemplate(id!, signal),
    enabled: id !== null,
  });
}

export function useWorkflows() {
  return useQuery({
    queryKey: notificationKeys.workflows(),
    queryFn: ({ signal }) => fetchWorkflows(signal),
  });
}

export function useWorkflow(id: number | null) {
  return useQuery({
    queryKey: notificationKeys.workflow(id ?? 0),
    queryFn: ({ signal }) => fetchWorkflow(id!, signal),
    enabled: id !== null,
  });
}

export function useDeliveries(query: DeliveryQuery) {
  return useQuery({
    queryKey: notificationKeys.deliveries(query),
    queryFn: ({ signal }) => fetchDeliveries(query, signal),
    placeholderData: (previous) => previous,
  });
}

export function useDelivery(id: string | null) {
  return useQuery({
    queryKey: notificationKeys.delivery(id ?? ""),
    queryFn: ({ signal }) => fetchDelivery(id!, signal),
    enabled: id !== null,
  });
}

export function useNotificationSettings() {
  return useQuery({
    queryKey: notificationKeys.settings(),
    queryFn: ({ signal }) => fetchSettings(signal),
  });
}

export function usePsmActionsForTest() {
  return useQuery({
    queryKey: notificationKeys.psmActions(),
    queryFn: ({ signal }) => fetchPsmActionsForTest(signal),
  });
}

export function useNotificationsMutation<TArgs, TResult>(mutationFn: (args: TArgs) => Promise<TResult>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    },
  });
}
