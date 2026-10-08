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
};

export type RecordPermissions = { canEdit: boolean; canManage: boolean; canViewHistory: boolean };

export type RecordListResponse = RecordPermissions & { records: IncidentRecord[]; total: number };
export type RecordResponse = RecordPermissions & { record: IncidentRecord };
export type ReclassifyResponse = RecordPermissions & { record: IncidentRecord; replacement: IncidentRecord };

export type RecordOption = { id: number; code: string; name: string; active: boolean };
export type RecordOptionsResponse = { areas: RecordOption[]; classifications: RecordOption[] };

export type HistoryEvent = {
  occurredAt: string;
  actorId: string;
  action: "create" | "update" | "delete";
  changeSetId: string;
  oldValue: Record<string, unknown> | null;
  newValue: Record<string, unknown> | null;
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
};

const BASE = "/api/v1/safety/incidents/records";

export const recordKeys = {
  all: ["safety", "incidents", "records"] as const,
  list: (filter: RecordFilter) => [...recordKeys.all, "list", filter] as const,
  options: () => [...recordKeys.all, "options"] as const,
  reconciliation: (year: number) => [...recordKeys.all, "reconciliation", year] as const,
  history: (id: number) => [...recordKeys.all, "history", id] as const,
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
  return params.toString();
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

export function createRecord(body: RecordFields & { eventType: EventType } & Partial<MonthContext>) {
  return apiSend<RecordResponse>("POST", BASE, body);
}

export function updateRecord(id: number, body: RecordFields & MonthContext & { version: number }) {
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
