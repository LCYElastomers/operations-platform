"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, Calculator, Clock, Gauge, Scale, TrendingDown } from "lucide-react";
import { useState } from "react";

import { BarChart } from "@/components/common/bar-chart";
import {
  DisplayControls,
  HiddenNotice,
  useDisplayPreferences,
  visibleRows,
} from "@/components/common/display-controls";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar, FilterSelect } from "@/components/common/filter-bar";
import { MetricCard } from "@/components/common/metric-card";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

import { describeSafetyError } from "../incidents/api";
import { MONTH_LABELS } from "../incidents/grid";
import { yearOf } from "../site-calendar";
import { useAutomaticValue, useSiteToday } from "../use-site-calendar";
import { fetchTrirExperience, trirKeys, type TrirCalculation, type TrirExperience, type TrirMonth } from "./api";

/** The earliest year of the TRIR history. */
export const FIRST_TRIR_YEAR = 2021;

const LCY_COLOR = "#2563eb";
const BENCHMARK_COLOR = "#64748b";

const MONTH_STATES: Record<TrirMonth["state"], string> = {
  closed: "Closed",
  open: "Open",
  not_reported: "Not reported",
  zero_hours: "Zero hours",
  count_not_confirmed: "Count not confirmed",
};

const MISSING_REASONS: Record<string, string> = {
  not_reported: "hours not reported",
  open: "month not closed",
  zero_hours: "zero hours entered",
  count_not_confirmed: "recordable count not confirmed",
};

function hours(value: number | null): string {
  return value === null ? "—" : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function period(calculation: TrirCalculation): string {
  if (calculation.basis === "historical_annual") return `${calculation.year} (full year)`;
  if (calculation.fromMonth === null || calculation.throughMonth === null) return String(calculation.year);
  const first = MONTH_LABELS[calculation.fromMonth - 1];
  const last = MONTH_LABELS[calculation.throughMonth - 1];
  if (calculation.fromYear !== null && calculation.fromYear !== calculation.year) {
    return `${first} ${calculation.fromYear}–${last} ${calculation.year}`;
  }
  return first === last ? `${last} ${calculation.year}` : `${first}–${last} ${calculation.year}`;
}

function useTrirExperience(year: number, through: number | null) {
  return useQuery({
    queryKey: trirKeys.experience(year, through),
    queryFn: ({ signal }) => fetchTrirExperience(year, through, signal),
    retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
  });
}

type Shown = { title: string; calculation: TrirCalculation } | null;

export function TrirExperiencePage({
  title,
  description,
  siteToday,
}: {
  title: string;
  description?: string;
  siteToday: string;
}) {
  const currentYear = yearOf(useSiteToday(siteToday));
  const yearChoice = useAutomaticValue(currentYear);
  const year = yearChoice.value;
  const [through, setThrough] = useState<number | null>(null);
  const experience = useTrirExperience(year, through);
  const data = experience.data;
  const [shown, setShown] = useState<Shown>(null);
  const display = useDisplayPreferences("safety.trir");

  const years = Array.from({ length: Math.max(1, currentYear - FIRST_TRIR_YEAR + 1) }, (_, index) => currentYear - index);
  const accessDenied =
    experience.error instanceof ApiError && (experience.error.status === 401 || experience.error.status === 403);
  const view = (name: string, calculation: TrirCalculation) => setShown({ title: name, calculation });

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Safety · TRIR Experience" title={title} description={description} />
      <p className="-mt-2 max-w-4xl text-sm text-muted-foreground">
        Total Recordable Incident Rate: recordable cases × 200,000 ÷ hours worked. Hours come from Safety Performance;
        they are never entered here. Every rate shows its calculation.
      </p>

      <FilterBar
        actions={
          experience.isFetching && !experience.isPending ? (
            <StatusBadge tone="pending" pulse>
              Updating
            </StatusBadge>
          ) : undefined
        }
      >
        <FilterSelect
          label="Year"
          placeholder={false}
          options={years.map((value) => ({ value: String(value), label: String(value) }))}
          value={String(year)}
          onChange={(event) => {
            yearChoice.choose(Number(event.target.value));
            setThrough(null);
          }}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Through month"
          placeholder={
            data?.status.latestCompleteMonth
              ? `Latest complete (${MONTH_LABELS[data.status.latestCompleteMonth - 1]})`
              : "Latest complete"
          }
          options={MONTH_LABELS.map((label, index) => ({ value: String(index + 1), label }))}
          value={through === null ? "" : String(through)}
          onChange={(event) => setThrough(event.target.value ? Number(event.target.value) : null)}
          disabled={data?.current.basis === "historical_annual"}
          className="pointer-coarse:h-11"
        />
      </FilterBar>

      {experience.isError ? (
        <EmptyState
          icon={AlertTriangle}
          title={accessDenied ? "TRIR data is not available to you" : "Could not load TRIR data"}
          description={describeSafetyError(experience.error)}
          action={
            accessDenied ? undefined : (
              <Button variant="outline" size="sm" onClick={() => void experience.refetch()}>
                Retry
              </Button>
            )
          }
        />
      ) : (
        <>
          <Kpis data={data} loading={experience.isPending} onView={view} />
          <HistoryChart data={data} loading={experience.isPending} hiddenSeries={display.preferences.hiddenSeries} />
          <div className="flex justify-end">
            <DisplayControls
              preferences={display.preferences}
              onChange={display.update}
              onReset={display.reset}
              series={[
                { id: "lcy", label: "LCY TRIR" },
                { id: "benchmark", label: "Industry benchmark" },
              ]}
            />
          </div>
          {data && <HistoryTable data={data} onView={view} />}
          {data && data.monthly.length > 0 && (
            <MonthlyTable
              data={data}
              preferences={display.preferences}
              onShowAll={() => display.update({ hideEmptyRows: false, showReportedZeros: true })}
              onView={view}
            />
          )}
          {data && <DataQuality data={data} />}
          {data && <Methodology data={data} />}
        </>
      )}

      <Dialog
        open={shown !== null}
        onClose={() => setShown(null)}
        title={shown ? `How ${shown.title} is calculated` : ""}
        description={shown ? period(shown.calculation) : undefined}
      >
        {shown && <CalculationDetail calculation={shown.calculation} />}
      </Dialog>
    </div>
  );
}

