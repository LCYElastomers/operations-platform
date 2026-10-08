"use client";

import { RotateCcw, SlidersHorizontal } from "lucide-react";
import { useCallback, useId, useMemo, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * How a table or chart is shown. Display only: hiding a row or month never
 * changes a stored value or a total. Saved per browser in localStorage under
 * `display:<surface>`; never sent to the API and never stored as safety data.
 */
export type DisplayPreferences = {
  /** Hide rows whose every cell is null (not reported). */
  hideEmptyRows: boolean;
  /** When false, rows holding only reported zeros (and blanks) are hidden too; zeros still show as 0. */
  showReportedZeros: boolean;
  /** Hide months (columns) with nothing reported in any row. */
  hideEmptyMonths: boolean;
  /** Series ids the user turned off. */
  hiddenSeries: string[];
};

export const DEFAULT_DISPLAY: DisplayPreferences = {
  hideEmptyRows: true,
  showReportedZeros: true,
  hideEmptyMonths: false,
  hiddenSeries: [],
};

const STORAGE_PREFIX = "display:";
const CHANGE_EVENT = "display-preferences-change";

function read(surface: string): string | null {
  try {
    return window.localStorage.getItem(STORAGE_PREFIX + surface);
  } catch {
    return null;
  }
}

export function parsePreferences(text: string | null): DisplayPreferences {
  if (!text) return DEFAULT_DISPLAY;
  try {
    const value = JSON.parse(text) as Partial<DisplayPreferences>;
    return {
      hideEmptyRows: typeof value.hideEmptyRows === "boolean" ? value.hideEmptyRows : DEFAULT_DISPLAY.hideEmptyRows,
      showReportedZeros:
        typeof value.showReportedZeros === "boolean" ? value.showReportedZeros : DEFAULT_DISPLAY.showReportedZeros,
      hideEmptyMonths:
        typeof value.hideEmptyMonths === "boolean" ? value.hideEmptyMonths : DEFAULT_DISPLAY.hideEmptyMonths,
      hiddenSeries: Array.isArray(value.hiddenSeries)
        ? value.hiddenSeries.filter((item): item is string => typeof item === "string")
        : [],
    };
  } catch {
    return DEFAULT_DISPLAY;
  }
}

function subscribe(onChange: () => void) {
  window.addEventListener("storage", onChange);
  window.addEventListener(CHANGE_EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(CHANGE_EVENT, onChange);
  };
}

/** The saved preferences of one surface; the server and first render use the defaults. */
export function useDisplayPreferences(surface: string) {
  const text = useSyncExternalStore(
    subscribe,
    () => read(surface),
    () => null,
  );
  const preferences = useMemo(() => parsePreferences(text), [text]);
  const save = useCallback(
    (next: DisplayPreferences | null) => {
      try {
        if (next === null) window.localStorage.removeItem(STORAGE_PREFIX + surface);
        else window.localStorage.setItem(STORAGE_PREFIX + surface, JSON.stringify(next));
      } catch {
        // Storage can be unavailable (e.g. private browsing); the page keeps the defaults.
      }
      window.dispatchEvent(new Event(CHANGE_EVENT));
    },
    [surface],
  );
  return {
    preferences,
    update: (change: Partial<DisplayPreferences>) => save({ ...preferences, ...change }),
    reset: () => save(null),
  };
}

type Values = readonly (number | null)[];

/** A row is empty only when every cell is null; with zeros hidden, only-zero rows count as empty too. */
export function isEmptyRow(values: Values, preferences: DisplayPreferences): boolean {
  if (values.every((value) => value === null)) return preferences.hideEmptyRows;
  if (!preferences.showReportedZeros) return values.every((value) => value === null || value === 0);
  return false;
}

/** Rows to show and how many were hidden. Hidden rows still count in every total. */
export function visibleRows<T>(
  rows: readonly T[],
  values: (row: T) => Values,
  preferences: DisplayPreferences,
): { rows: T[]; hidden: number } {
  const shown = rows.filter((row) => !isEmptyRow(values(row), preferences));
  return { rows: shown, hidden: rows.length - shown.length };
}

/** Indexes of the columns to show; a column is empty when no row reports it. */
export function visibleColumns(
  count: number,
  rows: readonly Values[],
  preferences: DisplayPreferences,
): number[] {
  const all = Array.from({ length: count }, (_, index) => index);
  if (!preferences.hideEmptyMonths) return all;
  return all.filter((index) => rows.some((row) => row[index] !== null && row[index] !== undefined));
}

export function pick<T>(values: readonly T[], indexes: number[]): T[] {
  return indexes.map((index) => values[index]);
}

type DisplayControlsProps = {
  preferences: DisplayPreferences;
  onChange: (change: Partial<DisplayPreferences>) => void;
  onReset: () => void;
  /** Offer the Hide empty months option. */
  months?: boolean;
  /** Offer the row options. */
  rowOptions?: boolean;
  series?: { id: string; label: string }[];
  className?: string;
};

/** A "Display" disclosure with the view's options. Native details/summary: keyboard and touch work as usual. */
export function DisplayControls({
  preferences,
  onChange,
  onReset,
  months = false,
  rowOptions = true,
  series = [],
  className,
}: DisplayControlsProps) {
  const id = useId();
  const changed = JSON.stringify(preferences) !== JSON.stringify(DEFAULT_DISPLAY);
  const check = (key: "hideEmptyRows" | "showReportedZeros" | "hideEmptyMonths", label: string) => (
    <label key={key} htmlFor={`${id}-${key}`} className="flex min-h-9 items-center gap-2 text-sm pointer-coarse:min-h-11">
      <input
        id={`${id}-${key}`}
        type="checkbox"
        checked={preferences[key]}
        onChange={(event) => onChange({ [key]: event.target.checked })}
        className="size-4 accent-primary"
      />
      {label}
    </label>
  );
  return (
    <details className={cn("group relative", className)}>
      <summary
        className={cn(
          "inline-flex h-9 cursor-pointer list-none items-center gap-2 rounded-md border bg-card px-3 text-sm font-medium shadow-xs select-none hover:bg-muted pointer-coarse:h-11",
          "focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none [&::-webkit-details-marker]:hidden",
        )}
      >
        <SlidersHorizontal aria-hidden className="size-4" />
        Display
        {changed && <span className="size-1.5 rounded-full bg-primary" aria-label="(changed)" />}
      </summary>
      <div className="mt-2 w-full space-y-1 rounded-lg border bg-card p-3 shadow-md sm:absolute sm:right-0 sm:z-20 sm:w-72">
        {rowOptions && check("hideEmptyRows", "Hide empty rows")}
        {rowOptions && check("showReportedZeros", "Show reported zeros")}
        {months && check("hideEmptyMonths", "Hide empty months")}
        {series.length > 0 && (
          <fieldset className="border-t pt-2">
            <legend className="pt-2 text-xs font-medium text-muted-foreground">Series</legend>
            {series.map((item) => (
              <label key={item.id} className="flex min-h-9 items-center gap-2 text-sm pointer-coarse:min-h-11">
                <input
                  type="checkbox"
                  checked={!preferences.hiddenSeries.includes(item.id)}
                  onChange={(event) =>
                    onChange({
                      hiddenSeries: event.target.checked
                        ? preferences.hiddenSeries.filter((hidden) => hidden !== item.id)
                        : [...preferences.hiddenSeries, item.id],
                    })
                  }
                  className="size-4 accent-primary"
                />
                {item.label}
              </label>
            ))}
          </fieldset>
        )}
        <p className="border-t pt-2 text-xs text-muted-foreground">
          Display only. Hidden rows and months still count in every total. Saved in this browser.
        </p>
        <Button variant="ghost" size="sm" onClick={onReset} disabled={!changed} className="w-full pointer-coarse:h-11">
          <RotateCcw />
          Reset
        </Button>
      </div>
    </details>
  );
}

/** e.g. "5 empty rows hidden · Show all". */
export function HiddenNotice({
  hidden,
  noun,
  onShowAll,
}: {
  hidden: number;
  noun: [one: string, many: string];
  onShowAll: () => void;
}) {
  if (hidden === 0) return null;
  return (
    <p className="flex flex-wrap items-center gap-x-2 px-1 text-xs text-muted-foreground" role="status">
      {hidden} {hidden === 1 ? noun[0] : noun[1]} hidden
      <button
        type="button"
        onClick={onShowAll}
        className="rounded-sm font-medium text-primary underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none pointer-coarse:min-h-11"
      >
        Show all
      </button>
    </p>
  );
}
