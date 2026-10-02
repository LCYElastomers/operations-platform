"use client";

import { useQuery } from "@tanstack/react-query";

import { apiGet } from "@/lib/api-client";
import { cn } from "@/lib/utils";

type HealthResponse = {
  status: "ok";
  service: string;
  version: string;
};

export function ApiStatus() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["system", "health"],
    queryFn: ({ signal }) => apiGet<HealthResponse>("/api/v1/health", { signal }),
    refetchInterval: 30_000,
    retry: 1,
  });

  const state = isPending ? "checking" : isError ? "unreachable" : "online";

  return (
    <div className="flex items-center justify-between rounded-lg border bg-card px-4 py-3 text-card-foreground">
      <div>
        <p className="text-sm font-medium">API</p>
        <p className="text-xs text-muted-foreground">
          {data ? `${data.service} v${data.version}` : "/api/v1/health"}
        </p>
      </div>
      <span className="flex items-center gap-2 text-sm">
        <span
          aria-hidden
          className={cn(
            "size-2 rounded-full",
            state === "online" && "bg-success",
            state === "unreachable" && "bg-destructive",
            state === "checking" && "animate-pulse bg-warning",
          )}
        />
        <span className="capitalize">{state}</span>
      </span>
    </div>
  );
}
