"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { FilterBar, FilterSelect } from "@/components/common/filter-bar";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

import {
  costKeys,
  describeCostError,
  fetchCostSummary,
  type CoqClass,
  type CostPeriodQuery,
  type CostSummary,
} from "./api";
import { COQ_CLASS_COLORS, COQ_CLASS_LABELS, MONTH_LABELS, toNumber, usd } from "./format";

export function useCostSummary() {
  const [query, setQuery] = useState<CostPeriodQuery>({ year: null, from: null, through: null });
  const summary = useQuery({
    queryKey: costKeys.summary(query),
    queryFn: ({ signal }) => fetchCostSummary(query, signal),
    retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
  });
  return { query, setQuery, summary };
}

type CostSummaryQuery = ReturnType<typeof useCostSummary>;

const MONTH_OPTIONS = MONTH_LABELS.map((label, index) => ({ value: String(index + 1), label }));

/** Year and month-range filters. The source records no area, product, owner or status. */
export function CostFilters({ state, children }: { state: CostSummaryQuery; children?: React.ReactNode }) {
  const { query, setQuery, summary } = state;
  const data = summary.data;
  const years = [...new Set([...(data?.availableYears ?? []), ...(query.year !== null ? [query.year] : [])])].sort(
    (a, b) => b - a,
  );
  const latest = data?.latestReportedMonth;
  return (
    <div className="space-y-2">
      <FilterBar
        actions={
          summary.isFetching && !summary.isPending ? (
            <StatusBadge tone="pending" pulse>
              Updating
            </StatusBadge>
          ) : undefined
        }
      >
        <FilterSelect
          label="Year"
          placeholder={data?.year ? `Latest (${data.year})` : "Latest"}
          options={years.map((value) => ({ value: String(value), label: String(value) }))}
          value={query.year === null ? "" : String(query.year)}
          onChange={(event) =>
            setQuery({ year: event.target.value ? Number(event.target.value) : null, from: null, through: null })
          }
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="From"
          placeholder="Jan"
          options={MONTH_OPTIONS}
          value={query.from === null ? "" : String(query.from)}
          onChange={(event) => setQuery({ ...query, from: event.target.value ? Number(event.target.value) : null })}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Through"
          placeholder={latest ? `Latest reported (${MONTH_LABELS[latest - 1]})` : "Latest reported"}
          options={MONTH_OPTIONS}
          value={query.through === null ? "" : String(query.through)}
          onChange={(event) => setQuery({ ...query, through: event.target.value ? Number(event.target.value) : null })}
          className="pointer-coarse:h-11"
        />
        {children}
      </FilterBar>
      <p className="text-xs text-muted-foreground">
        Area, product, owner and status filters are not available: the source workbook records none of them.
      </p>
    </div>
  );
}

export function CostError({ summary }: { summary: CostSummaryQuery["summary"] }) {
  const error = summary.error;
  const accessDenied = error instanceof ApiError && (error.status === 401 || error.status === 403);
  return (
    <EmptyState
      icon={AlertTriangle}
      title={accessDenied ? "Cost of Quality data is not available to you" : "Could not load Cost of Quality data"}
      description={describeCostError(error)}
      action={
        accessDenied ? undefined : (
          <Button variant="outline" size="sm" onClick={() => void summary.refetch()}>
            Retry
          </Button>
        )
      }
    />
  );
}

export function NoFigures() {
  return (
    <EmptyState
      icon={AlertTriangle}
      title="No Cost of Quality figures"
      description="No monthly figures have been imported. They are loaded from the reviewed COQ workbook mapping; nothing is shown until then."
    />
  );
}

/** A value cell with a data bar scaled to the largest value in its column. */
export function DataBar({ value, max, color, children }: { value: number | null; max: number; color: string; children: React.ReactNode }) {
  const width = value !== null && max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <span className="relative block min-w-24 rounded-sm">
      {width > 0 && (
        <span
          aria-hidden
          className="absolute inset-y-0 left-0 rounded-sm opacity-15"
          style={{ width: `${width}%`, backgroundColor: color }}
        />
      )}
      <span className="relative px-1">{children}</span>
    </span>
  );
}

export function NotReported() {
  return <span className="text-xs text-muted-foreground">Not reported</span>;
}

export const TH = "px-3 py-2 text-xs font-medium text-muted-foreground first:pl-4";
export const TD = "px-3 py-2 first:pl-4";

