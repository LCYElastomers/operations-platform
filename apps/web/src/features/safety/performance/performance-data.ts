import type { BarSeries } from "@/components/common/bar-chart";
import type { TrendSeries } from "@/components/common/trend-chart";

import { MONTH_LABELS } from "../incidents/grid";
import { monthName } from "../observations/observation-data";
import type {
  BlockReason,
  Measure,
  MonthStatus,
  PerformanceDashboardResponse,
  PerformanceMonth,
  RateResult,
  SaveMonthRequest,
} from "./api";

export const MEASURES: { measure: Measure; label: string }[] = [
  { measure: "trir", label: "TRIR" },
  { measure: "first_aid", label: "First Aid Rate" },
  { measure: "lopc", label: "Loss of Primary Containment (LOPC) Rate" },
  { measure: "property_equipment_damage", label: "Property & Equipment Damage Rate" },
];

export const SHORT_LABELS: Record<Measure, string> = {
  trir: "TRIR",
  first_aid: "First Aid",
  lopc: "LOPC",
  property_equipment_damage: "Property & Equipment Damage",
};

export const ROLLING_LABEL = "12-Month Rolling Average (12MRA)";

export const STATUS_LABELS: Record<MonthStatus, string> = {
  not_reported: "Not Reported",
  reported: "Reported",
  closed: "Closed",
};

const REASON_LABELS: Record<BlockReason, string> = {
  not_reported: "not reported",
  open: "not closed",
  zero_hours: "zero hours",
  count_not_confirmed: "count not confirmed",
};

/** Matches the API: numeric(10, 2) and a per-month ceiling far above one site's hours. */
export const MAX_MONTHLY_HOURS = 1_000_000;
const HOURS_PATTERN = /^\d+(\.\d{1,2})?$/;

export type ParsedHours = { ok: true; value: number | null } | { ok: false };

/** Blank is "not given" (null), never zero. Commas are accepted as thousands separators. */
export function parseHours(text: string): ParsedHours {
  const trimmed = text.trim().replaceAll(",", "");
  if (trimmed === "") return { ok: true, value: null };
  if (!HOURS_PATTERN.test(trimmed)) return { ok: false };
  const value = Number(trimmed);
  return value <= MAX_MONTHLY_HOURS ? { ok: true, value } : { ok: false };
}

