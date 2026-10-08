"use client";

import { AlertTriangle, CircleCheck, RefreshCw, Save, Undo2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

import { describeSafetyError, type BehaviorChange, type BehaviorConflict, type BehaviorCountsResponse } from "./api";
import { formatCount, parseCount, total } from "./grid";
import { useBehaviorCounts, useSaveBehaviorCounts } from "./use-incident-metrics";

/** Typed text per category id; a category without an entry shows its stored value. */
type BehaviorDraft = Record<number, string>;

export function summarizeBehaviorDraft(
  data: BehaviorCountsResponse,
  draft: BehaviorDraft,
): { changes: BehaviorChange[]; invalidCount: number } {
  const changes: BehaviorChange[] = [];
  let invalidCount = 0;
  for (const category of data.categories) {
    const text = draft[category.id];
    if (text === undefined) continue;
    const parsed = parseCount(text);
    if (!parsed.ok) invalidCount += 1;
    else if (parsed.value !== category.value) {
      changes.push({ categoryId: category.id, value: parsed.value, previousValue: category.value });
    }
  }
  return { changes, invalidCount };
}

function behaviorConflicts(error: unknown): BehaviorConflict[] | null {
  if (!(error instanceof ApiError) || error.detail?.error !== "edit_conflict") return null;
  return Array.isArray(error.detail.conflicts) ? (error.detail.conflicts as BehaviorConflict[]) : [];
}

type AnnualBehaviorEntryProps = {
  year: number;
  /** Reports unsaved Behavior edits so the page can guard year changes and navigation. */
  onDirtyChange: (dirty: boolean) => void;
};

/**
 * Annual Behavior tag counts: one value per category for the whole year, with
 * its own save. Blank is not reported; 0 is an explicit zero. Mount with
 * `key={year}` so a year change starts from a clean draft.
 */
export function AnnualBehaviorEntry({ year, onDirtyChange }: AnnualBehaviorEntryProps) {
  const counts = useBehaviorCounts(year);
  const save = useSaveBehaviorCounts(year);
  const [draft, setDraft] = useState<BehaviorDraft>({});
  const [notice, setNotice] = useState<string | null>(null);

  const data = counts.data;
  const summary = useMemo(
    () => (data ? summarizeBehaviorDraft(data, draft) : { changes: [], invalidCount: 0 }),
    [data, draft],
  );
  const dirty = summary.changes.length > 0 || summary.invalidCount > 0;
  const editable = data?.canEdit ?? false;
  const conflicts = behaviorConflicts(save.error);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);

  const draftTotal = data
    ? total(
        data.categories.map((category) => {
          const text = draft[category.id];
          if (text === undefined) return category.value;
          const parsed = parseCount(text);
          return parsed.ok ? parsed.value : null;
        }),
      )
    : null;

  const setValue = (id: number, text: string) => {
    setNotice(null);
    setDraft((current) => ({ ...current, [id]: text }));
  };

  const discard = () => {
    setDraft({});
    setNotice(null);
    save.reset();
  };

  const submit = () => {
    if (!editable || summary.invalidCount > 0 || summary.changes.length === 0) return;
    const saved = new Map(summary.changes.map((c) => [c.categoryId, c.value]));
    setNotice(null);
    save.mutate(summary.changes, {
      onSuccess: (response) => {
        setDraft((current) => {
          const next: BehaviorDraft = {};
          for (const [key, text] of Object.entries(current)) {
            const id = Number(key);
            const parsed = parseCount(text);
            if (!(saved.has(id) && parsed.ok && parsed.value === saved.get(id))) next[id] = text;
          }
          return next;
        });
        const count = response.changedCategories;
        setNotice(
          count === 0
            ? "Nothing needed saving; the stored counts already match."
            : `Saved ${count} behavior ${count === 1 ? "count" : "counts"} for ${year}.`,
        );
      },
    });
  };

  const headingId = `behavior-entry-${year}`;
  return (
    <section aria-labelledby={headingId} className="rounded-lg border bg-card text-card-foreground">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0 max-w-3xl">
          <h2 id={headingId} className="text-sm font-semibold">
            Annual Behavior tagging, {year}
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            One count per behavior for the whole year, not monthly values. One incident report can carry more than
            one behavior tag, so the tags can exceed the Incident total. Leave a behavior blank when it is not
            reported; enter 0 only for an explicit zero.
          </p>
        </div>
        <div aria-live="polite" className="flex items-center gap-2 empty:hidden">
          {save.isPending ? (
            <StatusBadge tone="pending" pulse>
              Saving
            </StatusBadge>
          ) : dirty ? (
            <StatusBadge tone="warning">
              {summary.changes.length > 0
                ? `${summary.changes.length} unsaved ${summary.changes.length === 1 ? "change" : "changes"}`
                : "Unsaved changes"}
            </StatusBadge>
          ) : notice ? (
            <p role="status" className="flex items-center gap-1.5 text-sm text-success">
              <CircleCheck className="size-4 shrink-0" />
              {notice}
            </p>
          ) : data && !editable ? (
            <StatusBadge>Read only</StatusBadge>
          ) : null}
        </div>
      </header>

      {counts.isError ? (
        <div role="alert" className="flex items-center justify-between gap-3 px-4 py-3 text-sm text-destructive">
          <span className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            Behavior counts could not be loaded. {describeSafetyError(counts.error)}
          </span>
          <Button variant="outline" size="sm" onClick={() => void counts.refetch()}>
            Retry
          </Button>
        </div>
      ) : !data ? (
        <div className="p-4" aria-busy>
          <div className="h-24 animate-pulse rounded-md bg-muted/70" />
          <span className="sr-only">Loading Behavior counts</span>
        </div>
      ) : (
        <div className="space-y-3 px-4 py-3">
          {summary.invalidCount > 0 && (
            <p role="alert" className="text-sm text-destructive">
              {summary.invalidCount === 1 ? "1 count is" : `${summary.invalidCount} counts are`} invalid. Counts must be
              whole numbers from 0 to 100,000, or blank.
            </p>
          )}
          {save.isError && (
            <div
              role="alert"
              className="flex flex-col gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between"
            >
              <p className="flex items-start gap-2 text-destructive">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                {conflicts
                  ? `${conflicts.length === 1 ? "1 count was" : `${conflicts.length} counts were`} changed by someone else since you loaded this year. Nothing was saved. Reload the latest counts; your edits stay in place.`
                  : `Behavior counts were not saved. ${describeSafetyError(save.error)}`}
              </p>
              {conflicts && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    save.reset();
                    void counts.refetch();
                  }}
                >
                  <RefreshCw />
                  Reload latest counts
                </Button>
              )}
            </div>
          )}
          <ul className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2 xl:grid-cols-3">
            {data.categories.map((category) => {
              const text = draft[category.id] ?? formatCount(category.value);
              const parsed = parseCount(text);
              const changed = draft[category.id] !== undefined && (!parsed.ok || parsed.value !== category.value);
              const inputId = `behavior-${year}-${category.code}`;
              return (
                <li key={category.id} className="flex items-center justify-between gap-3">
                  <label htmlFor={inputId} className="min-w-0 text-sm">
                    {category.name}
                  </label>
                  {editable ? (
                    <input
                      id={inputId}
                      inputMode="numeric"
                      autoComplete="off"
                      value={text}
                      placeholder="—"
                      aria-invalid={!parsed.ok || undefined}
                      onChange={(event) => setValue(category.id, event.target.value)}
                      disabled={save.isPending}
                      className={cn(
                        "h-8 w-20 shrink-0 rounded-md border bg-background px-2 text-right text-sm tabular-nums placeholder:text-muted-foreground/60 pointer-coarse:h-11",
                        changed && "bg-warning/20",
                        !parsed.ok && "border-destructive",
                      )}
                    />
                  ) : (
                    <output id={inputId} className="w-20 text-right text-sm tabular-nums">
                      {category.value === null ? (
                        <span className="text-muted-foreground/60">
                          <span aria-hidden>—</span>
                          <span className="sr-only">Not reported</span>
                        </span>
                      ) : (
                        category.value
                      )}
                    </output>
                  )}
                </li>
              );
            })}
          </ul>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-3">
            <p className="text-sm text-muted-foreground">
              Behavior tags, {year}:{" "}
              <span className="font-semibold text-foreground tabular-nums">
                {draftTotal === null ? "Not reported" : draftTotal.toLocaleString()}
              </span>
            </p>
            {editable && (
              <div className="flex items-center gap-2">
                <Button variant="ghost" onClick={discard} disabled={!dirty || save.isPending}>
                  <Undo2 />
                  Discard
                </Button>
                <Button
                  onClick={submit}
                  disabled={summary.changes.length === 0 || summary.invalidCount > 0 || save.isPending}
                >
                  <Save />
                  Save behavior counts
                </Button>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
