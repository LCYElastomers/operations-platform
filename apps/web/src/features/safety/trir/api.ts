import { apiGet } from "@/lib/api-client";

/**
 * Mirrors the FastAPI TRIR Experience contract. `rate` is the full-precision
 * decimal as a string; `display` the same value rounded half-up to 2 places.
 */
export type MissingMonth = {
  year: number;
  month: number;
  reason: "not_reported" | "open" | "zero_hours" | "count_not_confirmed";
};

export type TrirCalculation = {
  year: number;
  basis: "safety_performance_monthly" | "historical_annual" | null;
  /** The year of fromMonth: the previous year for a rolling 12-month window that starts in it. */
  fromYear: number | null;
  fromMonth: number | null;
  throughMonth: number | null;
  recordables: number | null;
  hours: number | null;
  rate: string | null;
  display: string | null;
  formula: string | null;
  numeratorSource: string;
  denominatorSource: string;
  complete: boolean;
  missingMonths: MissingMonth[];
  unavailableReason: string | null;
};

export type TrirBenchmark = { year: number; value: string | null; source: string | null };

export type TrirComparison = {
  benchmarkYear: number | null;
  benchmark: string | null;
  difference: string | null;
  differenceDisplay: string | null;
  status: "below" | "equal" | "above" | "unavailable";
  statement: string;
};

export type TrirHistoryRow = {
  year: number;
  calculation: TrirCalculation;
  incidentCount: number | null;
  legacyTrir: string | null;
  legacyTir: string | null;
  legacyDifference: string | null;
  benchmark: TrirBenchmark | null;
  comparison: TrirComparison;
  partial: boolean;
  note: string | null;
};

export type TrirMonth = {
  month: number;
  state: "closed" | "open" | "not_reported" | "zero_hours" | "count_not_confirmed";
  recordables: number | null;
  hours: number | null;
  ytdRecordables: number | null;
  ytdHours: number | null;
  ytdRate: string | null;
  ytdDisplay: string | null;
};

export type TrirDataQualityItem = { year: number | null; check: string; status: "ok" | "warning"; message: string };

export type TrirMethodology = {
  formula: string;
  rateBase: number;
  numerator: string;
  denominator: string;
  contractorHours: string;
  benchmark: string;
  cutoff: string;
  rounding: string;
  comparisonTolerance: string;
  historicalYears: string;
  unreportedMonths: string;
  legacyTir: string;
};

export type TrirStatus = {
  year: number;
  latestCompleteMonth: number | null;
  throughMonth: number | null;
  complete: boolean;
  historyYears: number[];
};

export type TrirExperience = {
  year: number;
  status: TrirStatus;
  current: TrirCalculation;
  comparison: TrirComparison;
  rolling12: TrirCalculation;
  incidentCount: number | null;
  history: TrirHistoryRow[];
  monthly: TrirMonth[];
  benchmarks: TrirBenchmark[];
  dataQuality: TrirDataQualityItem[];
  methodology: TrirMethodology;
};

export const trirKeys = {
  all: ["safety", "trir"] as const,
  experience: (year: number, through: number | null) => [...trirKeys.all, "experience", year, through] as const,
};

export function fetchTrirExperience(year: number, through: number | null, signal?: AbortSignal) {
  const params = new URLSearchParams({ year: String(year) });
  if (through !== null) params.set("through", String(through));
  return apiGet<TrirExperience>(`/api/v1/safety/trir/experience?${params}`, { signal });
}
