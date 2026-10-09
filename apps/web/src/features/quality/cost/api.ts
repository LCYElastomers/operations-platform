import { ApiError, apiGet, apiSend } from "@/lib/api-client";

/**
 * Mirrors the FastAPI Cost of Quality contract. Amounts and ratios are
 * full-precision decimals sent as strings; ratios are fractions
 * (0.0051 = 0.51%). null is not entered or not calculable, never 0.
 *
 * The classification (classes, categories, statuses, cost components) is
 * defined once by the API and read from `/records/options`; it is not
 * repeated here.
 */
export type CoqClass = "prevention" | "appraisal" | "internal_failure" | "external_failure";
export type QualityGroup = "good" | "poor";
export type FinancialStatus = "potential" | "validating" | "confirmed" | "closed";
export type OperationalStatus = "open" | "under_review" | "action_required" | "monitoring" | "closed";

/** The failure classes: COPQ is Internal Failure + External Failure. */
export const POOR_CLASSES: CoqClass[] = ["internal_failure", "external_failure"];

/** Cost component field names on a record, in form order (labels come from the options). */
export const COST_FIELDS = [
  "materialCost",
  "laborCost",
  "productionCost",
  "testingCost",
  "maintenanceCost",
  "freightCost",
  "disposalCost",
  "customerCost",
  "otherCost",
] as const;
export type CostField = (typeof COST_FIELDS)[number];

export type CostReference = { type: string; key: string; label: string | null };

/** What a user enters. Amounts are sent as typed; the API validates them. */
export type CostRecordFields = {
  recordDate: string;
  title: string;
  areaId: number | null;
  coqClass: CoqClass;
  categoryCode: string;
  description: string;
  product: string | null;
  campaign: string | null;
  lot: string | null;
  location: string | null;
  process: string | null;
  equipment: string | null;
  counterparty: string | null;
  /** A platform user; the API records their name. */
  ownerUserId: string | null;
  /** Only a name recorded before users existed, kept unchanged. */
  owner: string | null;
  notes: string | null;
  financialStatus: FinancialStatus;
  status: OperationalStatus;
  dueDate: string | null;
  dateClosed: string | null;
  resolutionNotes: string | null;
  recoveredCost: string | null;
  avoidedCost: string | null;
  references: CostReference[];
} & Record<CostField, string | null>;

export type CostRecord = Omit<CostRecordFields, "references"> & {
  id: number;
  /** Display identifier derived from the id, e.g. QC-00042. */
  recordNumber: string;
  areaName: string | null;
  coqClassLabel: string;
  qualityGroup: QualityGroup;
  categoryLabel: string;
  /** Sum of the entered components; null when none is entered. */
  totalCost: string | null;
  financialStatusLabel: string;
  statusLabel: string;
  /** Confirmed or Closed; otherwise the total is potential exposure. */
  costConfirmed: boolean;
  overdue: boolean;
  daysOpen: number;
  /** Total less recovered; null when no cost is entered. */
  netCost: string | null;
  references: (CostReference & { typeLabel: string })[];
  source: "manual" | "legacy_import";
  version: number;
  createdAt: string;
  createdBy: string;
  createdByName: string;
  updatedAt: string;
  updatedBy: string;
  updatedByName: string;
};

/** What the signed-in user may do. The interface uses it to offer controls; the API checks every request. */
export type CostAbilities = { create: boolean; edit: boolean; assign: boolean; confirmFinancial: boolean; close: boolean };

export type CostRecordList = { records: CostRecord[]; total: number; canEdit: boolean; abilities: CostAbilities };
export type CostRecordResponse = { record: CostRecord; canEdit: boolean; abilities: CostAbilities };

export type CodeLabel = { code: string; label: string };

export type CostRecordOptions = {
  areas: { id: number; code: string; name: string; active: boolean }[];
  classes: { code: CoqClass; label: string; qualityGroup: QualityGroup; categories: CodeLabel[] }[];
  financialStatuses: { code: FinancialStatus; label: string; confirmed: boolean }[];
  operationalStatuses: { code: OperationalStatus; label: string }[];
  costComponents: { field: CostField; label: string }[];
  referenceTypes: CodeLabel[];
  products: string[];
  /** Names already used on records, for the register filter. */
  owners: string[];
  canEdit: boolean;
  abilities: CostAbilities;
};

export type CostHistoryEvent = {
  occurredAt: string;
  actorId: string;
  /** The user's name when the change was made, or a system actor's label. */
  actorName: string;
  action: "create" | "update" | "delete";
  changeSetId: string;
  oldValue: Record<string, unknown> | null;
  newValue: Record<string, unknown> | null;
};

/** Totals of a set of records; confirmed cost and potential exposure kept apart. */
export type CostFigures = {
  count: number;
  confirmedCount: number;
  potentialCount: number;
  noCostCount: number;
  confirmed: string | null;
  potential: string | null;
  totalExposure: string | null;
  recovered: string | null;
  avoided: string | null;
  net: string | null;
};

export type CoqClassSummary = {
  code: CoqClass;
  label: string;
  qualityGroup: QualityGroup;
  figures: CostFigures;
  shareOfTotal: string | null;
};

export type CoqMatrix = {
  good: string | null;
  poor: string | null;
  total: string | null;
  poorPct: string | null;
  goodPotential: string | null;
  poorPotential: string | null;
  totalPotential: string | null;
};

export type CostMonth = {
  month: number;
  confirmed: Record<CoqClass, string | null>;
  potential: Record<CoqClass, string | null>;
  good: string | null;
  poor: string | null;
  poorPotential: string | null;
  netPoor: string | null;
  recordCount: number;
  productionLbs: string | null;
  salesRevenue: string | null;
  copqPctOfSales: string | null;
};

