"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { shouldRetry } from "@/features/quality/cost/use-cost";

import {
  fetchAction,
  fetchActions,
  fetchDashboard,
  fetchNotificationSettings,
  fetchOptions,
  fetchRecommendation,
  fetchRegister,
  fetchStudies,
  fetchStudy,
  fetchTimeline,
  psmKeys,
  type ActionDetail,
  type ActionQuery,
  type RecommendationDetail,
  type RegisterQuery,
} from "./api";

export function usePsmOptions() {
  return useQuery({
    queryKey: psmKeys.options(),
    queryFn: ({ signal }) => fetchOptions(signal),
    retry: shouldRetry,
    staleTime: 60_000,
  });
}

export function usePsmDashboard(studyId: string) {
  return useQuery({
    queryKey: psmKeys.dashboard(studyId),
    queryFn: ({ signal }) => fetchDashboard(studyId, signal),
    retry: shouldRetry,
    placeholderData: keepPreviousData,
  });
}

export function useStudies() {
  return useQuery({ queryKey: psmKeys.studies(), queryFn: ({ signal }) => fetchStudies(signal), retry: shouldRetry });
}

export function useStudy(id: number) {
  return useQuery({ queryKey: psmKeys.study(id), queryFn: ({ signal }) => fetchStudy(id, signal), retry: shouldRetry });
}

export function useRegister(query: RegisterQuery) {
  return useQuery({
    queryKey: psmKeys.register(query),
    queryFn: ({ signal }) => fetchRegister(query, signal),
    retry: shouldRetry,
    placeholderData: keepPreviousData,
  });
}

export function useRecommendation(id: number) {
  return useQuery({
    queryKey: psmKeys.recommendation(id),
    queryFn: ({ signal }) => fetchRecommendation(id, signal),
    retry: shouldRetry,
  });
}

export function useTimeline(id: number, enabled: boolean) {
  return useQuery({
    queryKey: psmKeys.timeline(id),
    queryFn: ({ signal }) => fetchTimeline(id, signal),
    retry: shouldRetry,
    enabled,
  });
}

export function useActions(query: ActionQuery) {
  return useQuery({
    queryKey: psmKeys.actions(query),
    queryFn: ({ signal }) => fetchActions(query, signal),
    retry: shouldRetry,
    placeholderData: keepPreviousData,
  });
}

export function useAction(id: number) {
  return useQuery({ queryKey: psmKeys.action(id), queryFn: ({ signal }) => fetchAction(id, signal), retry: shouldRetry });
}

export function useNotificationSettings(enabled: boolean) {
  return useQuery({
    queryKey: psmKeys.notificationSettings(),
    queryFn: ({ signal }) => fetchNotificationSettings(signal),
    retry: shouldRetry,
    enabled,
  });
}

/**
 * A PSM write. The returned record is stored, and every PSM list and figure is
 * refreshed: one change can move a register row, an action and the dashboard.
 */
export function usePsmMutation<A, R>(mutationFn: (args: A) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: (response) => {
      const detail = response as unknown;
      if (detail && typeof detail === "object") {
        if ("scenarios" in detail && "displayId" in detail) {
          const rec = detail as RecommendationDetail;
          queryClient.setQueryData(psmKeys.recommendation(rec.id), rec);
        } else if ("action" in detail && "updates" in detail) {
          const action = detail as ActionDetail;
          queryClient.setQueryData(psmKeys.action(action.action.id), action);
        }
      }
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: psmKeys.all }),
  });
}
