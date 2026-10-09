import { ApiError, apiGet, apiSend } from "@/lib/api-client";

/** Mirrors the FastAPI Safety Observations contract. Every count is a count of observation records. */
export type Outcome = "safe" | "unsafe";
export type Kind = "act" | "condition";

export type ObservationCategory = { id: number; code: string; name: string };

/** What the signed-in user may do; the server enforces the same rules. */
export type ObservationAbilities = { canEdit: boolean; canCreate?: boolean; canDelete?: boolean };

export type ObservationCategoriesResponse = ObservationAbilities & {
  categories: ObservationCategory[];
};

export type ObservationInput = {
  /** YYYY-MM-DD */
  observedOn: string;
  outcome: Outcome;
  kind: Kind;
  categoryId: number;
  areaLocation: string | null;
  description: string | null;
  correctiveAction: string | null;
};

export type Observation = ObservationInput & {
  id: number;
  categoryCode: string;
  categoryName: string;
  createdAt: string;
  createdBy: string;
  updatedAt: string;
  updatedBy: string;
};

export type ObservationListResponse = ObservationAbilities & {
  observations: Observation[];
  totalMatching: number;
};

export type ObservationCounts = {
  total: number;
  safe: number;
  unsafe: number;
  safeAct: number;
  safeCondition: number;
  unsafeAct: number;
  unsafeCondition: number;
};

export type CategoryCount = {
  categoryId: number;
  code: string;
  name: string;
  total: number;
  safe: number;
  unsafe: number;
};

export type ObservationSummaryResponse = {
  year: number;
  month: number | null;
  counts: ObservationCounts;
  categories: CategoryCount[];
};

export type ObservationDashboardResponse = {
  year: number;
  /** Last month of the year that has started (0-12). Later months are null. */
  throughMonth: number;
  counts: ObservationCounts;
  /** Unsafe / total; null when there are no observations. */
  unsafeShare: number | null;
  months: { month: number; counts: ObservationCounts | null }[];
  categories: (CategoryCount & { monthly: (number | null)[] })[];
  yearsWithData: number[];
};

export type ObservationListParams = { year: number; month: number; limit: number };

const BASE = "/api/v1/safety/observations";

export const observationKeys = {
  all: ["safety", "observations"] as const,
  categories: () => [...observationKeys.all, "categories"] as const,
  list: (params: ObservationListParams) => [...observationKeys.all, "list", params] as const,
  summary: (year: number, month: number) =>
    [...observationKeys.all, "summary", year, month] as const,
  dashboard: (year: number) => [...observationKeys.all, "dashboard", year] as const,
};

export function fetchObservationCategories(signal?: AbortSignal) {
  return apiGet<ObservationCategoriesResponse>(`${BASE}/categories`, { signal });
}

export function fetchObservations({ year, month, limit }: ObservationListParams, signal?: AbortSignal) {
  return apiGet<ObservationListResponse>(`${BASE}?year=${year}&month=${month}&limit=${limit}`, {
    signal,
  });
}

export function fetchObservationSummary(year: number, month: number, signal?: AbortSignal) {
  return apiGet<ObservationSummaryResponse>(`${BASE}/summary?year=${year}&month=${month}`, {
    signal,
  });
}

export function fetchObservationDashboard(year: number, signal?: AbortSignal) {
  return apiGet<ObservationDashboardResponse>(`${BASE}/dashboard?year=${year}`, { signal });
}

export function createObservation(input: ObservationInput) {
  return apiSend<Observation>("POST", BASE, input);
}

export function updateObservation(id: number, input: ObservationInput, expectedUpdatedAt: string) {
  return apiSend<Observation>("PUT", `${BASE}/${id}`, { ...input, expectedUpdatedAt });
}

export function deleteObservation(id: number) {
  return apiSend<void>("DELETE", `${BASE}/${id}`);
}

/** User-facing explanation of a failed Safety Observations request. */
export function describeObservationError(error: unknown): string {
  if (!(error instanceof ApiError)) return "The API could not be reached.";
  switch (error.status) {
    case 401:
      return "Your session has ended. Sign in again to continue.";
    case 403:
      return "You do not have permission for this Safety function.";
    case 404:
      return "This observation no longer exists. It may have been deleted by someone else.";
    case 409:
      return "Someone else changed this observation since it was loaded. Nothing was saved; the latest version is now shown.";
    case 503:
      return "Safety data is unavailable because the database could not be reached.";
    default:
      if (error.detail?.error === "unknown_category") {
        return "That category is no longer available. Choose another category.";
      }
      if (error.detail?.error === "observed_on_in_future") {
        return "The observed date cannot be in the future.";
      }
      return error.detail?.message ?? `The API responded with HTTP ${error.status}.`;
  }
}
