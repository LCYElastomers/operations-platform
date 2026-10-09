"use client";

import { CircleDollarSign, Percent, ShieldCheck, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { BarChart } from "@/components/common/bar-chart";
import { MetricCard } from "@/components/common/metric-card";
import { PageHeader } from "@/components/common/page-header";
import { cn } from "@/lib/utils";

import type { CoqClass, CoqClassSummary, CostSummary, CostSummaryQuery } from "./api";
import {
  CostError,
  CostFilters,
  DataChecks,
  Definitions,
  isFiltered,
  NoRecords,
  NotEntered,
  periodRecordQuery,
  RecordTable,
  TableSection,
  TD,
  TH,
  useCostSummaryQuery,
} from "./cost-shared";
import { COQ_CLASS_COLORS, MONTH_LABELS, percent, periodLabel, POTENTIAL_COLOR, recordsLabel, toNumber, usd } from "./format";
import { AddCostRecordButton } from "./record-dialog";
import { useCostRecords, useCostSummary } from "./use-cost";

const CLASS_ORDER: CoqClass[] = ["prevention", "appraisal", "internal_failure", "external_failure"];

const QUADRANT_TEXT: Record<CoqClass, string> = {
  prevention: "Costs to stop defects happening: planning, training, process control.",
  appraisal: "Costs to find defects: inspection, testing, audits.",
  internal_failure: "Defects found before shipment: scrap, rework, downtime.",
  external_failure: "Defects found by customers: complaints, returns, credits.",
};

export function CoqMatrixPage({ title, description }: { title: string; description?: string }) {
  const [query, setQuery] = useCostSummaryQuery(false);
  const [selected, setSelected] = useState<CoqClass | null>(null);
  const summary = useCostSummary(query);
  const data = summary.data;
  const filtered = isFiltered(query) || query.year !== null || query.from !== null || query.through !== null;
  const total = data ? data.classes.reduce((sum, item) => sum + item.figures.count, 0) : 0;
  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Quality · Cost of Quality"
        title={title}
        description={description}
        actions={<AddCostRecordButton coqClass={selected ?? undefined} />}
      />
      <p className="-mt-2 max-w-4xl text-sm text-muted-foreground">
        Cost of Quality = good quality costs (prevention + appraisal) + poor quality costs (internal + external failure),
        from every item in the Quality Cost Register. Figures are confirmed cost; potential exposure is shown beside them,
        never added in. A class with no confirmed cost is shown as not recorded, not as $0.
      </p>
      <CostFilters query={query} onChange={setQuery} data={data} fetching={summary.isFetching && !summary.isPending} />
      {summary.isError ? (
        <CostError error={summary.error} onRetry={() => void summary.refetch()} />
      ) : data && (data.year === null || total === 0) ? (
        <NoRecords filtered={filtered} action={filtered ? undefined : <AddCostRecordButton />} />
      ) : (
        <>
          <Kpis data={data} loading={summary.isPending} />
          {data && (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <Quadrants data={data} selected={selected} onSelect={setSelected} />
              <div className="space-y-4">
                <Mix data={data} />
                <Trend data={data} />
              </div>
            </div>
          )}
          {data && <CategoryTable data={data} />}
          {data && <ClassItems data={data} query={query} selected={selected} />}
          {data && <DataChecks data={data} />}
          {data && <Definitions data={data} />}
        </>
      )}
    </div>
  );
}

function Kpis({ data, loading }: { data: CostSummary | undefined; loading: boolean }) {
  const matrix = data?.matrix;
  const label = data ? periodLabel(data) : undefined;
  const potential = (value: string | null | undefined) => (value ? `Plus ${usd(value)} potential exposure` : label);
  const unavailable = "Not calculable: no confirmed Prevention or Appraisal cost is recorded.";
  return (
    <section aria-label="Cost of Quality" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard
        label="Total COQ"
        value={matrix?.total ? usd(matrix.total) : null}
        caption={matrix?.total ? potential(matrix.totalPotential) : unavailable}
        icon={CircleDollarSign}
        emphasis
        loading={loading}
      />
      <MetricCard
        label="Good COQ (P + A)"
        value={matrix?.good ? usd(matrix.good) : null}
        caption={matrix?.good ? potential(matrix.goodPotential) : "No confirmed Prevention or Appraisal cost recorded."}
        icon={ShieldCheck}
        emphasis
        loading={loading}
      />
      <MetricCard
        label="Poor COQ (IF + EF)"
        value={matrix?.poor ? usd(matrix.poor) : null}
        caption={matrix?.poor ? potential(matrix.poorPotential) : "No confirmed failure cost recorded."}
        icon={TriangleAlert}
        emphasis
        loading={loading}
      />
      <MetricCard
        label="Poor COQ % of total"
        value={matrix?.poorPct ? percent(matrix.poorPct) : null}
        caption={matrix?.poorPct ? `${label} · confirmed cost` : unavailable}
        icon={Percent}
        emphasis
        loading={loading}
      />
    </section>
  );
}