export type CostCategory = {
  coqClass: CoqClass;
  code: string;
  label: string;
  figures: CostFigures;
  shareOfClass: string | null;
  cumulativeShareOfPoor: string | null;
};

export type DataCheck = { status: "warning" | "info"; message: string };

export type CostSummary = {
  year: number | null;
  fromMonth: number;
  throughMonth: number;
  availableYears: number[];
  latestMonth: number | null;
  classes: CoqClassSummary[];
  matrix: CoqMatrix;
  copq: {
    figures: CostFigures;
    openCount: number;
    overdueCount: number;
    productionLbs: string | null;
    salesRevenue: string | null;
    internalCostPerLb: string | null;
    copqPctOfSales: string | null;
  };
  months: CostMonth[];
  categories: CostCategory[];
  aging: { label: string; minDays: number; maxDays: number | null; count: number; exposure: string | null }[];
  dataChecks: DataCheck[];
  definitions: { term: string; definition: string }[];
};

/** The filters shared by the Register, COPQ and the COQ Matrix. null / "" is not filtered. */
export type CostDimensions = {
  areaId: number | null;
  coqClass: CoqClass | null;
  category: string;
  product: string;
  owner: string;
  financialStatus: FinancialStatus | null;
};

export type CostSummaryQuery = CostDimensions & {
  year: number | null;
  from: number | null;
  through: number | null;
  /** Internal and External Failure records only (the COPQ view). */
  poorOnly: boolean;
};

export type CostRecordQuery = CostDimensions & {
  from: string;
  to: string;
  status: OperationalStatus | null;
  open: boolean;
  /** Restricts to classes when no single class is chosen (COPQ: the failure classes). */
  classes: CoqClass[];
  search: string;
};

export const NO_DIMENSIONS: CostDimensions = {
  areaId: null,
  coqClass: null,
  category: "",
  product: "",
  owner: "",
  financialStatus: null,
};

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
  summary: (query: CostSummaryQuery) => [...costKeys.all, "summary", query] as const,
  records: (query: CostRecordQuery) => [...costKeys.all, "records", query] as const,
  record: (id: number) => [...costKeys.all, "record", id] as const,
  history: (id: number) => [...costKeys.all, "history", id] as const,
  options: () => [...costKeys.all, "options"] as const,
  estimator: () => [...costKeys.all, "estimator"] as const,
};

const BASE = "/api/v1/quality/cost";

function dimensionParams(params: URLSearchParams, query: CostDimensions) {
  if (query.areaId !== null) params.set("areaId", String(query.areaId));
  if (query.coqClass !== null) params.append("coqClass", query.coqClass);
  if (query.category) params.set("category", query.category);
  if (query.product.trim()) params.set("product", query.product.trim());
  if (query.owner.trim()) params.set("owner", query.owner.trim());
  if (query.financialStatus !== null) params.append("financialStatus", query.financialStatus);
}

function withParams(path: string, params: URLSearchParams) {
  return params.size > 0 ? `${path}?${params}` : path;
}

export function fetchCostSummary(query: CostSummaryQuery, signal?: AbortSignal) {
  const params = new URLSearchParams();
  if (query.year !== null) params.set("year", String(query.year));
  if (query.from !== null) params.set("from", String(query.from));
  if (query.through !== null) params.set("through", String(query.through));
  dimensionParams(params, query);
  if (query.poorOnly) params.set("poorOnly", "true");
  return apiGet<CostSummary>(withParams(`${BASE}/summary`, params), { signal });
}

export function fetchCostRecords(query: CostRecordQuery, signal?: AbortSignal) {
  const params = new URLSearchParams();
  if (query.from) params.set("from", query.from);
  if (query.to) params.set("to", query.to);
  dimensionParams(params, query);
  if (query.coqClass === null) for (const code of query.classes) params.append("coqClass", code);
  if (query.status !== null) params.append("status", query.status);
  if (query.open) params.set("open", "true");
  if (query.search.trim()) params.set("search", query.search.trim());
  return apiGet<CostRecordList>(withParams(`${BASE}/records`, params), { signal });
}

export function fetchCostRecordOptions(signal?: AbortSignal) {
  return apiGet<CostRecordOptions>(`${BASE}/records/options`, { signal });
}

export function fetchCostRecord(id: number, signal?: AbortSignal) {
  return apiGet<CostRecordResponse>(`${BASE}/records/${id}`, { signal });
}

export function fetchCostRecordHistory(id: number, signal?: AbortSignal) {
  return apiGet<{ recordId: number; events: CostHistoryEvent[] }>(`${BASE}/records/${id}/history`, { signal });
}

export function createCostRecord(body: CostRecordFields) {
  return apiSend<CostRecordResponse>("POST", `${BASE}/records`, body);
}

export function updateCostRecord(id: number, body: CostRecordFields & { version: number }) {
  return apiSend<CostRecordResponse>("PUT", `${BASE}/records/${id}`, body);
}

/** A save refused by a record rule (422, naming the field) or an edit conflict (409). */
export function costRecordError(
  error: unknown,
): { message: string; field: string | null; current: CostRecord | null } | null {
  if (!(error instanceof ApiError)) return null;
  const detail = error.detail as { message?: string; field?: unknown; current?: CostRecord } | undefined;
  if (error.status === 409) {
    return {
      message: detail?.message ?? "This record changed since you loaded it. Nothing was saved.",
      field: null,
      current: detail?.current ?? null,
    };
  }
  if (error.status === 422 && detail?.message) {
    return { message: detail.message, field: typeof detail.field === "string" ? detail.field : null, current: null };
  }
  return null;
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
      return "Your session has ended. Sign in again to continue.";
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