export function TableSection({
  id,
  title,
  description,
  actions,
  children,
}: {
  id: string;
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="overflow-hidden rounded-lg border bg-card">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <h2 id={id} className="text-sm font-semibold">
            {title}
          </h2>
          {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
        </div>
        {actions}
      </header>
      {children}
    </section>
  );
}

type CostLine = {
  key: string;
  month: number;
  label: string;
  category: string;
  coqClass: CoqClass;
  sourceTerm: string;
  value: string | null;
};

/** Every cost line of every reported month in the period, as the source reports it. */
export function costLines(data: CostSummary): CostLine[] {
  const { fromMonth, throughMonth } = data.period;
  if (fromMonth === null || throughMonth === null) return [];
  return data.months
    .filter((month) => month.reported && month.month >= fromMonth && month.month <= throughMonth)
    .flatMap((month) =>
      data.elements.map((element) => ({
        key: `${month.month}-${element.code}`,
        month: month.month,
        label: element.label,
        category: element.category,
        coqClass: element.coqClass,
        sourceTerm: element.sourceTerm,
        value: month.elements[element.code] ?? null,
      })),
    )
    .sort((a, b) => a.month - b.month || (toNumber(b.value) ?? -1) - (toNumber(a.value) ?? -1));
}

/** Searchable cost-line detail, optionally limited to one COQ class. */
export function CostLineRegister({
  data,
  coqClass = null,
  title = "Cost line detail",
}: {
  data: CostSummary;
  coqClass?: CoqClass | null;
  title?: string;
}) {
  const [search, setSearch] = useState("");
  const all = useMemo(() => costLines(data), [data]);
  const term = search.trim().toLowerCase();
  const rows = all.filter(
    (line) =>
      (coqClass === null || line.coqClass === coqClass) &&
      (term === "" ||
        [line.label, line.category, COQ_CLASS_LABELS[line.coqClass], line.sourceTerm, MONTH_LABELS[line.month - 1]]
          .join(" ")
          .toLowerCase()
          .includes(term)),
  );
  const max = Math.max(0, ...rows.map((line) => toNumber(line.value) ?? 0));
  const unrecorded = coqClass === "prevention" || coqClass === "appraisal";
  return (
    <TableSection
      id="cost-lines"
      title={title}
      description="Each cost line by month as calculated from the source. Bars compare amounts within the rows shown."
      actions={
        <label className="relative flex items-center">
          <span className="sr-only">Search cost lines</span>
          <Search aria-hidden className="pointer-events-none absolute left-2.5 size-4 text-muted-foreground" />
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search cost lines"
            className="h-9 w-56 rounded-md border bg-background pr-3 pl-8 text-sm pointer-coarse:h-11"
          />
        </label>
      }
    >
      {rows.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">
          {unrecorded
            ? `${COQ_CLASS_LABELS[coqClass!]} costs are not recorded in the source workbook.`
            : all.length === 0
              ? "No cost lines are reported in this period."
              : "No cost lines match the search."}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm tabular-nums">
            <caption className="sr-only">{title}</caption>
            <thead className="border-b">
              <tr>
                {["Month", "Cost line", "Category", "COQ class", "Source column", "Amount"].map((heading) => (
                  <th key={heading} scope="col" className={TH}>
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((line) => (
                <tr key={line.key} className="border-b border-border/60 last:border-b-0">
                  <td className={TD}>
                    {MONTH_LABELS[line.month - 1]} {data.year}
                  </td>
                  <th scope="row" className={cn(TD, "font-medium")}>
                    {line.label}
                  </th>
                  <td className={TD}>{line.category}</td>
                  <td className={TD}>
                    <span className="inline-flex items-center gap-1.5">
                      <span aria-hidden className="size-2 rounded-full" style={{ backgroundColor: COQ_CLASS_COLORS[line.coqClass] }} />
                      {COQ_CLASS_LABELS[line.coqClass]}
                    </span>
                  </td>
                  <td className={cn(TD, "text-xs text-muted-foreground")}>{line.sourceTerm}</td>
                  <td className={TD}>
                    {line.value === null ? (
                      <NotReported />
                    ) : (
                      <DataBar value={toNumber(line.value)} max={max} color={COQ_CLASS_COLORS[line.coqClass]}>
                        {usd(line.value, 2)}
                      </DataBar>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </TableSection>
  );
}

export function DataChecks({ data }: { data: CostSummary }) {
  return (
    <section aria-labelledby="cost-checks" className="rounded-lg border bg-card px-4 py-3 text-sm">
      <h2 id="cost-checks" className="font-semibold">
        Data checks
      </h2>
      <p className="mt-0.5 text-xs text-muted-foreground">
        About the selected period and the source. Nothing is changed or filled in to make figures complete.
      </p>
      <ul className="mt-2 space-y-1.5">
        {data.dataChecks.map((check, index) => (
          <li key={index} className="flex items-start gap-2">
            <StatusBadge tone={check.status === "warning" ? "warning" : "info"}>
              {check.status === "warning" ? "Check" : "Note"}
            </StatusBadge>
            <span>
              {check.month !== null && check.year !== null && (
                <span className="font-medium">
                  {MONTH_LABELS[check.month - 1]} {check.year}:{" "}
                </span>
              )}
              {check.message}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Definitions({ data }: { data: CostSummary }) {
  return (
    <details className="rounded-lg border bg-card px-4 py-3 text-sm">
      <summary className="cursor-pointer font-semibold">Definitions</summary>
      <p className="mt-1 text-xs text-muted-foreground">From the Definitions sheet of {data.source}.</p>
      <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-[max-content_1fr]">
        {data.definitions.map((item) => (
          <div key={item.term} className="contents">
            <dt className="font-medium">{item.term}</dt>
            <dd className="text-muted-foreground">{item.definition}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
