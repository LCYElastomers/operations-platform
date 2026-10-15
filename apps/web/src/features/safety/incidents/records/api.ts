import { ApiError, apiGet, apiSend } from "@/lib/api-client";

/** Mirrors the FastAPI Incident and Near Miss records contract. */
export type EventType = "incident" | "near_miss";
export type RecordStatus = "active" | "voided" | "reclassified";

export type IncidentRecord = {
  id: number;
  /** Normalized, e.g. LCY-2026-037; null when the source gave none. */
  incidentNumber: string | null;
  eventType: EventType;
  /** ISO date. */
  incidentDate: string;
  reportingYear: number;
  reportingMonth: number;
  description: string;
  areaId: number | null;
  areaCode: string | null;
  areaName: string | null;
  classificationCategoryId: number | null;
  classificationCode: string | null;
  classificationName: string | null;
  status: RecordStatus;
  statusReason: string | null;
  relatedIncidentId: number | null;
  relatedIncidentNumber: string | null;
  source: "manual" | "legacy_import";
  version: number;
  createdAt: string;
  createdBy: string;
  updatedAt: string;
  updatedBy: string;
  createdByName?: string | null;
  updatedByName?: string | null;
  /** Classifications beyond `classificationCategoryId`. */
  additionalClassifications?: ClassificationRef[];
  lopcDetails?: (LopcDetails & DetailStamp) | null;
  damageDetails?: (DamageDetails & DetailStamp) | null;
  pitDetails?: (PitDetails & DetailStamp) | null;
  seriousRiskDetails?: (SeriousRiskDetails & DetailStamp) | null;
};

export type ClassificationRef = { id: number; code: string; name: string };
type DetailStamp = { updatedAt: string; updatedBy: string };

/** Record details. Every field may be null: not recorded (Unknown), never No or 0. */
export type LopcDetails = {
  isLopc: boolean | null;
  materialName: string | null;
  /** Exact decimal as text, e.g. "0.5". */
  estimatedQuantity: string | null;
  quantityUnitCode: string | null;
  equipmentTag: string | null;
  failureMechanismCode: string | null;
  contributingFactorCode: string | null;
  secondaryContainmentStatusCode: string | null;
  processSafetyIncident: boolean | null;
  notes: string | null;
};

export type DamageDetails = {
  damageKindCode: string | null;
  assetOrPropertyName: string | null;
  equipmentTag: string | null;
  assetType: string | null;
  damageDescription: string | null;
  operationalImpact: string | null;
  estimatedCost: string | null;
  currencyCode: string | null;
  workOrderReference: string | null;
  outOfService: boolean | null;
  repairRequired: boolean | null;
  notes: string | null;
};

export type PitDetails = {
  vehicleIdentifier: string | null;
  vehicleType: string | null;
  ownershipTypeCode: string | null;
  operatingCompany: string | null;
  impactedAssetOrProperty: string | null;
  damageOccurred: boolean | null;
  notes: string | null;
};

export type SeriousRiskDetails = {
  isPsif: boolean;
  potentialSeverityCode: string | null;
  seriousRiskCategoryCode: string | null;
  rationale: string | null;
};

/**
 * Further classifications and details sent with a record. An omitted key leaves
 * the stored value unchanged; null removes the detail.
 */
export type DetailFields = {
  additionalClassificationIds?: number[];
  lopcDetails?: Partial<LopcDetails> | null;
  damageDetails?: Partial<DamageDetails> | null;
  pitDetails?: Partial<PitDetails> | null;
  seriousRiskDetails?: (Partial<SeriousRiskDetails> & { isPsif: boolean }) | null;
};

export type DetailKind = "classifications" | "lopc" | "damage" | "pit" | "serious_risk";

/** What the signed-in user may do; `*Types` list the record types each action is allowed for. */
export type RecordPermissions = {
  canEdit: boolean;
  canManage: boolean;
  canViewHistory: boolean;
  canClassify?: boolean;
  viewableTypes?: EventType[];
  creatableTypes?: EventType[];
  editableTypes?: EventType[];
  voidableTypes?: EventType[];
};

/** Per-type ability, falling back to the overall flag for older responses. */
export function allowsType(
  permissions: RecordPermissions | undefined,
  list: "creatableTypes" | "editableTypes" | "voidableTypes",
  type: EventType,
): boolean {
  if (!permissions) return false;
  const types = permissions[list];
  if (types) return types.includes(type);
  return list === "voidableTypes" ? permissions.canManage : permissions.canEdit;
}

export type RecordListResponse = RecordPermissions & { records: IncidentRecord[]; total: number };
export type RecordResponse = RecordPermissions & { record: IncidentRecord };
export type ReclassifyResponse = RecordPermissions & { record: IncidentRecord; replacement: IncidentRecord };

export type RecordOption = { id: number; code: string; name: string; active: boolean };
export type DetailCode = { code: string; name: string; active: boolean };
export type RecordOptionsResponse = {
  areas: RecordOption[];
  classifications: RecordOption[];
  /** Taxonomy -> codes, e.g. quantity_unit, lopc_failure_mechanism, lopc_contributing_factor. */
  detailCodes?: Record<string, DetailCode[]>;
};

export type HistoryEvent = {
  occurredAt: string;
  actorId: string;
  actorName?: string;
  action: "create" | "update" | "delete";
  changeSetId: string;
  oldValue: Record<string, unknown> | null;
  newValue: Record<string, unknown> | null;
  /** Set for a change to the record's further classifications or one of its details. */
  detail?: DetailKind | null;
};
export type HistoryResponse = { recordId: number; events: HistoryEvent[] };