function ViewCalculation({ name, calculation, onView }: { name: string; calculation: TrirCalculation; onView: (name: string, c: TrirCalculation) => void }) {
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => onView(name, calculation)}
      aria-label={`View calculation for ${name}`}
      className="pointer-coarse:h-11"
    >
      <Calculator />
      View calculation
    </Button>
  );
}

function Kpis({
  data,
  loading,
  onView,
}: {
  data: TrirExperience | undefined;
  loading: boolean;
  onView: (name: string, calculation: TrirCalculation) => void;
}) {
  const current = data?.current;
  const rolling = data?.rolling12;
  const comparison = data?.comparison;
  return (
    <section aria-label="TRIR" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <div className="flex flex-col gap-2">
        <MetricCard
          label={current?.basis === "historical_annual" ? `LCY TRIR ${data?.year}` : `LCY TRIR YTD`}
          value={current?.display ?? null}
          caption={current ? (current.formula ? `${current.formula}, ${period(current)}` : (current.unavailableReason ?? "Unavailable")) : undefined}
          detail={current && !current.complete && current.display ? "Partial: some months are missing." : null}
          icon={Gauge}
          emphasis
          loading={loading}
        />
        {current && <ViewCalculation name={`LCY TRIR, ${period(current)}`} calculation={current} onView={onView} />}
      </div>
      <MetricCard
        label={comparison?.benchmarkYear ? `Industry benchmark (${comparison.benchmarkYear})` : "Industry benchmark"}
        value={comparison?.benchmark ?? null}
        caption={comparison?.statement}
        detail={
          comparison?.benchmarkYear && data && comparison.benchmarkYear !== data.year
            ? `No ${data.year} benchmark; the ${comparison.benchmarkYear} value is shown.`
            : null
        }
        icon={Scale}
        emphasis
        loading={loading}
      />
      <div className="flex flex-col gap-2">
        <MetricCard
          label="Rolling 12-month TRIR"
          value={rolling?.display ?? null}
          caption={rolling ? (rolling.formula ? `${rolling.formula}, ${period(rolling)}` : (rolling.unavailableReason ?? "Unavailable")) : undefined}
          icon={TrendingDown}
          emphasis
          loading={loading}
        />
        {rolling && rolling.formula && (
          <ViewCalculation name="Rolling 12-month TRIR" calculation={rolling} onView={onView} />
        )}
      </div>
      <MetricCard
        label="Recordable cases"
        value={current?.recordables ?? null}
        caption={current ? `${period(current)}. ${current.numeratorSource}` : undefined}
        icon={Activity}
        loading={loading}
      />
      <MetricCard
        label="Hours worked"
        value={current?.hours ?? null}
        caption={current ? `${period(current)}. ${current.denominatorSource}` : undefined}
        icon={Clock}
        loading={loading}
      />
      <MetricCard
        label="Incidents (all classifications)"
        value={data?.incidentCount ?? null}
        caption="Shown for context; not the TRIR numerator."
        icon={AlertTriangle}
        loading={loading}
      />
    </section>
  );
}

