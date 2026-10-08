"use client";

import {
  AlertTriangle,
  CircleCheck,
  LayoutDashboard,
  RefreshCw,
  Save,
  Undo2,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { MonthlyGrid, type MonthlyGridRow } from "@/components/common/monthly-grid";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

import { describeSafetyError, editConflicts, type MetricSectionBlock } from "./api";
import { AnnualBehaviorEntry } from "./behavior-entry";
import {
  authoritativeTotals,
  BREAKDOWN_CHECKS,
  cellKey,
  checkMonth,
  defaultReportingYear,
  draftMonthlyTotals,
  draftSectionValues,
  FIRST_REPORTING_YEAR,
  MONTH_LABELS,
  parseCount,
  summarizeDraft,
  TAG_SECTIONS,
  total,
  type Draft,
  type MonthCheck,
} from "./grid";
import { yearOf } from "../site-calendar";
import { useAutomaticValue, useSiteToday } from "../use-site-calendar";
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
    description: category.description,
    cells: states[index].map(({ text, dirty, invalid }) => ({ text, dirty, invalid })),
    total: total(states[index].map((cell) => cell.value)),
  }));
}

/**
 * Collapsed-header orientation: each explicit category's own YTD. Sections with
 * many categories get none, since adding overlapping classifications together
 * would be misleading.
 */
const MAX_SUMMARY_CATEGORIES = 2;

function sectionSummary(rows: MonthlyGridRow[]): string | null {
  if (rows.length === 0 || rows.length > MAX_SUMMARY_CATEGORIES) return null;
  const format = (value: number | null) => (value === null ? "—" : value.toLocaleString());
  if (rows.length === 1) return `YTD ${format(rows[0].total)}`;
  return `YTD ${rows.map((row) => `${row.label} ${format(row.total)}`).join(" · ")}`;
}

function sectionStatus(rows: MonthlyGridRow[]) {
  const cells = rows.flatMap((row) => row.cells);
  const invalid = cells.filter((cell) => cell.invalid).length;
  const unsaved = cells.filter((cell) => cell.dirty && !cell.invalid).length;
  if (invalid > 0) return <StatusBadge tone="danger">{invalid} invalid</StatusBadge>;
  if (unsaved > 0) return <StatusBadge tone="warning">{unsaved} unsaved</StatusBadge>;
  return null;
}

/** Shown expanded on small or touch screens; other sections start collapsed there. */
const PRIMARY_SECTION_CODE = "incident_near_miss_totals";
const COMPACT_LAYOUT_QUERY = "(pointer: coarse), (max-width: 1279px)";
const OPEN_SECTIONS_KEY = "safety.incidents.data-entry.open-sections";

function readOpenSections(): Record<string, boolean> {
  try {
    const parsed: unknown = JSON.parse(window.sessionStorage.getItem(OPEN_SECTIONS_KEY) ?? "{}");
    return parsed && typeof parsed === "object" ? (parsed as Record<string, boolean>) : {};
  } catch {
    return {};
  }
}

type SectionGridsProps = {
  sections: MetricSectionBlock[];
  draft: Draft;
  editable: boolean;
  onCellChange: (rowId: string, column: number, text: string) => void;
  onCellRevert: (rowId: string, column: number) => void;
};

/** Mounted only once data has loaded in the browser, so window is available. */
function SectionGrids({ sections, draft, editable, onCellChange, onCellRevert }: SectionGridsProps) {
  const [compact] = useState(() => window.matchMedia(COMPACT_LAYOUT_QUERY).matches);
  const [chosen, setChosen] = useState(readOpenSections);

  const isOpen = (code: string) => chosen[code] ?? (!compact || code === PRIMARY_SECTION_CODE);
  const setOpen = (code: string, open: boolean) => {
    const next = { ...chosen, [code]: open };
    setChosen(next);
    try {
      window.sessionStorage.setItem(OPEN_SECTIONS_KEY, JSON.stringify(next));
    } catch {
      // Storage can be unavailable (e.g. private browsing); the choice still applies on this page.
    }
  };

  const breakdownCodes = BREAKDOWN_GROUPS.map(([, code]) => code);
  const totalsGroup = sections.filter((section) => !breakdownCodes.includes(section.code));
  const breakdowns = BREAKDOWN_GROUPS.flatMap(([letter, code]) => {
    const section = sections.find((s) => s.code === code);
    return section ? [{ letter, section }] : [];
  });

  const grid = (section: MetricSectionBlock, title: string, breakdown: boolean) => {
    const rows = sectionRows(section, draft);
    const monthly = draftMonthlyTotals(section, draft);
    return (
      <MonthlyGrid
        key={section.id}
        title={title}
        columns={MONTH_LABELS}
        rows={rows}
        editable={editable}
        onCellChange={onCellChange}
        onCellRevert={onCellRevert}
        open={isOpen(section.code)}
        onOpenChange={(open) => setOpen(section.code, open)}
        summary={sectionSummary(rows)}
        status={sectionStatus(rows)}
        footer={
          breakdown
            ? { label: "Sum of categories", values: monthly, total: total(monthly) }
            : undefined
        }
        notes={breakdown && <BreakdownNotes section={section} sections={sections} draft={draft} />}
      />
    );
  };

  return (
    <div className="space-y-6">
      <section aria-labelledby="group-totals" className="space-y-4">
        <h2 id="group-totals" className="px-1 text-base font-semibold">
          A · Incident totals and classifications
        </h2>
        {totalsGroup.map((section) => grid(section, section.name, false))}
      </section>
      {breakdowns.length > 0 && (
        <section aria-labelledby="group-breakdowns" className="space-y-4">
          <div className="px-1">
            <h2 id="group-breakdowns" className="text-base font-semibold">
              Breakdowns
            </h2>
            <p className="mt-0.5 max-w-4xl text-sm text-muted-foreground">
              Supporting dimensions of the totals above, which stay authoritative. Each month is checked against
              its total as you type; a difference is a warning only and nothing is filled in or distributed. Blank is
              not reported; 0 is a reported zero.
            </p>
          </div>
          {breakdowns.map(({ letter, section }) => grid(section, `${letter} · ${section.name}`, true))}
        </section>
      )}
    </div>
  );
}