export function formatHours(value: number | null): string {
  return value === null ? "—" : value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function inputText(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

export type HoursDraft = {
  total: string;
  hourly: string;
  salary: string;
  /** Whether the hourly / salary inputs are shown. */
  breakdown: boolean;
  closed: boolean;
};

export function draftFromMonth(month: PerformanceMonth): HoursDraft {
  const hours = month.hours;
  return {
    total: inputText(hours?.totalHours),
    hourly: inputText(hours?.hourlyHours),
    salary: inputText(hours?.salaryHours),
    breakdown: hours !== null && (hours.hourlyHours !== null || hours.salaryHours !== null),
    closed: hours?.monthClosed ?? false,
  };
}

export type DraftCheck = { errors: string[]; request: SaveMonthRequest | null; dirty: boolean };

const cents = (value: number) => Math.round(value * 100);

/** Validates a month's draft into a save request, mirroring the API's rules. */
export function checkDraft(draft: HoursDraft, month: PerformanceMonth): DraftCheck {
  const errors: string[] = [];
  const total = parseHours(draft.total);
  const hourly = draft.breakdown ? parseHours(draft.hourly) : ({ ok: true, value: null } as const);
  const salary = draft.breakdown ? parseHours(draft.salary) : ({ ok: true, value: null } as const);
  if (!total.ok || !hourly.ok || !salary.ok) {
    errors.push("Hours must be a number of 0 or more with up to 2 decimal places.");
  } else if (total.value === null) {
    errors.push("Enter total hours, or clear the month to mark it Not Reported.");
  } else if (
    hourly.value !== null &&
    salary.value !== null &&
    cents(hourly.value) + cents(salary.value) !== cents(total.value)
  ) {
    errors.push("Hourly and salary hours must add up to total hours.");
  }
  if (draft.closed && !month.canClose) errors.push("A month can be closed only after it has ended.");

  const request =
    errors.length === 0 && total.ok && hourly.ok && salary.ok && total.value !== null
      ? {
          totalHours: total.value,
          hourlyHours: hourly.value,
          salaryHours: salary.value,
          monthClosed: draft.closed,
          expectedUpdatedAt: month.hours?.updatedAt ?? null,
        }
      : null;
  const stored = month.hours;
  const dirty =
    stored === null
      ? draft.total.trim() !== "" || draft.closed
      : request === null ||
        request.totalHours !== stored.totalHours ||
        request.hourlyHours !== stored.hourlyHours ||
        request.salaryHours !== stored.salaryHours ||
        request.monthClosed !== stored.monthClosed;
  return { errors, request, dirty };
}

export function throughLabel(year: number, month: number | null): string {
  return month === null ? `No closed months in ${year}` : `Through ${monthName(month)} ${year}`;
}

function periodLabel(period: { year: number; month: number }): string {
  return `${MONTH_LABELS[period.month - 1]} ${period.year}`;
}

export function windowLabel(result: RateResult): string {
  return `${periodLabel(result.start)} – ${periodLabel(result.end)}`;
}

export function formatRate(rate: number | null): string | null {
  return rate === null ? null : rate.toFixed(2);
}

const MAX_LISTED_MONTHS = 3;

/** Why a rate could not be calculated, naming the months that block it. */
export function unavailableReason(result: RateResult): string {
  const listed = result.ineligibleMonths
    .slice(0, MAX_LISTED_MONTHS)
    .map((m) => `${periodLabel(m)} ${REASON_LABELS[m.reason]}`);
  const more = result.ineligibleMonths.length - MAX_LISTED_MONTHS;
  return `Unavailable: ${listed.join("; ")}${more > 0 ? `; ${more} more` : ""}`;
}

/** e.g. "Jan 2026 – Aug 2026 · 1 event ÷ 145,194 h". */
export function rateCaption(result: RateResult): string {
  if (!result.available || result.events === null || result.hours === null) {
    return unavailableReason(result);
  }
  const events = `${result.events} ${result.events === 1 ? "event" : "events"}`;
  const split =
    result.propertyDamage !== null && result.equipmentDamageFailure !== null
      ? ` (property ${result.propertyDamage}, equipment ${result.equipmentDamageFailure})`
      : "";
  return `${windowLabel(result)} · ${events}${split} ÷ ${formatHours(result.hours)} h`;
}

function monthEnd(year: number, month: number): string {
  const day = new Date(year, month, 0).getDate();
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** Rate trends, one point per month end; months without a rate are left out. */
export function rateTrendSeries(
  dashboard: PerformanceDashboardResponse | undefined,
  lines: { measure: Measure; window: "ytd" | "rolling"; name: string }[],
): TrendSeries[] {
  if (!dashboard) return [];
  return lines.map(({ measure, window, name }) => {
    const trend = dashboard.trends.find((t) => t.measure === measure);
    const values = trend?.[window] ?? [];
    return {
      name,
      points: values.flatMap((value, index) =>
        value === null ? [] : [[monthEnd(dashboard.year, index + 1), value] as [string, number]],
      ),
    };
  });
}

export function hoursSeries(dashboard: PerformanceDashboardResponse | undefined): BarSeries[] {
  if (!dashboard) return [];
  return [{ name: "Worked hours", values: dashboard.months.map((m) => m.hours?.totalHours ?? null) }];
}

/** Annual TRIR bars. A year still in progress is labelled YTD with its months. */
export function annualTrirChart(dashboard: PerformanceDashboardResponse | undefined): {
  categories: string[];
  series: BarSeries[];
} {
  const years = dashboard?.annualTrir ?? [];
  return {
    categories: years.map((a) =>
      a.partial && a.throughMonth !== null
        ? `${a.year} YTD (Jan–${MONTH_LABELS[a.throughMonth - 1]})`
        : String(a.year),
    ),
    series: years.length
      ? [{ name: "TRIR", values: years.map((a) => (a.rate === null ? null : Number(a.rate.toFixed(2)))) }]
      : [],
  };
}
