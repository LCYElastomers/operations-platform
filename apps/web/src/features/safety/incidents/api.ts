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

/** One stored category, January..throughMonth. null means unreported, 0 a reported zero. */
export type AnalyticsSeries = {
  section: string;
  code: string;
  /** The configured display name. */
  name: string;
  values: (number | null)[];
  /** Sum of reported months; null when none are reported. */
  total: number | null;
  monthsReported: number;
  unreportedMonths: number[];
  /** Every month January..throughMonth is reported. */
  complete: boolean;
};

export type AnalyticsKpi = {
  key: "incidents" | "near_misses" | "lopc" | "psif";
  value: number | null;
  monthsReported: number;
  throughMonth: number | null;
  complete: boolean;
};

/**
 * Read-only analytics calculated by the API from the stored monthly values.
 * Classifications may overlap and are never summed; `combinedDamage` is
 * Property Damage plus Equipment Damage classifications; `pit` is the
 * pit_accident classification and `lopc` the LOPC series.
 */
export type IncidentAnalyticsResponse = {
  year: number;
  /** null when the year has not started. */
  throughMonth: number | null;
  /** The latest month of the year that has started in Baytown. */
  latestMonth: number | null;
  /** Newest first. */
  availableYears: number[];
  kpis: AnalyticsKpi[];
  incidents: AnalyticsSeries;
  nearMisses: AnalyticsSeries;
  /** Incident Classification categories in display order, then PSIF. */
  classifications: AnalyticsSeries[];
  lopc: AnalyticsSeries;
  psif: AnalyticsSeries;
  pit: AnalyticsSeries;
  propertyDamage: AnalyticsSeries;
  equipmentDamage: AnalyticsSeries;
  combinedDamage: AnalyticsSeries;
};

export const incidentAnalyticsKeys = {
  all: ["safety", "incidents", "analytics"] as const,
  /** `through` null: the API's default, the latest month that has started. */
  period: (year: number, through: number | null) => [...incidentAnalyticsKeys.all, year, through] as const,
};

export function fetchIncidentAnalytics(year: number, through: number | null, signal?: AbortSignal) {
  const params = new URLSearchParams({ year: String(year) });
  if (through !== null) params.set("through", String(through));
  return apiGet<IncidentAnalyticsResponse>(`/api/v1/safety/incidents/analytics?${params}`, { signal });
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
