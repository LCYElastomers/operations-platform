import { apiGet } from "@/lib/api-client";

import type { EventType } from "./api";

/** Mirrors the FastAPI record-derived analytics (Event Experience, LOPC records, serious risk). */
export type CompletenessStatus =
  | "complete"
  | "no_event_in_scope"
  | "insufficient_classification_data"
  | "source_unavailable";

export type EventSummary = {
  id: number;
  incidentNumber: string | null;
  eventType: EventType;
  incidentDate: string;
  areaId: number | null;
  areaName: string | null;
  classifications: string[];
  description: string;
};

export type ExperienceCategory = {
  code: string;
  name: string;
  year: number;
  asOf: string;
  status: CompletenessStatus;
  latestEventDate: string | null;
  /** asOf - latestEventDate in calendar days; null when no event is known. */
  daysSinceLatestEvent: number | null;
  latestInSelectedYear: boolean;
  /** Classified records Jan 1..asOf; a minimum when `ytdEventsComplete` is false. */
  ytdEvents: number;
  ytdEventsComplete: boolean;
  latestEvent: EventSummary | null;
  /** The stored monthly count Jan..asOf month; null when unreported. */
  monthlyCount: number | null;
  warnings: string[];
};

export type EventExperienceResponse = {
  year: number;
  asOf: string;
  siteTimeZone: string;
  includesNearMisses: boolean;
  categories: ExperienceCategory[];
};

/** `key` is the drill-through value: a code, "unknown", or an id as text; null when not filterable. */
export type CountRow = { key: string | null; name: string; count: number };
export type QuantityRow = { unitCode: string; unitName: string; total: string; records: number };

export type LopcRecordsResponse = {
  year: number;
  throughMonth: number | null;
  records: number;
  withDetails: number;
  monthlyCount: number | null;
  monthlyCountComplete: boolean;
  byFailureMechanism: CountRow[];
  byMaterial: CountRow[];
  byEquipment: CountRow[];
  byContainment: CountRow[];
  byProcessSafety: CountRow[];
  quantities: QuantityRow[];
  recordsWithoutQuantity: number;
  recent: EventSummary[];
  warnings: string[];
};

export type SeriousRiskResponse = {
  year: number;
  throughMonth: number | null;
  includesNearMisses: boolean;
  psifRecords: number;
  monthlyCount: number | null;
  monthlyCountComplete: boolean;
  monthly: { month: number; records: number; monthlyCount: number | null }[];
  byClassification: CountRow[];
  byArea: CountRow[];
  byContributingFactor: CountRow[];
  bySeverity: CountRow[];
  recent: EventSummary[];
  warnings: string[];
};

const BASE = "/api/v1/safety/incidents/analytics";

export function fetchEventExperience(year: number, signal?: AbortSignal) {
  return apiGet<EventExperienceResponse>(`${BASE}/event-experience?year=${year}`, { signal });
}

function period(year: number, through: number | null) {
  const params = new URLSearchParams({ year: String(year) });
  if (through !== null) params.set("through", String(through));
  return params.toString();
}

export function fetchLopcRecords(year: number, through: number | null, signal?: AbortSignal) {
  return apiGet<LopcRecordsResponse>(`${BASE}/lopc-records?${period(year, through)}`, { signal });
}

export function fetchSeriousRisk(year: number, through: number | null, signal?: AbortSignal) {
  return apiGet<SeriousRiskResponse>(`${BASE}/serious-risk?${period(year, through)}`, { signal });
}