function HistoryChart({
  data,
  loading,
  hiddenSeries,
}: {
  data: TrirExperience | undefined;
  loading: boolean;
  hiddenSeries: string[];
}) {
  const rows = data?.history ?? [];
  const value = (text: string | null) => (text === null ? null : Number(text));
  return (
    <BarChart
      title="LCY TRIR vs Industry Benchmark by Year"
      description="Bars are LCY TRIR rounded to 2 decimals; the dashed line is the industry benchmark. A partial year is labelled. Exact values are in the table."
      categories={rows.map((row) => (row.partial ? `${row.year} (YTD)` : String(row.year)))}
      series={hiddenSeries.includes("lcy") ? [] : [{ name: "LCY TRIR", values: rows.map((row) => value(row.calculation.display)), color: LCY_COLOR }]}
      lines={
        hiddenSeries.includes("benchmark")
          ? []
          : [
              {
                name: "Industry benchmark",
                values: rows.map((row) => value(row.benchmark?.value ?? null)),
                color: BENCHMARK_COLOR,
                dashed: true,
              },
            ]
      }
      showValues
      loading={loading}
      height={320}
    />
  );
}

function Table({ caption, children }: { caption: string; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-sm tabular-nums">
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}

const TH = "px-3 py-2 text-xs font-medium text-muted-foreground first:pl-4";
const TD = "px-3 py-2 first:pl-4";

function HistoryTable({ data, onView }: { data: TrirExperience; onView: (name: string, calculation: TrirCalculation) => void }) {
  return (
    <section aria-labelledby="trir-history" className="overflow-hidden rounded-lg border bg-card">
      <header className="border-b px-4 py-3">
        <h2 id="trir-history" className="text-sm font-semibold">
          TRIR history
        </h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Recalculated from recordable cases and hours. Legacy figures are shown for comparison and never used in the
          calculation.
        </p>
      </header>
      <Table caption="TRIR by year">
        <thead className="border-b">
          <tr>
            {["Year", "Recordables", "Hours", "LCY TRIR", "Benchmark", "Comparison", "Legacy TRIR", ""].map((heading) => (
              <th key={heading} scope="col" className={TH}>
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.history.map((row) => (
            <tr key={row.year} className="border-b border-border/60 align-top last:border-b-0">
              <th scope="row" className={cn(TD, "font-medium")}>
                {row.year}
                {row.partial && <span className="block text-xs font-normal text-muted-foreground">{period(row.calculation)}</span>}
              </th>
              <td className={TD}>{row.calculation.recordables ?? "—"}</td>
              <td className={TD}>{hours(row.calculation.hours)}</td>
              <td className={cn(TD, "font-semibold")} title={row.calculation.rate ?? undefined}>
                {row.calculation.display ?? "—"}
              </td>
              <td className={TD}>
                {row.benchmark?.value ?? "—"}
                {row.benchmark && row.benchmark.year !== row.year && (
                  <span className="block text-xs text-muted-foreground">{row.benchmark.year} value</span>
                )}
              </td>
              <td className={cn(TD, "max-w-56 text-xs")}>{row.comparison.statement}</td>
              <td className={TD}>
                {row.legacyTrir ?? "—"}
                {row.legacyDifference && Number(row.legacyDifference) !== 0 && (
                  <span className="block text-xs text-amber-700 dark:text-warning">differs by {row.legacyDifference}</span>
                )}
              </td>
              <td className={TD}>
                {row.calculation.formula && (
                  <ViewCalculation name={`LCY TRIR ${period(row.calculation)}`} calculation={row.calculation} onView={onView} />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      {data.history.some((row) => row.note) && (
        <ul className="space-y-1 border-t px-4 py-3 text-xs text-muted-foreground">
          {data.history
            .filter((row) => row.note)
            .map((row) => (
              <li key={row.year}>
                <span className="font-medium text-foreground">{row.year}:</span> {row.note}
              </li>
            ))}
        </ul>
      )}
    </section>
  );
}

/** A month's year-to-date TRIR as a calculation, from the figures the API returned for that month. */
export function monthCalculation(data: TrirExperience, row: TrirMonth): TrirCalculation {
  const formula =
    row.ytdRecordables !== null && row.ytdHours !== null
      ? `(${row.ytdRecordables.toLocaleString("en-US")} × 200,000) ÷ ${row.ytdHours
          .toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
          .replace(/\.00$/, "")}`
      : null;
  return {
    year: data.year,
    basis: "safety_performance_monthly",
    fromYear: data.year,
    fromMonth: 1,
    throughMonth: row.month,
    recordables: row.ytdRecordables,
    hours: row.ytdHours,
    rate: row.ytdRate,
    display: row.ytdDisplay,
    formula,
    numeratorSource: data.current.numeratorSource,
    denominatorSource: data.current.denominatorSource,
    complete: true,
    missingMonths: [],
    unavailableReason: null,
  };
}

function MonthlyTable({
  data,
  preferences,
  onShowAll,
  onView,
}: {
  data: TrirExperience;
  preferences: Parameters<typeof visibleRows>[2];
  onShowAll: () => void;
  onView: (name: string, calculation: TrirCalculation) => void;
}) {
  const rows = visibleRows(data.monthly, (row) => [row.recordables, row.hours], preferences);
  return (
    <section aria-labelledby="trir-monthly" className="overflow-hidden rounded-lg border bg-card">
      <header className="border-b px-4 py-3">
        <h2 id="trir-monthly" className="text-sm font-semibold">
          {data.year} by month
        </h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Hours and recordable cases from Safety Performance. Year-to-date TRIR uses closed months from January only.
        </p>
        <HiddenNotice hidden={rows.hidden} noun={["unreported month", "unreported months"]} onShowAll={onShowAll} />
      </header>
      <Table caption={`TRIR by month, ${data.year}`}>
        <thead className="border-b">
          <tr>
            {["Month", "Status", "Recordables", "Hours", "YTD recordables", "YTD hours", "YTD TRIR"].map((heading) => (
              <th key={heading} scope="col" className={TH}>
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.rows.map((row) => (
            <tr key={row.month} className="border-b border-border/60 last:border-b-0">
              <th scope="row" className={cn(TD, "font-medium")}>
                {MONTH_LABELS[row.month - 1]}
              </th>
              <td className={TD}>
                <StatusBadge tone={row.state === "closed" ? "success" : row.state === "not_reported" ? "neutral" : "warning"}>
                  {MONTH_STATES[row.state]}
                </StatusBadge>
              </td>
              <td className={TD}>{row.recordables ?? "—"}</td>
              <td className={TD}>{hours(row.hours)}</td>
              <td className={TD}>{row.ytdRecordables ?? "—"}</td>
              <td className={TD}>{hours(row.ytdHours)}</td>
              <td className={cn(TD, "font-semibold")} title={row.ytdRate ?? undefined}>
                <span className="flex items-center gap-2">
                  {row.ytdDisplay ?? "—"}
                  {row.ytdRate !== null && (
                    <ViewCalculation
                      name={`YTD TRIR through ${MONTH_LABELS[row.month - 1]} ${data.year}`}
                      calculation={monthCalculation(data, row)}
                      onView={onView}
                    />
                  )}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    </section>
  );
}

function DataQuality({ data }: { data: TrirExperience }) {
  const warnings = data.dataQuality.filter((item) => item.status === "warning");
  return (
    <section aria-labelledby="trir-quality" className="rounded-lg border bg-card px-4 py-3 text-sm">
      <h2 id="trir-quality" className="font-semibold">
        Data checks
      </h2>
      <p className="mt-0.5 text-xs text-muted-foreground">
        Warnings only. Nothing is changed to make figures agree.
      </p>
      <ul className="mt-2 space-y-1.5">
        {data.dataQuality.map((item, index) => (
          <li key={index} className="flex items-start gap-2">
            <StatusBadge tone={item.status === "ok" ? "success" : "warning"}>{item.status === "ok" ? "OK" : "Check"}</StatusBadge>
            <span className={cn(item.status === "ok" && "text-muted-foreground")}>
              {item.year !== null && <span className="font-medium text-foreground">{item.year}: </span>}
              {item.message}
            </span>
          </li>
        ))}
      </ul>
      {warnings.length === 0 && <p className="mt-2 text-muted-foreground">All checks agree.</p>}
    </section>
  );
}

function Methodology({ data }: { data: TrirExperience }) {
  const m = data.methodology;
  const items: [string, string][] = [
    ["Formula", m.formula],
    ["Numerator", m.numerator],
    ["Denominator", m.denominator],
    ["Contractor hours", m.contractorHours],
    ["Benchmark", m.benchmark],
    ["Cutoff", m.cutoff],
    ["Rounding", m.rounding],
    ["Comparison", m.comparisonTolerance],
    ["Historical years", m.historicalYears],
    ["Unreported months", m.unreportedMonths],
    ["TIR", m.legacyTir],
  ];
  return (
    <section aria-labelledby="trir-methodology" className="rounded-lg border bg-card px-4 py-3 text-sm">
      <h2 id="trir-methodology" className="font-semibold">
        Methodology
      </h2>
      <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-[max-content_1fr]">
        {items.map(([term, text]) => (
          <div key={term} className="contents">
            <dt className="font-medium">{term}</dt>
            <dd className="text-muted-foreground">{text}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function CalculationDetail({ calculation }: { calculation: TrirCalculation }) {
  const rows: [string, React.ReactNode][] = [
    ["Formula", calculation.formula ?? "Not calculated"],
    [
      "Numerator",
      <>
        {calculation.recordables ?? "—"} recordable {calculation.recordables === 1 ? "case" : "cases"}
        <span className="block text-xs text-muted-foreground">{calculation.numeratorSource}</span>
      </>,
    ],
    [
      "Denominator",
      <>
        {hours(calculation.hours)} hours
        <span className="block text-xs text-muted-foreground">{calculation.denominatorSource}</span>
      </>,
    ],
    ["Period (cutoff)", period(calculation)],
    ["Exact result", calculation.rate ?? "—"],
    ["Shown as", calculation.display ? `${calculation.display} (rounded half-up to 2 decimals)` : "—"],
  ];
  return (
    <div className="space-y-4 text-sm">
      <dl className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-[max-content_1fr]">
        {rows.map(([term, value]) => (
          <div key={term} className="contents">
            <dt className="font-medium">{term}</dt>
            <dd className="break-words tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
      {calculation.unavailableReason && (
        <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2">{calculation.unavailableReason}</p>
      )}
      {calculation.missingMonths.length > 0 && (
        <div>
          <p className="font-medium">Not included</p>
          <ul className="mt-1 list-disc pl-5 text-muted-foreground">
            {calculation.missingMonths.map((missing) => (
              <li key={`${missing.year}-${missing.month}`}>
                {MONTH_LABELS[missing.month - 1]} {missing.year}: {MISSING_REASONS[missing.reason] ?? missing.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        TRIR is never interchanged with TIR. Calculated with exact decimals; only the displayed value is rounded.
      </p>
    </div>
  );
}