/** Groups B–H, in this order; every other section is in group A. */
const BREAKDOWN_GROUPS: [letter: string, code: string][] = [
  ["B", "incidents_by_area"],
  ["C", "near_misses_by_area"],
  ["D", "near_miss_potential"],
  ["E", "near_miss_cause"],
  ["F", "lopc_contributing_factor"],
  ["G", "injury_cause"],
  ["H", "body_part"],
];

const MONTH_CHECK_TEXT: Record<Exclude<MonthCheck, "reconciled">, string> = {
  below_total: "below total",
  above_total: "above total",
  no_dimension_data: "no breakdown data",
  no_authoritative_total: "no authoritative total",
};

/** Live, non-blocking comparison of a breakdown with its authoritative total, month by month. */
function BreakdownNotes({
  section,
  sections,
  draft,
}: {
  section: MetricSectionBlock;
  sections: MetricSectionBlock[];
  draft: Draft;
}) {
  if (TAG_SECTIONS.has(section.code)) {
    return (
      <p className="text-xs text-muted-foreground">
        Tags may exceed the near-miss count: one near miss can carry more than one {section.name.toLowerCase()}.
      </p>
    );
  }
  const check = BREAKDOWN_CHECKS[section.code];
  if (!check) return null;
  const parts = draftMonthlyTotals(section, draft);
  const whole = authoritativeTotals(sections, check.against, draft);
  const months = MONTH_LABELS.map((label, index) => {
    const authoritative = whole?.[index] ?? null;
    return { label, parts: parts[index], whole: authoritative, state: checkMonth(parts[index], authoritative) };
  }).filter((month) => month.state !== null);
  const reconciled = months.filter((month) => month.state === "reconciled");
  const flagged = months.filter((month) => month.state !== "reconciled");
  const noData = check.parts === "Areas" ? "no area data" : "no breakdown data";

  return (
    <div aria-live="polite" className="space-y-1 text-xs">
      <p className="font-medium text-muted-foreground">
        Checked against {check.label} (warning only).
        {section.code === "body_part" && " Body parts are tags: one injury can involve more than one."}
      </p>
      {months.length === 0 && <p className="text-muted-foreground">No months to check yet.</p>}
      {reconciled.length > 0 && (
        <p className="text-success">Reconciled: {reconciled.map((month) => month.label).join(", ")}</p>
      )}
      {flagged.length > 0 && (
        <ul className="space-y-0.5">
          {flagged.map((month) => {
            const state = month.state as Exclude<MonthCheck, "reconciled">;
            const difference = month.parts !== null && month.whole !== null ? month.parts - month.whole : null;
            return (
              <li key={month.label} className={cn(difference !== null ? "text-amber-700 dark:text-warning" : "text-muted-foreground")}>
                {month.label}: {check.parts} {month.parts ?? "not reported"}, {check.label}{" "}
                {month.whole ?? "not reported"} ·{" "}
                {state === "no_dimension_data" ? noData : MONTH_CHECK_TEXT[state]}
                {difference !== null && ` (reconciliation difference ${difference > 0 ? "+" : "−"}${Math.abs(difference)})`}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function GridKey({ editable }: { editable: boolean }) {
  const swatch = "inline-grid h-5 min-w-7 place-items-center rounded-sm border px-1 tabular-nums";
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-1 pt-1 text-xs text-muted-foreground">
      <span className="flex items-center gap-1.5">
        <span aria-hidden className={cn(swatch, "bg-card text-muted-foreground/60")}>
          —
        </span>
        Not reported
      </span>
      <span className="flex items-center gap-1.5">
        <span aria-hidden className={cn(swatch, "bg-card font-medium text-foreground")}>
          0
        </span>
        Reported zero
      </span>
      {editable && (
        <span className="flex items-center gap-1.5">
          <span aria-hidden className={cn(swatch, "border-transparent bg-warning/20")} />
          Unsaved edit
        </span>
      )}
      <span className="flex items-center gap-1.5">
        <span aria-hidden className={cn(swatch, "bg-muted font-semibold text-foreground")}>
          Σ
        </span>
        YTD is calculated from reported months
      </span>
      <span className="basis-full">
        Incident and Near Miss are entered as reported totals, not summed from classifications.
        {editable && (
          <span className="hidden lg:inline">
            {" "}
            Enter or arrow keys move between cells; Esc restores a cell.
          </span>
        )}
      </span>
    </div>
  );
}

type IncidentDataEntryProps = {
  title: string;
  description?: string;
  /** The Baytown date when the page was rendered on the server. */
  siteToday: string;
};

export function IncidentDataEntry({ title, description, siteToday }: IncidentDataEntryProps) {
  const currentYear = yearOf(useSiteToday(siteToday));
  const [draft, setDraft] = useState<Draft>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [behaviorDirty, setBehaviorDirty] = useState(false);
  // Draft cells have no year (and stay in the draft until saved), so a year
  // with unsaved or in-flight changes never moves at midnight.
  const yearChoice = useAutomaticValue(defaultReportingYear(currentYear), {
    hold: Object.keys(draft).length > 0 || behaviorDirty,
  });
  const year = yearChoice.value;
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

  const anyDirty = dirty || behaviorDirty;

  useUnsavedChangesWarning(anyDirty);

  const changeYear = (next: number) => {
    if (next === year) return;
    if (anyDirty && !window.confirm(`Discard unsaved changes for ${year}?`)) return;
    setDraft({});
    setNotice(null);
    save.reset();
    yearChoice.choose(next);
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

  const changeCount = summary.changes.length;

  const leaveFor = (event: React.MouseEvent) => {
    if (anyDirty && !window.confirm(`Leave without saving your changes for ${year}?`)) {
      event.preventDefault();
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Safety · Incident & Near Miss"
        title={title}
        description={description}
        actions={
          <Link
            href="/safety/incidents/dashboard"
            onClick={leaveFor}
            className={buttonVariants({ variant: "outline" })}
          >
            <LayoutDashboard />
            View dashboard
          </Link>
        }
      />

      <div className="sticky top-14 z-[15] -mx-1 -my-1 bg-background px-1 py-1">
        <div
          role="group"
          aria-label="Reporting year and saving"
          className="flex flex-wrap items-end gap-x-3 gap-y-2 rounded-lg border bg-card p-2.5 shadow-sm sm:flex-nowrap"
        >
          <div className="w-32 shrink-0 sm:w-40">
            <ReportingYearSelect
              year={year}
              onChange={changeYear}
              currentYear={currentYear}
              firstYear={FIRST_REPORTING_YEAR}
              yearsWithData={data?.yearsWithData}
              disabled={save.isPending}
            />
          </div>
          <div
            aria-live="polite"
            className="order-last flex min-w-0 basis-full items-center empty:hidden sm:order-none sm:basis-auto sm:flex-1 sm:justify-end sm:self-center"
          >
            {save.isPending ? (
              <StatusBadge tone="pending" pulse>
                Saving
              </StatusBadge>
            ) : dirty ? (
              <StatusBadge tone="warning" className="text-sm">
                {changeCount > 0
                  ? `${changeCount.toLocaleString()} unsaved ${changeCount === 1 ? "change" : "changes"}`
                  : "Unsaved changes"}
              </StatusBadge>
            ) : notice ? (
              <p role="status" className="flex items-center gap-1.5 text-sm text-success">
                <CircleCheck className="size-4 shrink-0" />
                {notice}
              </p>
            ) : metrics.isFetching && !metrics.isPending ? (
              <StatusBadge tone="pending" pulse>
                Updating
              </StatusBadge>
            ) : data && !editable ? (
              <StatusBadge>Read only</StatusBadge>
            ) : data ? (
              <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <CircleCheck className="size-4 shrink-0" />
                All changes saved
              </span>
            ) : null}
          </div>
          {editable && (
            <div className="ml-auto flex shrink-0 items-center gap-2">
              <Button
                variant="ghost"
                onClick={discard}
                disabled={!dirty || save.isPending}
                className="pointer-coarse:h-11 max-sm:pointer-coarse:w-11"
              >
                <Undo2 />
                <span className="max-sm:sr-only">Discard</span>
              </Button>
              <Button
                onClick={submit}
                disabled={changeCount === 0 || summary.invalidCount > 0 || save.isPending}
                className="pointer-coarse:h-11 pointer-coarse:px-5"
              >
                <Save />
                Save changes
              </Button>
            </div>
          )}
        </div>
      </div>

      <GridKey editable={editable} />

      <div aria-live="polite" className="space-y-2 empty:hidden">
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
        <SectionGrids
          sections={data.sections}
          draft={draft}
          editable={editable}
          onCellChange={setCell}
          onCellRevert={revertCell}
        />
      )}

      <AnnualBehaviorEntry key={year} year={year} onDirtyChange={setBehaviorDirty} />
    </div>
  );
}
