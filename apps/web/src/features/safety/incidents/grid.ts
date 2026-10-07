import type { CellChange, MetricSectionBlock, MonthlyMetricsResponse } from "./api";

export const MONTH_LABELS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/** Matches the API's sanity ceiling for a monthly count. */
export const MAX_MONTHLY_COUNT = 100_000;

/** Edited cell text keyed by cellKey(). Cells without an entry show the stored value. */
export type Draft = Record<string, string>;

export function cellKey(categoryId: number, month: number): string {
  return `${categoryId}:${month}`;
}

export type ParsedCount = { ok: true; value: number | null } | { ok: false };

/** "" is unreported (null); otherwise a whole, non-negative count. */
export function parseCount(text: string): ParsedCount {
  const trimmed = text.trim();
  if (trimmed === "") return { ok: true, value: null };
  if (!/^\d+$/.test(trimmed)) return { ok: false };
  const value = Number(trimmed);
  return value <= MAX_MONTHLY_COUNT ? { ok: true, value } : { ok: false };
}

export function formatCount(value: number | null): string {
  return value === null ? "" : String(value);
}

/** Sum of reported values; null when nothing is reported. Same rule as the API. */
export function total(values: (number | null)[]): number | null {
  let sum: number | null = null;
  for (const value of values) {
    if (value !== null) sum = (sum ?? 0) + value;
  }
  return sum;
}

export type CellState = { text: string; value: number | null; dirty: boolean; invalid: boolean };

/** The cell as shown: draft text when edited, otherwise the stored value. */
export function cellState(stored: number | null, draftText: string | undefined): CellState {
  if (draftText === undefined) {
    return { text: formatCount(stored), value: stored, dirty: false, invalid: false };
  }
  const parsed = parseCount(draftText);
  if (!parsed.ok) return { text: draftText, value: stored, dirty: true, invalid: true };
  return { text: draftText, value: parsed.value, dirty: parsed.value !== stored, invalid: false };
}

/** Section rows with draft edits applied, for live totals while editing. */
export function draftSectionValues(section: MetricSectionBlock, draft: Draft) {
  return section.categories.map((category) =>
    category.values.map((stored, index) => cellState(stored, draft[cellKey(category.id, index + 1)])),
  );
}

export type DraftSummary = {
  changes: CellChange[];
  invalidCount: number;
};

/** Changes to send, based on the stored values the draft was edited against. */
export function summarizeDraft(metrics: MonthlyMetricsResponse, draft: Draft): DraftSummary {
  const changes: CellChange[] = [];
  let invalidCount = 0;
  for (const section of metrics.sections) {
    for (const category of section.categories) {
      category.values.forEach((stored, index) => {
        const month = index + 1;
        const text = draft[cellKey(category.id, month)];
        if (text === undefined) return;
        const parsed = parseCount(text);
        if (!parsed.ok) {
          invalidCount += 1;
        } else if (parsed.value !== stored) {
          changes.push({ categoryId: category.id, month, value: parsed.value, previousValue: stored });
        }
      });
    }
  }
  return { changes, invalidCount };
}

/** Incident & Near Miss reporting starts with this year; earlier years are not offered. */
export const FIRST_REPORTING_YEAR = 2026;
const RECENT_YEARS = 5;

export function defaultReportingYear(currentYear: number): number {
  return Math.max(currentYear, FIRST_REPORTING_YEAR);
}

/** Recent years plus any year that already has data, newest first, never before the first reporting year. */
export function reportingYearOptions(
  currentYear: number,
  yearsWithData: number[],
  firstYear = FIRST_REPORTING_YEAR,
): number[] {
  const years = new Set(yearsWithData);
  const latest = Math.max(currentYear, firstYear);
  for (let year = latest; year > latest - RECENT_YEARS; year -= 1) years.add(year);
  return [...years].filter((year) => year >= firstYear).sort((a, b) => b - a);
}
