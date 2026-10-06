import { ApiError, apiGet, apiSend } from "@/lib/api-client";

/**
 * Mirrors the FastAPI Safety metrics contract. Monthly values: null means
 * unreported, 0 means a reported zero. Totals are calculated by the API.
 */
export type MetricCategoryRow = {
  id: number;
  code: string;
  name: string;
  /** 12 entries, January..December. */
  values: (number | null)[];
  ytd: number | null;
};

/**
 * Categories are never summed into a section total: Incident and Near Miss are
 * explicit categories, and Incident Classification is not mutually exclusive.
 */
export type MetricSectionBlock = {
  id: number;
  code: string;
  name: string;
  categories: MetricCategoryRow[];
};

export type MonthlyMetricsResponse = {
  metricSet: string;
  year: number;
  canEdit: boolean;
  sections: MetricSectionBlock[];
  yearsWithData: number[];
};

export type CellChange = {
  categoryId: number;
  /** 1..12 */
  month: number;
  value: number | null;
  /** The stored value this edit was based on; the API refuses the save if it changed. */
  previousValue: number | null;
};

export type SaveMonthlyMetricsResponse = {
  changedCells: number;
  metrics: MonthlyMetricsResponse;
};

export type CellConflict = { categoryId: number; month: number; currentValue: number | null };

const BASE = "/api/v1/safety/incidents/metrics";

export const incidentMetricKeys = {
  all: ["safety", "incidents", "metrics"] as const,
  year: (year: number) => [...incidentMetricKeys.all, year] as const,
};

export function fetchIncidentMetrics(year: number, signal?: AbortSignal) {
  return apiGet<MonthlyMetricsResponse>(`${BASE}?year=${year}`, { signal });
}

export function saveIncidentMetrics(year: number, changes: CellChange[]) {
  return apiSend<SaveMonthlyMetricsResponse>("PATCH", BASE, { year, changes });
}

export function editConflicts(error: unknown): CellConflict[] | null {
  if (!(error instanceof ApiError) || error.detail?.error !== "edit_conflict") return null;
  return Array.isArray(error.detail.conflicts) ? (error.detail.conflicts as CellConflict[]) : [];
}

/** User-facing explanation of a failed Safety request. */
export function describeSafetyError(error: unknown): string {
  if (!(error instanceof ApiError)) return "The API could not be reached.";
  switch (error.status) {
    case 401:
      return "Sign-in is required to view Safety data. User authentication is not enabled on this server yet.";
    case 403:
      return "You do not have permission for this Safety function.";
    case 503:
      return "Safety data is unavailable because the database could not be reached.";
    default:
      return error.detail?.message ?? `The API responded with HTTP ${error.status}.`;
  }
}
