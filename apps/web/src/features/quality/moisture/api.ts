import { apiGet } from "@/lib/api-client";

/** Mirrors the FastAPI moisture contract. Measurements: null = missing, 0 = zero. */
export type MoistureRecord = {
  date: string;
  campaignNo: string | null;
  lot: string | null;
  location: string | null;
  product: string | null;
  avgMoisture: number | null;
  avgColor: number | null;
  avgCombinedBd: number | null;
};

export type DataSourceInfo = {
  kind: string;
  isFixture: boolean;
  label: string;
};

/**
 * One Product + Lot master row. Location is not part of the key; means are over
 * the lot's non-null location-level values. Records without a lot are never merged.
 */
export type MoistureLot = {
  product: string | null;
  lot: string | null;
  firstDate: string;
  lastDate: string;
  campaignNos: string[];
  locations: string[];
  /** Location-level records in this lot. */
  recordCount: number;
  avgMoisture: number | null;
  avgColor: number | null;
  avgCombinedBd: number | null;
  moistureValueCount: number;
  colorValueCount: number;
  combinedBdValueCount: number;
};

export type MoistureLotDetail = MoistureLot & {
  /** Location-level records, oldest first. */
  records: MoistureRecord[];
};

export type MoistureLotsResponse = {
  dataSource: DataSourceInfo;
  /** Matching Product + Lot master rows. */
  totalMatching: number;
  limit: number;
  lots: MoistureLotDetail[];
};

export type MoistureSummary = {
  /** Product + Lot master rows. */
  lotCount: number;
  /** Location-level records. */
  recordCount: number;
  avgMoisture: number | null;
  avgColor: number | null;
  avgCombinedBd: number | null;
  moistureValueCount: number;
  colorValueCount: number;
  combinedBdValueCount: number;
};

export type MoistureTrendsResponse = {
  dataSource: DataSourceInfo;
  summary: MoistureSummary;
  /** By latest measurement date, oldest first. */
  lots: MoistureLot[];
};

export type MoistureFiltersResponse = {
  dataSource: DataSourceInfo;
  products: string[];
  locations: string[];
  dateRange: { min: string | null; max: string | null };
};

/** UI filter state. Empty string means "not filtered". */
export type MoistureFilters = {
  product: string;
  location: string;
  search: string;
  startDate: string;
  endDate: string;
};

export const EMPTY_FILTERS: MoistureFilters = {
  product: "",
  location: "",
  search: "",
  startDate: "",
  endDate: "",
};

export function hasActiveFilters(filters: MoistureFilters): boolean {
  return Object.values(filters).some((value) => value.trim() !== "");
}

export function isDateRangeInvalid(filters: MoistureFilters): boolean {
  return filters.startDate !== "" && filters.endDate !== "" && filters.startDate > filters.endDate;
}

/** Query string for the API. Product and location are sent verbatim. */
export function toQueryString(filters: MoistureFilters): string {
  const params = new URLSearchParams();
  if (filters.product) params.set("product", filters.product);
  if (filters.location) params.set("location", filters.location);
  if (filters.search.trim()) params.set("search", filters.search.trim());
  if (filters.startDate) params.set("startDate", filters.startDate);
  if (filters.endDate) params.set("endDate", filters.endDate);
  return params.toString();
}

const BASE = "/api/v1/quality/moisture";

function withQuery(path: string, query: string) {
  return query ? `${BASE}${path}?${query}` : `${BASE}${path}`;
}

export const moistureKeys = {
  all: ["quality", "moisture"] as const,
  filters: () => [...moistureKeys.all, "filters"] as const,
  lots: (query: string) => [...moistureKeys.all, "lots", query] as const,
  trends: (query: string) => [...moistureKeys.all, "trends", query] as const,
};

export function fetchMoistureFilters(signal?: AbortSignal) {
  return apiGet<MoistureFiltersResponse>(`${BASE}/filters`, { signal });
}

export function fetchMoistureLots(query: string, signal?: AbortSignal) {
  return apiGet<MoistureLotsResponse>(withQuery("/lots", query), { signal });
}

export function fetchMoistureTrends(query: string, signal?: AbortSignal) {
  return apiGet<MoistureTrendsResponse>(withQuery("/trends", query), { signal });
}
