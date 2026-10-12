/**
 * Reporting periods shared by every dashboard, register and export.
 *
 * The API's `app/reports/period.py` resolves the same modes with the same rules
 * and labels, so a screen and its PDF / Excel export cover the same dates.
 * Dates are ISO strings (YYYY-MM-DD) on the Baytown site calendar; `today`
 * comes from `siteToday()`. A period's end date is inclusive.
 */

export type PeriodMode =
  | "all"
  | "this-month"
  | "last-month"
  | "ytd"
  | "last-3-months"
  | "last-6-months"
  | "this-year"
  | "year"
  | "month"
  | "custom";

/** What the user chose; stored in the URL. */
export type PeriodValue = {
  mode: PeriodMode;
  year?: number;
  month?: number;
  from?: string;
  to?: string;
};

/** A resolved period. `startDate` / `endDate` are null only for "all". */
export type PeriodSelection = {
  mode: PeriodMode;
  startDate: string | null;
  endDate: string | null;
  year: number | null;
  month: number | null;
  /** "Year to Date", "August 2026", "2026", "Custom Range". */
  label: string;
  /** The dates covered: "Jan 1 – Oct 9, 2026"; "" for all dates. */
  rangeLabel: string;
  /** "Year to Date · Jan 1 – Oct 9, 2026". */
  fullLabel: string;
};

export const PRESET_LABELS: Record<Exclude<PeriodMode, "year" | "month" | "custom">, string> = {
  all: "All dates",
  "this-month": "This Month",
  "last-month": "Last Month",
  ytd: "Year to Date",
  "last-3-months": "Last 3 Months",
  "last-6-months": "Last 6 Months",
  "this-year": "This Year",
};

export type PresetMode = keyof typeof PRESET_LABELS;

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
];
export const MONTH_ABBR = MONTH_NAMES.map((name) => name.slice(0, 3));

export const MIN_YEAR = 2000;
export const MAX_YEAR = 2100;

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Which choices a page offers. Not every report suits every period. */
export type PeriodConfig = {
  presets: PresetMode[];
  /** Browse by year, or by year and month. */
  browse: "year" | "year-month" | false;
  /** A free from / to date range. */
  custom: boolean;
  /** Years offered when browsing, newest first. */
  years: number[];
};

export function isIsoDate(value: string | null | undefined): value is string {
  if (!value) return false;
  const match = ISO_DATE.exec(value);
  if (!match) return false;
  const [, y, m, d] = match.map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
}

function pad(value: number) {
  return String(value).padStart(2, "0");
}

function iso(year: number, month: number, day: number) {
  return `${year}-${pad(month)}-${pad(day)}`;
}

export function lastDayOfMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** (year, month) shifted by `delta` months. */
export function addMonths(year: number, month: number, delta: number): [number, number] {
  const index = year * 12 + (month - 1) + delta;
  return [Math.floor(index / 12), (index % 12) + 1];
}

function parts(date: string): [number, number, number] {
  return [Number(date.slice(0, 4)), Number(date.slice(5, 7)), Number(date.slice(8, 10))];
}

function short(date: string) {
  const [, m, d] = parts(date);
  return `${MONTH_ABBR[m - 1]} ${d}`;
}

/** "Jan 1 – Oct 9, 2026"; "Nov 1, 2025 – Jan 31, 2026" across years. */
export function rangeLabel(start: string, end: string): string {
  const [sy] = parts(start);
  const [ey] = parts(end);
  if (start === end) return `${short(start)}, ${sy}`;
  if (sy === ey) return `${short(start)} – ${short(end)}, ${ey}`;
  return `${short(start)}, ${sy} – ${short(end)}, ${ey}`;
}

function monthName(year: number, month: number) {
  return `${MONTH_NAMES[month - 1]} ${year}`;
}

function selection(mode: PeriodMode, start: string, end: string, label: string): PeriodSelection {
  const [sy, sm] = parts(start);
  const [ey, em, ed] = parts(end);
  const singleMonth = mode === "this-month" || mode === "last-month" || mode === "month";
  const wholeYear = start === iso(sy, 1, 1) && sy === ey && em === 12 && ed === 31;
  let range: string;
  if (mode === "month") range = rangeLabel(start, end);
  else if (mode === "this-month" || mode === "last-month") range = monthName(sy, sm);
  else if (wholeYear && (mode === "this-year" || mode === "year")) range = String(sy);
  else range = rangeLabel(start, end);
  return {
    mode,
    startDate: start,
    endDate: end,
    year: sy === ey ? sy : null,
    month: singleMonth ? sm : null,
    label,
    rangeLabel: range,
    fullLabel: range === label ? label : `${label} · ${range}`,
  };
}

const ALL: PeriodSelection = {
  mode: "all",
  startDate: null,
  endDate: null,
  year: null,
  month: null,
  label: PRESET_LABELS.all,
  rangeLabel: "",
  fullLabel: PRESET_LABELS.all,
};

