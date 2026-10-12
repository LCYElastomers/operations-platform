/**
 * Quality Cost page filters as kept in the URL, and what they mean for the
 * summary, records and export APIs. Plain functions, so a server page can read
 * its initial filters from the request.
 */
import { MIN_YEAR, periodFromParams, periodToParams, resolvePeriod, yearsSince, type PeriodConfig, type PeriodValue } from "@/lib/period";
import type { ReportContext } from "@/lib/reports";

import {
  NO_DIMENSIONS,
  type CoqClass,
  type CostDimensions,
  type CostRecordQuery,
  type CostSummary,
  type CostSummaryQuery,
  type OperationalStatus,
} from "./api";

type SearchRecord = Record<string, string | string[] | undefined>;

/**
 * The COPQ / COQ Matrix filters. `period` is null for the default: the latest
 * year with records, January through its latest month with records.
 */
export type CostDashboardQuery = CostDimensions & { period: PeriodValue | null };

export const EMPTY_COST_DASHBOARD: CostDashboardQuery = { period: null, ...NO_DIMENSIONS };

/** The register's filters: an item-date period instead of raw from / to dates. */
export type CostRegisterQuery = CostDimensions & {
  period: PeriodValue;
  status: OperationalStatus | null;
  search: string;
};

const ALL_DATES: PeriodValue = { mode: "all" };

export const EMPTY_COST_REGISTER: CostRegisterQuery = { ...NO_DIMENSIONS, period: ALL_DATES, status: null, search: "" };

/** The summary covers whole months of one year, so only these periods apply. */
const SUMMARY_MODES = new Set<PeriodValue["mode"]>(["this-month", "last-month", "ytd", "this-year", "year", "month"]);
const COQ_CLASSES: CoqClass[] = ["prevention", "appraisal", "internal_failure", "external_failure"];
const FINANCIAL_STATUSES: NonNullable<CostDimensions["financialStatus"]>[] = ["potential", "validating", "confirmed", "closed"];
const STATUSES: OperationalStatus[] = ["open", "under_review", "action_required", "monitoring", "closed"];

export function costPeriodConfig(years: number[]): PeriodConfig {
  return { presets: ["this-month", "last-month", "ytd", "this-year"], browse: "year-month", custom: false, years };
}

export function registerPeriodConfig(today: string): PeriodConfig {
  return {
    presets: ["all", "this-month", "last-month", "ytd", "last-3-months", "last-6-months", "this-year"],
    browse: "year-month",
    custom: true,
    years: yearsSince(MIN_YEAR, today),
  };
}

/** The summary API's year / from / through for a period on the site date `today`. */
export function summaryQueryOf(query: CostDashboardQuery, today: string, poorOnly: boolean): CostSummaryQuery {
  const { period, ...dimensions } = query;
  const base = { ...dimensions, poorOnly };
  const selection = period ? resolvePeriod(period, today) : null;
  if (!period || !selection?.startDate || !selection.endDate) return { ...base, year: null, from: null, through: null };
  const year = Number(selection.startDate.slice(0, 4));
  if (period.mode === "year" || period.mode === "this-year") return { ...base, year, from: null, through: null };
  return { ...base, year, from: Number(selection.startDate.slice(5, 7)), through: Number(selection.endDate.slice(5, 7)) };
}

function dimensionParams(params: URLSearchParams, query: CostDimensions) {
  if (query.areaId !== null) params.set("areaId", String(query.areaId));
  if (query.coqClass) params.set("coqClass", query.coqClass);
  if (query.category) params.set("category", query.category);
  if (query.product) params.set("product", query.product);
  if (query.owner) params.set("owner", query.owner);
  if (query.financialStatus) params.set("financialStatus", query.financialStatus);
}

function dimensionsFromParams(params: URLSearchParams): CostDimensions {
  const text = (key: string) => (params.get(key) ?? "").slice(0, 200);
  const areaId = Number(params.get("areaId"));
  return {
    areaId: Number.isInteger(areaId) && areaId >= 1 ? areaId : null,
    coqClass: COQ_CLASSES.find((code) => code === params.get("coqClass")) ?? null,
    category: /^[a-z_]{1,50}\.[a-z_]{1,50}$/.test(text("category")) ? text("category") : "",
    product: text("product"),
    owner: text("owner"),
    financialStatus: FINANCIAL_STATUSES.find((code) => code === params.get("financialStatus")) ?? null,
  };
}

function toSearch(params: SearchRecord) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    const one = Array.isArray(value) ? value[0] : value;
    if (one !== undefined) search.set(key, one);
  }
  return search;
}

/** `?period=ytd&areaId=3&coqClass=internal_failure`; the default leaves the URL clean. */
export function costQueryParams(query: CostDashboardQuery): URLSearchParams {
  const params = new URLSearchParams();
  periodToParams(params, query.period ?? ALL_DATES, ALL_DATES);
  dimensionParams(params, query);
  return params;
}

/** A period the summary cannot show (e.g. a custom range) falls back to the default. */
export function costQueryFromParams(params: URLSearchParams): CostDashboardQuery {
  const period = periodFromParams(params, ALL_DATES);
  return { period: SUMMARY_MODES.has(period.mode) ? period : null, ...dimensionsFromParams(params) };
}

export function costDashboardFromParams(params: SearchRecord): CostDashboardQuery {
  return costQueryFromParams(toSearch(params));
}

export function costRegisterParams(query: CostRegisterQuery): URLSearchParams {
  const params = new URLSearchParams();
  periodToParams(params, query.period, ALL_DATES);
  dimensionParams(params, query);
  if (query.status) params.set("status", query.status);
  if (query.search.trim()) params.set("search", query.search.trim());
  return params;
}

export function costRegisterFromParams(params: URLSearchParams): CostRegisterQuery {
  return {
    ...dimensionsFromParams(params),
    period: periodFromParams(params, ALL_DATES),
    status: STATUSES.find((code) => code === params.get("status")) ?? null,
    search: (params.get("search") ?? "").slice(0, 200),
  };
}

export function costRegisterFromRecord(params: SearchRecord): CostRegisterQuery {
  return costRegisterFromParams(toSearch(params));
}

/** The records API query for the register's period on the site date `today`. */
export function recordQueryOf(query: CostRegisterQuery, today: string): CostRecordQuery {
  const { period, ...rest } = query;
  const selection = resolvePeriod(period, today);
  return { ...rest, from: selection?.startDate ?? "", to: selection?.endDate ?? "", open: false, classes: [] };
}

function dimensionFilters(query: CostDimensions) {
  return {
    areaId: query.areaId,
    coqClass: query.coqClass,
    category: query.category || null,
    product: query.product || null,
    owner: query.owner || null,
    financialStatus: query.financialStatus,
  };
}

/** What the export API takes for a dashboard's period and dimensions. */
export function costReportContext(query: CostDashboardQuery, data: CostSummary | undefined): ReportContext {
  return {
    period: query.period ?? { mode: "year", year: data?.year ?? undefined },
    filters: dimensionFilters(query),
  };
}

export function costRegisterReportContext(query: CostRegisterQuery): ReportContext {
  return {
    period: query.period,
    filters: { ...dimensionFilters(query), status: query.status, search: query.search.trim() || null },
  };
}