function Quadrant({ item, selected, onSelect }: { item: CoqClassSummary; selected: boolean; onSelect: () => void }) {
  const color = COQ_CLASS_COLORS[item.code];
  const { figures } = item;
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className="flex min-h-40 flex-col rounded-lg border-2 p-4 text-left transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
      style={{ borderColor: selected ? color : `${color}55`, backgroundColor: `${color}${selected ? "1a" : "0d"}` }}
    >
      <span className="flex w-full items-center justify-between gap-2">
        <span className="text-sm font-semibold" style={{ color }}>
          {item.label}
        </span>
        <span className="text-xs text-muted-foreground">{recordsLabel(figures.count)}</span>
      </span>
      <span className="mt-2 text-2xl font-semibold tabular-nums">
        {figures.confirmed === null ? (
          <span className="text-muted-foreground/70">
            <span aria-hidden>—</span>
            <span className="sr-only">Not recorded</span>
          </span>
        ) : (
          usd(figures.confirmed)
        )}
      </span>
      <span className="text-xs text-muted-foreground">
        {item.shareOfTotal ? `${percent(item.shareOfTotal, 1)} of total COQ` : figures.confirmed === null ? "No confirmed cost" : "Confirmed cost"}
      </span>
      {figures.potential && (
        <span className="mt-1 text-xs italic" style={{ color: POTENTIAL_COLOR }}>
          + {usd(figures.potential)} potential exposure
        </span>
      )}
      <span className="mt-auto pt-2 text-xs text-muted-foreground">{QUADRANT_TEXT[item.code]}</span>
    </button>
  );
}

function Quadrants({
  data,
  selected,
  onSelect,
}: {
  data: CostSummary;
  selected: CoqClass | null;
  onSelect: (value: CoqClass | null) => void;
}) {
  const byCode = Object.fromEntries(data.classes.map((item) => [item.code, item])) as Record<CoqClass, CoqClassSummary>;
  return (
    <section aria-labelledby="coq-matrix" className="rounded-lg border bg-card">
      <header className="border-b px-4 py-3">
        <h2 id="coq-matrix" className="text-sm font-semibold">
          Cost of Quality matrix
        </h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {periodLabel(data)}. Top row: good quality costs. Bottom row: poor quality costs. Select a class to list its items.
        </p>
      </header>
      <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2">
        {CLASS_ORDER.map((code) => (
          <Quadrant key={code} item={byCode[code]} selected={selected === code} onSelect={() => onSelect(selected === code ? null : code)} />
        ))}
      </div>
    </section>
  );
}

