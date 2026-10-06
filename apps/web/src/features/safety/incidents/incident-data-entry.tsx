"use client";

import { AlertTriangle, CircleCheck, RefreshCw, Save, Undo2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { MonthlyGrid, type MonthlyGridRow } from "@/components/common/monthly-grid";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";

import { describeSafetyError, editConflicts, type MetricSectionBlock } from "./api";
import {
  cellKey,
  draftSectionValues,
  MONTH_LABELS,
  parseCount,
  summarizeDraft,
  total,
  type Draft,
} from "./grid";
import { ReportingYearSelect } from "./reporting-year-select";
import { useIncidentMetrics, useSaveIncidentMetrics } from "./use-incident-metrics";

function useUnsavedChangesWarning(active: boolean) {
  useEffect(() => {
    if (!active) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [active]);
}

/** Rows only: categories are never summed into a section total (see MetricSectionBlock). */
function sectionRows(section: MetricSectionBlock, draft: Draft): MonthlyGridRow[] {
  const states = draftSectionValues(section, draft);
  return section.categories.map((category, index) => ({
    id: String(category.id),
    label: category.name,
    cells: states[index].map(({ text, dirty, invalid }) => ({ text, dirty, invalid })),
    total: total(states[index].map((cell) => cell.value)),
  }));
}

type IncidentDataEntryProps = {
  title: string;
  description?: string;
};

export function IncidentDataEntry({ title, description }: IncidentDataEntryProps) {
  const [year, setYear] = useState(() => new Date().getFullYear());
  const [draft, setDraft] = useState<Draft>({});
  const [notice, setNotice] = useState<string | null>(null);
  const metrics = useIncidentMetrics(year);
  const save = useSaveIncidentMetrics(year);

  const data = metrics.data;
  const summary = useMemo(
    () => (data ? summarizeDraft(data, draft) : { changes: [], invalidCount: 0 }),
    [data, draft],
  );
  const dirty = summary.changes.length > 0 || summary.invalidCount > 0;
  const editable = data?.canEdit ?? false;
  const conflicts = editConflicts(save.error);

  useUnsavedChangesWarning(dirty);

  const changeYear = (next: number) => {
    if (next === year) return;
    if (dirty && !window.confirm(`Discard unsaved changes for ${year}?`)) return;
    setDraft({});
    setNotice(null);
    save.reset();
    setYear(next);
  };

  const setCell = (rowId: string, column: number, text: string) => {
    setNotice(null);
    setDraft((current) => ({ ...current, [cellKey(Number(rowId), column + 1)]: text }));
  };

  const revertCell = (rowId: string, column: number) =>
    setDraft((current) => {
      const next = { ...current };
      delete next[cellKey(Number(rowId), column + 1)];
      return next;
    });

  const discard = () => {
    setDraft({});
    setNotice(null);
    save.reset();
  };

  const submit = () => {
    if (!editable || summary.invalidCount > 0 || summary.changes.length === 0) return;
    const saved = new Map(summary.changes.map((c) => [cellKey(c.categoryId, c.month), c.value]));
    setNotice(null);
    save.mutate(summary.changes, {
      onSuccess: (response) => {
        // Keep edits typed while the save was in flight.
        setDraft((current) => {
          const next: Draft = {};
          for (const [key, text] of Object.entries(current)) {
            const parsed = parseCount(text);
            if (!(saved.has(key) && parsed.ok && parsed.value === saved.get(key))) next[key] = text;
          }
          return next;
        });
        const count = response.changedCells;
        setNotice(
          count === 0
            ? "Nothing needed saving; the stored values already match."
            : `Saved ${count.toLocaleString()} ${count === 1 ? "value" : "values"} for ${year}.`,
        );
      },
    });
  };

  const reloadLatest = () => {
    save.reset();
    void metrics.refetch();
  };

  const accessDenied =
    metrics.error instanceof ApiError && (metrics.error.status === 401 || metrics.error.status === 403);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Safety · Incident & Near Miss"
        title={title}
        description={description}
        status={
          save.isPending ? (
            <StatusBadge tone="pending" pulse>
              Saving
            </StatusBadge>
          ) : dirty ? (
            <StatusBadge tone="warning">Unsaved changes</StatusBadge>
          ) : data && !editable ? (
            <StatusBadge>Read only</StatusBadge>
          ) : undefined
        }
        actions={
          editable && (
            <>
              <Button variant="outline" onClick={discard} disabled={!dirty || save.isPending}>
                <Undo2 />
                Discard
              </Button>
              <Button
                onClick={submit}
                disabled={summary.changes.length === 0 || summary.invalidCount > 0 || save.isPending}
              >
                <Save />
                {summary.changes.length > 0
                  ? `Save ${summary.changes.length.toLocaleString()} ${summary.changes.length === 1 ? "change" : "changes"}`
                  : "Save"}
              </Button>
            </>
          )
        }
      />

      <div className="space-y-2">
        <FilterBar
          actions={
            metrics.isFetching && !metrics.isPending ? (
              <StatusBadge tone="pending" pulse>
                Updating
              </StatusBadge>
            ) : undefined
          }
        >
          <ReportingYearSelect
            year={year}
            onChange={changeYear}
            yearsWithData={data?.yearsWithData}
            disabled={save.isPending}
          />
        </FilterBar>
        <p className="px-1 text-xs text-muted-foreground">
          Blank cells are unreported. Enter 0 for a month with no events. YTD is calculated from
          the monthly values and cannot be edited. Enter Incident and Near Miss totals directly;
          they are not calculated from Incident Classification, which can overlap.
        </p>
      </div>

      <div aria-live="polite" className="space-y-2">
        {notice && (
          <div
            role="status"
            className="flex items-center gap-2 rounded-lg border border-success/30 bg-success/10 px-4 py-3 text-sm text-success"
          >
            <CircleCheck className="size-4 shrink-0" />
            {notice}
          </div>
        )}
        {summary.invalidCount > 0 && (
          <p role="alert" className="px-1 text-sm text-destructive">
            {summary.invalidCount === 1 ? "1 cell contains" : `${summary.invalidCount} cells contain`}{" "}
            an invalid value. Counts must be whole numbers from 0 to 100,000, or blank.
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
                ? `${conflicts.length === 1 ? "1 value was" : `${conflicts.length} values were`} changed by someone else since you loaded this year. Nothing was saved. Reload the latest values; your edits stay in place.`
                : `Changes were not saved. ${describeSafetyError(save.error)}`}
            </p>
            {conflicts && (
              <Button variant="outline" size="sm" onClick={reloadLatest}>
                <RefreshCw />
                Reload latest values
              </Button>
            )}
          </div>
        )}
      </div>

      {metrics.isError ? (
        <EmptyState
          icon={AlertTriangle}
          title={accessDenied ? "Safety data is not available to you" : "Could not load Safety data"}
          description={describeSafetyError(metrics.error)}
          action={
            accessDenied ? undefined : (
              <Button variant="outline" size="sm" onClick={() => void metrics.refetch()}>
                Retry
              </Button>
            )
          }
        />
      ) : !data ? (
        <div className="space-y-5">
          <MonthlyGrid
            title="Incident & Near Miss"
            columns={MONTH_LABELS}
            rows={[]}
            editable={false}
            loading
          />
          <span className="sr-only">Loading Safety data</span>
        </div>
      ) : data.sections.length === 0 ? (
        <EmptyState
          title="No Incident & Near Miss categories are configured"
          description="Run the database migrations to create the Safety section and category definitions."
        />
      ) : (
        <div className="space-y-5">
          {data.sections.map((section) => (
            <MonthlyGrid
              key={section.id}
              title={section.name}
              columns={MONTH_LABELS}
              rows={sectionRows(section, draft)}
              editable={editable}
              onCellChange={setCell}
              onCellRevert={revertCell}
            />
          ))}
        </div>
      )}
    </div>
  );
}
