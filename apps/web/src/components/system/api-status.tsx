"use client";

import { useQuery } from "@tanstack/react-query";

import { StatusBadge, type StatusTone } from "@/components/common/status-badge";
import { apiGet } from "@/lib/api-client";

type HealthResponse = {
  status: "ok";
  service: string;
  version: string;
};

type ApiState = "checking" | "online" | "unreachable";

const stateTone: Record<ApiState, StatusTone> = {
  checking: "pending",
  online: "success",
  unreachable: "danger",
};

const stateLabel: Record<ApiState, string> = {
  checking: "Checking",
  online: "Online",
  unreachable: "Unreachable",
};

export function useApiHealth() {
  const query = useQuery({
    queryKey: ["system", "health"],
    queryFn: ({ signal }) => apiGet<HealthResponse>("/api/v1/health", { signal }),
    refetchInterval: 30_000,
    retry: 1,
  });

  const state: ApiState = query.isPending ? "checking" : query.isError ? "unreachable" : "online";
  return { ...query, state };
}

export function ApiStatusIndicator() {
  const { state } = useApiHealth();

  return (
    <StatusBadge tone={stateTone[state]} pulse={state === "checking"}>
      API {stateLabel[state].toLowerCase()}
    </StatusBadge>
  );
}

export function ApiStatusCard() {
  const { state, data, dataUpdatedAt } = useApiHealth();

  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border bg-card px-4 py-3 text-card-foreground">
      <div className="min-w-0">
        <p className="text-sm font-medium">API service</p>
        <p className="truncate text-xs text-muted-foreground">
          {data ? `${data.service} v${data.version}` : "/api/v1/health"}
          {dataUpdatedAt > 0 && ` · checked ${new Date(dataUpdatedAt).toLocaleTimeString()}`}
        </p>
      </div>
      <StatusBadge tone={stateTone[state]} pulse={state === "checking"}>
        {stateLabel[state]}
      </StatusBadge>
    </div>
  );
}
