"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { costKeys } from "../cost/api";
import { shouldRetry } from "../cost/use-cost";

import {
  addAction,
  carKeys,
  completeAction,
  createCar,
  createQualityCost,
  fetchCar,
  fetchCarDashboard,
  fetchCarHistory,
  fetchCarOptions,
  fetchCars,
  fetchLinkedCars,
  linkQualityCost,
  recordApproval,
  updateAction,
  updateCar,
  withdrawApproval,
  type ActionFields,
  type ApprovalFunction,
  type CarDashboardQuery,
  type CarFields,
  type CarQuery,
  type CarResponse,
  type QualityCostCreate,
} from "./api";

export function useCars(query: CarQuery) {
  return useQuery({
    queryKey: carKeys.list(query),
    queryFn: ({ signal }) => fetchCars(query, signal),
    retry: shouldRetry,
    placeholderData: keepPreviousData,
  });
}

export function useCarDashboard(query: CarDashboardQuery) {
  return useQuery({
    queryKey: carKeys.dashboard(query),
    queryFn: ({ signal }) => fetchCarDashboard(query, signal),
    retry: shouldRetry,
    placeholderData: keepPreviousData,
  });
}

export function useCarOptions() {
  return useQuery({
    queryKey: carKeys.options(),
    queryFn: ({ signal }) => fetchCarOptions(signal),
    retry: shouldRetry,
    staleTime: 5 * 60_000,
  });
}

export function useCar(id: number | null) {
  return useQuery({
    queryKey: carKeys.car(id ?? 0),
    queryFn: ({ signal }) => fetchCar(id!, signal),
    retry: shouldRetry,
    enabled: id !== null,
  });
}

export function useCarHistory(id: number | null, enabled = true) {
  return useQuery({
    queryKey: carKeys.history(id ?? 0),
    queryFn: ({ signal }) => fetchCarHistory(id!, signal),
    retry: shouldRetry,
    enabled: id !== null && enabled,
  });
}

/** The CAR linked to a Quality Cost record. Users without CAR access get an error, shown as nothing. */
export function useLinkedCars(costRecordId: number | null) {
  return useQuery({
    queryKey: carKeys.linked(costRecordId ?? 0),
    queryFn: ({ signal }) => fetchLinkedCars(costRecordId!, signal),
    retry: false,
    enabled: costRecordId !== null,
  });
}

/**
 * Every write stores the returned report and refreshes the register, the
 * dashboard and the history. Quality Cost data is refreshed too, since a CAR
 * can create or link a Quality Cost record.
 */
function useCarMutation<A>(mutationFn: (args: A) => Promise<CarResponse>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: (response) => queryClient.setQueryData(carKeys.car(response.car.id), response),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: carKeys.all });
      void queryClient.invalidateQueries({ queryKey: costKeys.all });
    },
  });
}

export function useCreateCar() {
  return useCarMutation((body: CarFields) => createCar(body));
}

export function useUpdateCar() {
  return useCarMutation(({ id, body }: { id: number; body: CarFields & { version: number } }) =>
    updateCar(id, body),
  );
}

export function useAddAction() {
  return useCarMutation(({ carId, body }: { carId: number; body: ActionFields }) => addAction(carId, body));
}

export function useUpdateAction() {
  return useCarMutation(
    ({ carId, actionId, body }: { carId: number; actionId: number; body: ActionFields & { version: number } }) =>
      updateAction(carId, actionId, body),
  );
}

export function useCompleteAction() {
  return useCarMutation(
    ({ carId, actionId, body }: { carId: number; actionId: number; body: { version: number; completedOn: string } }) =>
      completeAction(carId, actionId, body),
  );
}

type ApprovalArgs = { id: number; body: { version: number; functionCode: ApprovalFunction } };

export function useRecordApproval() {
  return useCarMutation(({ id, body }: ApprovalArgs) => recordApproval(id, body));
}

export function useWithdrawApproval() {
  return useCarMutation(({ id, body }: ApprovalArgs) => withdrawApproval(id, body));
}

export function useCreateQualityCost() {
  return useCarMutation(({ carId, body }: { carId: number; body: QualityCostCreate }) =>
    createQualityCost(carId, body),
  );
}

export function useLinkQualityCost() {
  return useCarMutation(({ carId, body }: { carId: number; body: { version: number; recordId: number | null } }) =>
    linkQualityCost(carId, body),
  );
}