/**
 * The dates of `value` on the site date `today`. Returns null for an
 * incomplete or invalid choice (e.g. a custom range ending before it starts).
 */
export function resolvePeriod(value: PeriodValue, today: string): PeriodSelection | null {
  const [ty, tm] = parts(today);
  switch (value.mode) {
    case "all":
      return ALL;
    case "this-month":
      return selection(value.mode, iso(ty, tm, 1), iso(ty, tm, lastDayOfMonth(ty, tm)), PRESET_LABELS[value.mode]);
    case "last-month": {
      const [y, m] = addMonths(ty, tm, -1);
      return selection(value.mode, iso(y, m, 1), iso(y, m, lastDayOfMonth(y, m)), PRESET_LABELS[value.mode]);
    }
    case "ytd":
      return selection(value.mode, iso(ty, 1, 1), today, PRESET_LABELS.ytd);
    case "last-3-months":
    case "last-6-months": {
      const count = value.mode === "last-3-months" ? 3 : 6;
      const [y, m] = addMonths(ty, tm, -(count - 1));
      return selection(value.mode, iso(y, m, 1), iso(ty, tm, lastDayOfMonth(ty, tm)), PRESET_LABELS[value.mode]);
    }
    case "this-year":
      return selection(value.mode, iso(ty, 1, 1), iso(ty, 12, 31), PRESET_LABELS["this-year"]);
    case "year":
      if (!validYear(value.year)) return null;
      return selection("year", iso(value.year, 1, 1), iso(value.year, 12, 31), String(value.year));
    case "month":
      if (!validYear(value.year) || !validMonth(value.month)) return null;
      return selection(
        "month",
        iso(value.year, value.month, 1),
        iso(value.year, value.month, lastDayOfMonth(value.year, value.month)),
        monthName(value.year, value.month),
      );
    case "custom":
      if (!isIsoDate(value.from) || !isIsoDate(value.to) || value.to < value.from) return null;
      if (!validYear(parts(value.from)[0]) || !validYear(parts(value.to)[0])) return null;
      return selection("custom", value.from, value.to, "Custom Range");
  }
}

function validYear(year: number | undefined): year is number {
  return year !== undefined && Number.isInteger(year) && year >= MIN_YEAR && year <= MAX_YEAR;
}

function validMonth(month: number | undefined): month is number {
  return month !== undefined && Number.isInteger(month) && month >= 1 && month <= 12;
}

/** `?period=ytd`, `?year=2026&month=8`, `?year=2026` or `?from=…&to=…`. */
export function periodFromParams(params: URLSearchParams, fallback: PeriodValue): PeriodValue {
  const preset = params.get("period");
  if (preset && preset in PRESET_LABELS) return { mode: preset as PresetMode };
  const year = Number(params.get("year"));
  const month = Number(params.get("month"));
  if (params.has("year") && validYear(year)) {
    if (params.has("month") && validMonth(month)) return { mode: "month", year, month };
    if (!params.has("month")) return { mode: "year", year };
  }
  const from = params.get("from");
  const to = params.get("to");
  if (isIsoDate(from) && isIsoDate(to) && from <= to) return { mode: "custom", from, to };
  return fallback;
}

const PERIOD_KEYS = ["period", "year", "month", "from", "to"];

/** Writes `value` into `params`; the default period leaves the URL clean. */
export function periodToParams(params: URLSearchParams, value: PeriodValue, fallback: PeriodValue): void {
  for (const key of PERIOD_KEYS) params.delete(key);
  if (samePeriod(value, fallback)) return;
  if (value.mode === "year") params.set("year", String(value.year));
  else if (value.mode === "month") {
    params.set("year", String(value.year));
    params.set("month", String(value.month));
  } else if (value.mode === "custom") {
    params.set("from", value.from ?? "");
    params.set("to", value.to ?? "");
  } else params.set("period", value.mode);
}

export function samePeriod(a: PeriodValue, b: PeriodValue): boolean {
  return a.mode === b.mode && a.year === b.year && a.month === b.month && a.from === b.from && a.to === b.to;
}

/** The period as the export API takes it (`PeriodIn`). */
export function periodRequest(value: PeriodValue): Record<string, string | number> {
  const body: Record<string, string | number> = { mode: value.mode };
  if (value.mode === "year" || value.mode === "month") body.year = value.year!;
  if (value.mode === "month") body.month = value.month!;
  if (value.mode === "custom") {
    body.from = value.from!;
    body.to = value.to!;
  }
  return body;
}

/** Years from `first` through the current year, newest first. */
export function yearsSince(first: number, today: string): number[] {
  const current = parts(today)[0];
  const years: number[] = [];
  for (let year = current; year >= Math.max(first, MIN_YEAR); year -= 1) years.push(year);
  return years;
}

/** `?period=` value for a preset, e.g. the "This Month" quick view. */
export function presetValue(mode: PresetMode): PeriodValue {
  return { mode };
}