function Mix({ data }: { data: CostSummary }) {
  const confirmed = data.classes
    .map((item) => ({ item, value: toNumber(item.figures.confirmed) }))
    .filter((entry): entry is { item: CoqClassSummary; value: number } => entry.value !== null && entry.value > 0);
  const sum = confirmed.reduce((total, entry) => total + entry.value, 0);
  const goodMissing = data.matrix.good === null;
  return (
    <section aria-labelledby="coq-mix" className="rounded-lg border bg-card px-4 py-3">
      <h2 id="coq-mix" className="text-sm font-semibold">
        COQ mix
      </h2>
      <p className="mt-0.5 text-xs text-muted-foreground">
        Share of confirmed cost ({usd(sum > 0 ? String(sum) : null)}).
        {goodMissing && " No Prevention or Appraisal cost is recorded, so this is the failure-cost mix only."}
      </p>
      {confirmed.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">No confirmed cost in this selection.</p>
      ) : (
        <>
          <div className="mt-3 flex h-4 w-full overflow-hidden rounded-full bg-muted" role="img" aria-label="COQ mix">
            {confirmed.map(({ item, value }) => (
              <div key={item.code} style={{ width: `${(value / sum) * 100}%`, backgroundColor: COQ_CLASS_COLORS[item.code] }} />
            ))}
          </div>
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {data.classes.map((item) => {
              const value = toNumber(item.figures.confirmed);
              return (
                <li key={item.code} className="flex items-center gap-1.5">
                  <span aria-hidden className="size-2.5 rounded-sm" style={{ backgroundColor: COQ_CLASS_COLORS[item.code] }} />
                  <span>{item.label}</span>
                  <span className="text-muted-foreground tabular-nums">
                    {value === null ? "not recorded" : `${((value / sum) * 100).toFixed(1)}%`}
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

function dollars(value: string | null) {
  const number = toNumber(value);
  return number === null ? null : Math.round(number);
}

function Trend({ data }: { data: CostSummary }) {
  const months = data.months.filter((month) => month.month >= data.fromMonth && month.month <= data.throughMonth);
  const labels = Object.fromEntries(data.classes.map((item) => [item.code, item.label])) as Record<CoqClass, string>;
  return (
    <BarChart
      title="COQ by class and month"
      description="Confirmed cost by class. The dashed line is potential exposure across all classes. A month without items draws no bar."
      categories={months.map((month) => MONTH_LABELS[month.month - 1])}
      series={CLASS_ORDER.map((code) => ({
        name: labels[code],
        values: months.map((month) => dollars(month.confirmed[code])),
        color: COQ_CLASS_COLORS[code],
        stack: "coq",
      }))}
      lines={[
        {
          name: "Potential exposure",
          values: months.map((month) => {
            const values = CLASS_ORDER.map((code) => toNumber(month.potential[code])).filter((v): v is number => v !== null);
            return values.length === 0 ? null : Math.round(values.reduce((a, b) => a + b, 0));
          }),
          color: POTENTIAL_COLOR,
          dashed: true,
        },
      ]}
      height={240}
    />
  );
}

function CategoryTable({ data }: { data: CostSummary }) {
  const labels = Object.fromEntries(data.classes.map((item) => [item.code, item.label])) as Record<CoqClass, string>;
  const rows = [...data.categories].sort((a, b) => CLASS_ORDER.indexOf(a.coqClass) - CLASS_ORDER.indexOf(b.coqClass));
  const money = (value: string | null, italic = false) =>
    value === null ? <NotEntered label="—" /> : <span className={cn(italic && "italic")}>{usd(value)}</span>;
  return (
    <TableSection id="coq-categories" title="COQ by category" description={`${periodLabel(data)}. Confirmed cost and potential exposure kept apart.`}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-left text-sm tabular-nums">
          <caption className="sr-only">COQ by category</caption>
          <thead className="border-b">
            <tr>
              {["Class", "Category", "Items", "Confirmed", "Share of class", "Potential exposure", "Recovered", "Avoided"].map((heading) => (
                <th key={heading} scope="col" className={TH}>
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.code} className="border-b border-border/60 last:border-b-0">
                <td className={cn(TD, "whitespace-nowrap")}>
                  <span className="inline-flex items-center gap-1.5">
                    <span aria-hidden className="size-2 rounded-full" style={{ backgroundColor: COQ_CLASS_COLORS[row.coqClass] }} />
                    {labels[row.coqClass]}
                  </span>
                </td>
                <th scope="row" className={cn(TD, "font-medium")}>
                  {row.label}
                </th>
                <td className={TD}>{row.figures.count}</td>
                <td className={TD}>{money(row.figures.confirmed)}</td>
                <td className={TD}>{row.shareOfClass ? percent(row.shareOfClass, 1) : <NotEntered label="—" />}</td>
                <td className={TD}>{money(row.figures.potential, true)}</td>
                <td className={TD}>{money(row.figures.recovered)}</td>
                <td className={TD}>{money(row.figures.avoided)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </TableSection>
  );
}

function ClassItems({ data, query, selected }: { data: CostSummary; query: CostSummaryQuery; selected: CoqClass | null }) {
  const base = periodRecordQuery(data, query);
  const coqClass = query.coqClass ?? selected;
  const records = useCostRecords({ ...base, coqClass, category: coqClass === query.coqClass ? base.category : "" });
  const label = coqClass ? data.classes.find((item) => item.code === coqClass)?.label : null;
  const list = records.data;
  return (
    <TableSection
      id="coq-items"
      title={label ? `${label} items` : "Quality cost items"}
      description={`${periodLabel(data)}. ${
        list && list.total > list.records.length ? `Newest ${list.records.length} of ${recordsLabel(list.total)}. ` : ""
      }Select a row to open the item.`}
    >
      {records.isError ? (
        <CostError error={records.error} onRetry={() => void records.refetch()} />
      ) : !list ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">Loading…</p>
      ) : list.records.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">No items in this selection.</p>
      ) : (
        <RecordTable records={list.records} caption={label ? `${label} items` : "Quality cost items"} />
      )}
    </TableSection>
  );
}
