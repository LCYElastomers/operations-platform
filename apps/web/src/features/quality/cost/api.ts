import { ApiError, apiGet, apiSend } from "@/lib/api-client";

/**
 * Mirrors the FastAPI Cost of Quality contract. Amounts, quantities and ratios
 * are full-precision decimals sent as strings; ratios are fractions
 * (0.0051 = 0.51%). null is not reported or not calculable, never 0.
 */
export type CoqClass = "prevention" | "appraisal" | "internal_failure" | "external_failure";

export type CostMonth = {
  year: number;
  month: number;
  reported: boolean;
  totalProductionLbs: string | null;
  scrapProducedLbs: string | null;
  offspecProducedLbs: string | null;
  scrapLossPerLb: string | null;
  offspecLossPerLb: string | null;
  complaintCount: number | null;
  returnedProductLbs: string | null;
  salesRevenue: string | null;
  /** Calculated cost per element code. */
  elements: Record<string, string | null>;
  internalFailure: string | null;
  externalFailure: string | null;
  copq: string | null;
  internalCostPerLb: string | null;
  externalPctOfSales: string | null;
  copqPctOfSales: string | null;
  note: string | null;
};

export type CostPeriod = {
  fromMonth: number | null;
  throughMonth: number | null;
  monthsInPeriod: number;
  monthsReported: number;
  reportedMonths: number[];
  internalFailure: string | null;
  externalFailure: string | null;
  copq: string | null;
  totalProductionLbs: string | null;
  salesRevenue: string | null;
  complaintCount: number | null;
  returnedProductLbs: string | null;
  copqPctOfSales: string | null;
  externalPctOfSales: string | null;
  internalCostPerLb: string | null;
};

export type CostElement = {
  code: string;
  label: string;
  coqClass: CoqClass;
  category: string;
  /** The column heading in the source workbook. */
  sourceTerm: string;
  value: string | null;
  shareOfCopq: string | null;
  cumulativeShare: string | null;
};

export type CoqClassValue = {
  code: CoqClass;
  label: string;
  value: string | null;
  /** False: the source records no costs of this class. */
  recorded: boolean;
  shareOfRecorded: string | null;
};

export type CoqMatrix = {
  classes: CoqClassValue[];
  good: string | null;
  poor: string | null;
  total: string | null;
  poorPct: string | null;
  recordedTotal: string | null;
  unavailableReason: string | null;
};

export type DataCheck = { year: number | null; month: number | null; status: "warning" | "info"; message: string };

export type CostSummary = {
  year: number | null;
  availableYears: number[];
  latestReportedMonth: number | null;
  months: CostMonth[];
  period: CostPeriod;
  elements: CostElement[];
  matrix: CoqMatrix;
  dataChecks: DataCheck[];
  definitions: { term: string; definition: string }[];
  source: string;
};

export type CostPeriodQuery = { year: number | null; from: number | null; through: number | null };

export type PackageType = "Bags" | "Box" | "Single sacks" | "Double stack supersacks";

export type EstimatorReference = {
  source: string;
  products: { code: string; standardRateMtPerDay: string }[];
  packageTypes: PackageType[];
  assumptions: { label: string; value: string; unit: string }[];
  guidance: string[];
  notes: string[];
};

/** Numbers as typed (strings) are sent unchanged; the API validates them. */
export type EstimateRequest = {
  product?: string;
  downtime?: { downtimeHours: string };
  lowerProduction?: { flowRateLbPerHour: string; hours: string };
  scrap?: { quantityLbs: string };
  cGrade?: { quantityLbs: string };
  rework?: {
    productionRateReductionLbPerHour: string;
    reworkingRateLbPerHour: string;
    quantityLbs: string;
    packageType: PackageType;
    packageLoadLbPerPiece: string;
  };
  repack?: {
    quantityLbs: string;
    packageType: PackageType;
    packageLoadLbPerPiece: string;
    extraPersons: string;
    overtimeHoursPerPerson: string;
    payRateUsdPerHour: string;
  };
};

export type EstimateLine = {
  code: string;
  label: string;
  totalKusd: string;
  formula: string;
  steps: { label: string; value: string; unit: string }[];
};

export type Estimate = {
  lines: EstimateLine[];
  totalKusd: string;
  totalUsd: string;
  warnings: string[];
  source: string;
};

export const costKeys = {
  all: ["quality", "cost"] as const,
  summary: (query: CostPeriodQuery) => [...costKeys.all, "summary", query.year, query.from, query.through] as const,
  estimator: () => [...costKeys.all, "estimator"] as const,
};

export function fetchCostSummary(query: CostPeriodQuery, signal?: AbortSignal) {
  const params = new URLSearchParams();
  if (query.year !== null) params.set("year", String(query.year));
  if (query.from !== null) params.set("from", String(query.from));
  if (query.through !== null) params.set("through", String(query.through));
  const search = params.size > 0 ? `?${params}` : "";
  return apiGet<CostSummary>(`/api/v1/quality/cost/summary${search}`, { signal });
}

export function fetchEstimatorReference(signal?: AbortSignal) {
  return apiGet<EstimatorReference>("/api/v1/quality/cost/estimator", { signal });
}

export function requestEstimate(request: EstimateRequest) {
  return apiSend<Estimate>("POST", "/api/v1/quality/cost/estimate", request);
}

export function describeCostError(error: unknown): string {
  if (!(error instanceof ApiError)) return "The API could not be reached.";
  switch (error.status) {
    case 401:
      return "Sign-in is required to view Cost of Quality data. User authentication is not enabled on this server yet.";
    case 403:
      return "You do not have permission to view Cost of Quality data.";
    case 422:
      return error.detail?.message ?? "Check the values entered.";
    case 503:
      return "Cost of Quality data is unavailable because the database could not be reached.";
    default:
      return error.detail?.message ?? `The API responded with HTTP ${error.status}.`;
  }
}
