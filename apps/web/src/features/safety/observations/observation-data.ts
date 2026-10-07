import type { BarSeries } from "@/components/common/bar-chart";
import { PALETTE, type TrendSeries } from "@/components/common/trend-chart";

import { MONTH_LABELS } from "../incidents/grid";
import type {
  CategoryCount,
  Kind,
  Observation,
  ObservationCounts,
  ObservationDashboardResponse,
  ObservationInput,
  Outcome,
} from "./api";

/** Same limits as the API and the database. */
export const MAX_AREA_LOCATION_LENGTH = 200;
export const MAX_NOTE_LENGTH = 2000;
export const EARLIEST_OBSERVED_ON = "2000-01-01";

export const OUTCOME_LABELS: Record<Outcome, string> = { safe: "Safe", unsafe: "Unsafe" };
export const KIND_LABELS: Record<Kind, string> = { act: "Act", condition: "Condition" };

/** Form state. Classification starts unchosen so nothing is recorded by default. */
export type ObservationDraft = {
  observedOn: string;
  outcome: Outcome | null;
  kind: Kind | null;
  categoryId: number | null;
  areaLocation: string;
  description: string;
  correctiveAction: string;
};

export type DraftErrors = Partial<Record<keyof ObservationDraft, string>>;

/** The device's local calendar date as YYYY-MM-DD. */
export function localIsoDate(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function emptyDraft(observedOn: string): ObservationDraft {
  return {
    observedOn,
    outcome: null,
    kind: null,
    categoryId: null,
    areaLocation: "",
    description: "",
    correctiveAction: "",
  };
}

export function draftFromObservation(observation: Observation): ObservationDraft {
  return {
    observedOn: observation.observedOn,
    outcome: observation.outcome,
    kind: observation.kind,
    categoryId: observation.categoryId,
    areaLocation: observation.areaLocation ?? "",
    description: observation.description ?? "",
    correctiveAction: observation.correctiveAction ?? "",
  };
}

function isIsoDate(text: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return false;
  const [year, month, day] = text.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day;
}

/** Field errors; an empty object means the draft can be saved. Mirrors the API's rules. */
export function validateDraft(draft: ObservationDraft, today: string): DraftErrors {
  const errors: DraftErrors = {};
  if (!draft.observedOn) errors.observedOn = "Choose the date of the observation.";
  else if (!isIsoDate(draft.observedOn)) errors.observedOn = "Enter a valid date.";
  else if (draft.observedOn > today) errors.observedOn = "The date cannot be in the future.";
  else if (draft.observedOn < EARLIEST_OBSERVED_ON) errors.observedOn = "The date is too early.";
  if (!draft.outcome) errors.outcome = "Choose Safe or Unsafe.";
  if (!draft.kind) errors.kind = "Choose Act or Condition.";
  if (draft.categoryId === null) errors.categoryId = "Choose a category.";
  if (draft.areaLocation.trim().length > MAX_AREA_LOCATION_LENGTH) {
    errors.areaLocation = `Use at most ${MAX_AREA_LOCATION_LENGTH} characters.`;
  }
  if (draft.description.trim().length > MAX_NOTE_LENGTH) {
    errors.description = `Use at most ${MAX_NOTE_LENGTH} characters.`;
  }
  if (draft.correctiveAction.trim().length > MAX_NOTE_LENGTH) {
    errors.correctiveAction = `Use at most ${MAX_NOTE_LENGTH} characters.`;
  }
  return errors;
}

function optionalText(text: string): string | null {
  const trimmed = text.trim();
  return trimmed === "" ? null : trimmed;
}

/** Request body for a valid draft. Blank optional text is sent as null. */
export function toInput(draft: ObservationDraft): ObservationInput {
  if (!draft.outcome || !draft.kind || draft.categoryId === null) {
    throw new Error("toInput needs a validated draft");
  }
  return {
    observedOn: draft.observedOn,
    outcome: draft.outcome,
    kind: draft.kind,
    categoryId: draft.categoryId,
    areaLocation: optionalText(draft.areaLocation),
    description: optionalText(draft.description),
    correctiveAction: optionalText(draft.correctiveAction),
  };
}

/** After a save the next observation is usually from the same walk: keep the date only. */
export function nextDraft(saved: ObservationDraft): ObservationDraft {
  return emptyDraft(saved.observedOn);
}

/** "Tue, Oct 6, 2026" for a YYYY-MM-DD date, without shifting it through a time zone. */
export function formatObservedOn(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function monthName(month: number): string {
  return new Date(2000, month - 1, 1).toLocaleDateString("en-US", { month: "long" });
}

// Summary -------------------------------------------------------------------------

export type SummaryTile = { key: keyof ObservationCounts; label: string; value: number };

/** The month summary, in display order. Each figure is a count of the same records. */
export function summaryTiles(counts: ObservationCounts): SummaryTile[] {
  const tiles: [keyof ObservationCounts, string][] = [
    ["total", "Total"],
    ["safe", "Safe"],
    ["unsafe", "Unsafe"],
    ["safeAct", "Safe Act"],
    ["safeCondition", "Safe Condition"],
    ["unsafeAct", "Unsafe Act"],
    ["unsafeCondition", "Unsafe Condition"],
  ];
  return tiles.map(([key, label]) => ({ key, label, value: counts[key] }));
}

/** Categories that have observations, most first; ties keep display order. */
export function categoriesWithObservations(categories: CategoryCount[]): CategoryCount[] {
  return categories
    .map((category, index) => ({ category, index }))
    .filter(({ category }) => category.total > 0)
    .sort((a, b) => b.category.total - a.category.total || a.index - b.index)
    .map(({ category }) => category);
}

// Dashboard -----------------------------------------------------------------------

// The first two shared palette colors, so line charts (colored by position) match the bar charts.
export const SAFE_COLOR = PALETTE[0];
export const UNSAFE_COLOR = PALETTE[1];

export function formatShare(share: number | null): string | null {
  return share === null ? null : `${Math.round(share * 100)}%`;
}

/** Monthly Safe and Unsafe counts. Months that have not started are null (no bar), not 0. */
export function monthlySafeVsUnsafe(dashboard: ObservationDashboardResponse | undefined): BarSeries[] {
  const months = dashboard?.months ?? [];
  const values = (pick: (counts: ObservationCounts) => number) =>
    MONTH_LABELS.map((_, index) => {
      const counts = months[index]?.counts;
      return counts ? pick(counts) : null;
    });
  return [
    { name: "Safe", color: SAFE_COLOR, values: values((c) => c.safe) },
    { name: "Unsafe", color: UNSAFE_COLOR, values: values((c) => c.unsafe) },
  ];
}

/** Year-to-date Act / Condition split of Safe and Unsafe observations. */
export function actConditionBreakdown(dashboard: ObservationDashboardResponse | undefined): {
  categories: string[];
  series: BarSeries[];
} {
  const counts = dashboard?.counts;
  return {
    categories: ["Act", "Condition"],
    series: [
      {
        name: "Safe",
        color: SAFE_COLOR,
        values: counts ? [counts.safeAct, counts.safeCondition] : [null, null],
      },
      {
        name: "Unsafe",
        color: UNSAFE_COLOR,
        values: counts ? [counts.unsafeAct, counts.unsafeCondition] : [null, null],
      },
    ],
  };
}

/** Year-to-date Safe and Unsafe counts per category, in category display order. */
export function categoryYearToDate(dashboard: ObservationDashboardResponse | undefined): {
  categories: string[];
  series: BarSeries[];
} {
  const categories = dashboard?.categories ?? [];
  return {
    categories: categories.map((c) => c.name),
    series: [
      { name: "Safe", color: SAFE_COLOR, values: categories.map((c) => c.safe) },
      { name: "Unsafe", color: UNSAFE_COLOR, values: categories.map((c) => c.unsafe) },
    ],
  };
}

/**
 * Cumulative Safe and Unsafe counts at the end of each started month. The
 * current month's point is dated today, since its count is only through today.
 */
export function runningTotals(
  dashboard: ObservationDashboardResponse | undefined,
  today: string,
): TrendSeries[] {
  if (!dashboard) return [];
  let safe = 0;
  let unsafe = 0;
  const safePoints: [string, number][] = [];
  const unsafePoints: [string, number][] = [];
  for (const { month, counts } of dashboard.months) {
    if (!counts) continue;
    safe += counts.safe;
    unsafe += counts.unsafe;
    const monthEnd = localIsoDate(new Date(dashboard.year, month, 0));
    const at = monthEnd > today ? today : monthEnd;
    safePoints.push([at, safe]);
    unsafePoints.push([at, unsafe]);
  }
  return [
    { name: "Safe (running total)", points: safePoints },
    { name: "Unsafe (running total)", points: unsafePoints },
  ];
}

/** Monthly count for one category; months that have not started are null. */
export function categoryOverTime(
  dashboard: ObservationDashboardResponse | undefined,
  categoryCode: string,
): BarSeries[] {
  const category = dashboard?.categories.find((c) => c.code === categoryCode);
  return [
    {
      name: category?.name ?? "Observations",
      color: SAFE_COLOR,
      values: category?.monthly ?? MONTH_LABELS.map(() => null),
    },
  ];
}
