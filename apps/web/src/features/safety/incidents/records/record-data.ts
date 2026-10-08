import type { EventType, IncidentRecord, MonthReconciliation, ReconciliationState, RecordStatus } from "./api";

export const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
] as const;

export const EVENT_LABELS: Record<EventType, { one: string; many: string }> = {
  incident: { one: "Incident", many: "Incidents" },
  near_miss: { one: "Near Miss", many: "Near Misses" },
};

export const OTHER_EVENT: Record<EventType, EventType> = { incident: "near_miss", near_miss: "incident" };

export const STATUS_LABELS: Record<RecordStatus, string> = {
  active: "Active",
  voided: "Voided",
  reclassified: "Reclassified",
};

/** The grid section and category codes that carry the authoritative monthly totals. */
export const TOTALS_SECTION = "incident_near_miss_totals";
export const EVENT_CATEGORY_CODES: Record<string, EventType> = { incident: "incident", near_miss: "near_miss" };

export type StateTone = "ok" | "warning" | "neutral";

const STATE_TEXT: Record<ReconciliationState, { tone: StateTone; short: string }> = {
  reconciled: { tone: "ok", short: "Records match the total" },
  records_missing: { tone: "warning", short: "Fewer records than the total" },
  records_exceed_total: { tone: "warning", short: "More records than the total" },
  total_unreported_with_records: { tone: "warning", short: "Records but no reported total" },
  explicit_zero_with_records: { tone: "warning", short: "Records but a reported total of 0" },
  no_total_and_no_records: { tone: "neutral", short: "No total and no records" },
};

export function stateTone(state: ReconciliationState): StateTone {
  return STATE_TEXT[state].tone;
}

/** A full, plain-language reconciliation statement. Warnings only: totals stay authoritative. */
export function describeReconciliation(month: MonthReconciliation): string {
  const { monthlyTotal: total, documented } = month;
  const records = `${documented} ${documented === 1 ? "record" : "records"}`;
  switch (month.state) {
    case "reconciled":
      return total === 0
        ? "Reported total 0 and no records."
        : `Reported total ${total}; ${records} documented. They match.`;
    case "records_missing":
      return `Reported total ${total}; ${records} documented. ${total! - documented} not yet documented.`;
    case "records_exceed_total":
      return `Reported total ${total}; ${records} documented, ${documented - total!} more than the total. The total is not changed.`;
    case "total_unreported_with_records":
      return `No total is reported; ${records} documented. The total is not filled in from records.`;
    case "explicit_zero_with_records":
      return `Reported total 0, but ${records} documented. The total is not changed.`;
    case "no_total_and_no_records":
      return "No total is reported and no records are documented.";
  }
}

export function stateShort(state: ReconciliationState): string {
  return STATE_TEXT[state].short;
}

/** e.g. "Manage 3 Incident records for January 2026" or "Add Near Miss record for May 2026". */
export function monthActionLabel(eventType: EventType, documented: number, year: number, month: number): string {
  const when = `${MONTH_NAMES[month - 1]} ${year}`;
  const kind = EVENT_LABELS[eventType].one;
  if (documented === 0) return `Add ${kind} record for ${when}`;
  return `Manage ${documented} ${kind} ${documented === 1 ? "record" : "records"} for ${when}`;
}

/** e.g. "January 2026 Incidents". */
export function monthTitle(eventType: EventType, year: number, month: number): string {
  return `${MONTH_NAMES[month - 1]} ${year} ${EVENT_LABELS[eventType].many}`;
}

/** First and last selectable date of a month, never after today. null when the month has not started. */
export function monthDateRange(year: number, month: number, today: string): { min: string; max: string } | null {
  const pad = (value: number) => String(value).padStart(2, "0");
  const min = `${year}-${pad(month)}-01`;
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const end = `${year}-${pad(month)}-${pad(last)}`;
  if (min > today) return null;
  return { min, max: end < today ? end : today };
}

export function formatRecordDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return `${MONTH_NAMES[month - 1].slice(0, 3)} ${day}, ${year}`;
}

export function recordName(record: Pick<IncidentRecord, "incidentNumber" | "eventType" | "incidentDate">): string {
  return record.incidentNumber ?? `${EVENT_LABELS[record.eventType].one} of ${formatRecordDate(record.incidentDate)}`;
}

/** Field names shown in record history, in display order. */
export const HISTORY_FIELDS: [key: string, label: string][] = [
  ["incident_number", "Number"],
  ["event_type", "Type"],
  ["incident_date", "Date"],
  ["description", "Description"],
  ["area_id", "Area"],
  ["classification_category_id", "Classification"],
  ["status", "Status"],
  ["status_reason", "Reason"],
  ["related_incident_id", "Related record"],
  ["source", "Source"],
  ["version", "Version"],
];

export type HistoryChange = { label: string; from: string; to: string };

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

/** Field-by-field differences of one audit event; a creation lists the values set. */
export function historyChanges(
  oldValue: Record<string, unknown> | null,
  newValue: Record<string, unknown> | null,
  names: { areas: Map<number, string>; classifications: Map<number, string> },
): HistoryChange[] {
  const label = (key: string, value: unknown) => {
    if (value === null || value === undefined) return "—";
    if (key === "area_id") return names.areas.get(Number(value)) ?? `#${value}`;
    if (key === "classification_category_id") return names.classifications.get(Number(value)) ?? `#${value}`;
    if (key === "event_type") return EVENT_LABELS[value as EventType]?.one ?? show(value);
    if (key === "status") return STATUS_LABELS[value as RecordStatus] ?? show(value);
    return show(value);
  };
  return HISTORY_FIELDS.flatMap(([key, name]) => {
    if (key === "version") return [];
    const before = oldValue?.[key];
    const after = newValue?.[key];
    if (oldValue && JSON.stringify(before ?? null) === JSON.stringify(after ?? null)) return [];
    if (!oldValue && (after === null || after === undefined)) return [];
    return [{ label: name, from: oldValue ? label(key, before) : "", to: label(key, after) }];
  });
}