export type ReconciliationState =
  | "reconciled"
  | "records_missing"
  | "records_exceed_total"
  | "total_unreported_with_records"
  | "explicit_zero_with_records"
  | "no_total_and_no_records";

export type MonthReconciliation = {
  month: number;
  eventType: EventType;
  /** The stored monthly total; null when the month is unreported. */
  monthlyTotal: number | null;
  /** Active records dated in the month. */
  documented: number;
  state: ReconciliationState;
};

export type ReconciliationResponse = RecordPermissions & { year: number; months: MonthReconciliation[] };

export type RecordFields = {
  incidentNumber: string | null;
  incidentDate: string;
  description: string;
  areaId: number | null;
  classificationCategoryId: number | null;
};

/** The month a record is entered from; the API refuses a date outside it. */
export type MonthContext = { reportingYear: number; reportingMonth: number };

export type RecordFilter = {
  year?: number;
  through?: number;
  month?: number;
  eventType?: EventType;
  areaId?: number;
  classificationId?: number;
  statuses?: RecordStatus[];
  search?: string;
} & DrillFilter;

/**
 * Dashboard drill-through filters: an Event Experience category, and LOPC detail
 * values (a code, or "unknown" for not recorded).
 */
export type DrillFilter = {
  category?: string;
  failureMechanism?: string;
  containment?: string;
  contributingFactor?: string;
  quantityUnit?: string;
  processSafety?: "yes" | "no" | "unknown";
  material?: string;
  equipmentTag?: string;
};

export const DRILL_KEYS = [
  "category",
  "failureMechanism",
  "containment",
  "contributingFactor",
  "quantityUnit",
  "processSafety",
  "material",
  "equipmentTag",
] as const satisfies readonly (keyof DrillFilter)[];

const BASE = "/api/v1/safety/incidents/records";

export const recordKeys = {
  all: ["safety", "incidents", "records"] as const,
  list: (filter: RecordFilter) => [...recordKeys.all, "list", filter] as const,
  options: () => [...recordKeys.all, "options"] as const,
  reconciliation: (year: number) => [...recordKeys.all, "reconciliation", year] as const,
  history: (id: number) => [...recordKeys.all, "history", id] as const,
  record: (id: number) => [...recordKeys.all, "record", id] as const,
  /** Record-derived analytics; under `all`, so every record write refreshes them. */
  insights: (name: string, year: number, period: string | number | null) =>
    [...recordKeys.all, "insights", name, year, period] as const,
};

export function recordQuery(filter: RecordFilter): string {
  const params = new URLSearchParams();
  if (filter.year !== undefined) params.set("year", String(filter.year));
  if (filter.through !== undefined) params.set("through", String(filter.through));
  if (filter.month !== undefined) params.set("month", String(filter.month));
  if (filter.eventType) params.set("eventType", filter.eventType);
  if (filter.areaId !== undefined) params.set("areaId", String(filter.areaId));
  if (filter.classificationId !== undefined) params.set("classificationId", String(filter.classificationId));
  for (const status of filter.statuses ?? []) params.append("status", status);
  if (filter.search?.trim()) params.set("search", filter.search.trim());
  for (const key of DRILL_KEYS) {
    const value = filter[key];
    if (value) params.set(key, value);
  }
  return params.toString();
}

export function fetchRecord(id: number, signal?: AbortSignal) {
  return apiGet<RecordResponse>(`${BASE}/${id}`, { signal });
}

export function fetchRecords(filter: RecordFilter, signal?: AbortSignal) {
  return apiGet<RecordListResponse>(`${BASE}?${recordQuery(filter)}`, { signal });
}

export function fetchRecordOptions(signal?: AbortSignal) {
  return apiGet<RecordOptionsResponse>(`${BASE}/options`, { signal });
}

export function fetchReconciliation(year: number, signal?: AbortSignal) {
  return apiGet<ReconciliationResponse>(`${BASE}/reconciliation?year=${year}`, { signal });
}

export function fetchHistory(id: number, signal?: AbortSignal) {
  return apiGet<HistoryResponse>(`${BASE}/${id}/history`, { signal });
}

export type CreateBody = RecordFields & DetailFields & { eventType: EventType } & Partial<MonthContext>;
export type UpdateBody = RecordFields & DetailFields & MonthContext & { version: number };

export function createRecord(body: CreateBody) {
  return apiSend<RecordResponse>("POST", BASE, body);
}

export function updateRecord(id: number, body: UpdateBody) {
  return apiSend<RecordResponse>("PUT", `${BASE}/${id}`, body);
}

export function voidRecord(id: number, body: { version: number; reason: string }) {
  return apiSend<RecordResponse>("POST", `${BASE}/${id}/void`, body);
}

export type ReclassifyBody = { version: number; reason: string } & (
  | { replacement: RecordFields; replacementId?: never }
  | { replacementId: number; replacement?: never }
);

export function reclassifyRecord(id: number, body: ReclassifyBody) {
  return apiSend<ReclassifyResponse>("POST", `${BASE}/${id}/reclassify`, body);
}

/** The API's field-level message for a refused write, if any. */
export function recordError(error: unknown): { message: string; field: string | null; conflict: boolean } | null {
  if (!(error instanceof ApiError)) return null;
  const detail = error.detail;
  if (error.status === 409) {
    return { message: detail?.message ?? "This record changed since you loaded it.", field: null, conflict: true };
  }
  if (error.status === 422 && detail?.message) {
    return { message: detail.message, field: typeof detail.field === "string" ? detail.field : null, conflict: false };
  }
  return null;
}
