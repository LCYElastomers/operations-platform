import { ApiError, apiGet, apiSend } from "@/lib/api-client";

/**
 * Mirrors the FastAPI Safety Performance contract. Rates are calculated by the
 * API (events × 200,000 ÷ worked hours over one window) and never stored.
 * null means unreported or unavailable, never zero.
 */
export type Measure = "trir" | "first_aid" | "lopc" | "property_equipment_damage";
export type CountSource = "incidents" | "performance_legacy";
export type MonthStatus = "not_reported" | "reported" | "closed";
export type IneligibleReason = "not_reported" | "open" | "zero_hours";
/** Why a month blocks one measure's window; a pre-2026 count left blank in the source is not confirmed. */
export type BlockReason = IneligibleReason | "count_not_confirmed";

export type MonthHours = {
  totalHours: number;
  hourlyHours: number | null;
  salaryHours: number | null;
  monthClosed: boolean;
  updatedAt: string;
  updatedBy: string;
};

/**
 * Rate numerators for one month. A closed Incident & Near Miss month has no nulls;
 * a pre-2026 month keeps a blank source count as null even when closed.
 */
export type MonthCounts = {
  trir: number | null;
  firstAid: number | null;
  lopc: number | null;
  propertyEquipmentDamage: number | null;
  /** Incident & Near Miss only; the pre-2026 workbook has single combined counts. */
  recordableInjury: number | null;
  occupationalIllness: number | null;
  propertyDamage: number | null;
  equipmentDamageFailure: number | null;
};

export type PerformanceMonth = {
  month: number;
  status: MonthStatus;
  hours: MonthHours | null;
  counts: MonthCounts;
  countsConfirmed: boolean;
  eligible: boolean;
  ineligibleReason: IneligibleReason | null;
  canEnter: boolean;
  canClose: boolean;
};

export type PerformanceYearResponse = {
  year: number;
  countSource: CountSource;
  canEdit: boolean;
  months: PerformanceMonth[];
  yearsWithData: number[];
};

export type Period = { year: number; month: number };

export type RateResult = {
  measure: Measure;
  start: Period;
  end: Period;
  available: boolean;
  ineligibleMonths: (Period & { reason: BlockReason })[];
  events: number | null;
  hours: number | null;
  rate: number | null;
  propertyDamage: number | null;
  equipmentDamageFailure: number | null;
};

export type Kpi = { measure: Measure; ytd: RateResult; rolling: RateResult };

export type RateTrend = {
  measure: Measure;
  /** 12 entries, January..December; null when unavailable. */
  ytd: (number | null)[];
  rolling: (number | null)[];
};

export type AnnualTrir = {
  year: number;
  basis: "monthly" | "annual_legacy" | null;
  partial: boolean;
  throughMonth: number | null;
  events: number | null;
  hours: number | null;
  rate: number | null;
};

export type PerformanceDashboardResponse = {
  year: number;
  countSource: CountSource;
  throughMonth: number | null;
  kpis: Kpi[];
  ytdHours: number | null;
  months: PerformanceMonth[];
  trends: RateTrend[];
  annualTrir: AnnualTrir[];
  yearsWithData: number[];
};

export type SaveMonthRequest = {
  totalHours: number;
  hourlyHours: number | null;
  salaryHours: number | null;
  monthClosed: boolean;
  /** The month's updatedAt when it was loaded, or null if it had no hours. */
  expectedUpdatedAt: string | null;
};

const BASE = "/api/v1/safety/performance";

export const performanceKeys = {
  all: ["safety", "performance"] as const,
  months: (year: number) => [...performanceKeys.all, "months", year] as const,
  dashboards: () => [...performanceKeys.all, "dashboard"] as const,
  dashboard: (year: number, throughMonth: number | null) =>
    [...performanceKeys.dashboards(), year, throughMonth] as const,
};

export function fetchPerformanceMonths(year: number, signal?: AbortSignal) {
  return apiGet<PerformanceYearResponse>(`${BASE}/months?year=${year}`, { signal });
}

export function fetchPerformanceDashboard(year: number, throughMonth: number | null, signal?: AbortSignal) {
  const through = throughMonth === null ? "" : `&throughMonth=${throughMonth}`;
  return apiGet<PerformanceDashboardResponse>(`${BASE}/dashboard?year=${year}${through}`, { signal });
}

export function saveMonth(year: number, month: number, request: SaveMonthRequest) {
  return apiSend<MonthHours>("PUT", `${BASE}/months/${year}/${month}`, request);
}

export function clearMonth(year: number, month: number, expectedUpdatedAt: string) {
  const query = new URLSearchParams({ expectedUpdatedAt });
  return apiSend<void>("DELETE", `${BASE}/months/${year}/${month}?${query}`);
}

export function isEditConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && error.detail?.error === "edit_conflict";
}

/** User-facing explanation of a failed Safety Performance request. */
export function describePerformanceError(error: unknown): string {
  if (!(error instanceof ApiError)) return "The API could not be reached.";
  switch (error.status) {
    case 401:
      return "Sign-in is required to view Safety data. User authentication is not enabled on this server yet.";
    case 403:
      return "You do not have permission for Safety Performance.";
    case 503:
      return "Safety data is unavailable because the database could not be reached.";
    default:
      return error.detail?.message ?? `The API responded with HTTP ${error.status}.`;
  }
}
