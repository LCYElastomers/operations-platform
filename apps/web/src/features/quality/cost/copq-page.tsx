"use client";

import { CircleDollarSign, ClipboardList, Factory, HandCoins, Percent, ShieldCheck, TriangleAlert, Wallet } from "lucide-react";
import { useState } from "react";

import { BarChart } from "@/components/common/bar-chart";
import { MetricCard } from "@/components/common/metric-card";
import { PageHeader } from "@/components/common/page-header";
import { Tabs } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

import { POOR_CLASSES, type CostSummary, type CostSummaryQuery } from "./api";
import {
  CostError,
  CostFilters,
  DataBar,
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
import { CostEstimator } from "./estimator";
import { COQ_CLASS_COLORS, MONTH_LABELS, percent, periodLabel, POTENTIAL_COLOR, quantity, recordsLabel, toNumber, usd } from "./format";
import { AddCostRecordButton } from "./record-dialog";
import { useCostRecords, useCostSummary } from "./use-cost";

type View = "dashboard" | "estimator";

export function CopqPage({ title, description }: { title: string; description?: string }) {
  const [view, setView] = useState<View>("dashboard");
  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Quality · Cost of Quality"
        title={title}
        description={description}
        actions={<AddCostRecordButton coqClass="internal_failure" />}
      />
      <Tabs
        label="Cost of Poor Quality views"
        items={[
          { value: "dashboard", label: "COPQ dashboard" },
          { value: "estimator", label: "Incident estimator" },
        ]}
        value={view}
        onValueChange={setView}
      >
        {view === "dashboard" ? <CopqDashboard /> : <CostEstimator />}
      </Tabs>
    </div>
  );
}

function CopqDashboard() {
  const [query, setQuery] = useCostSummaryQuery(true);
  const summary = useCostSummary(query);
  const data = summary.data;
  const filtered = isFiltered(query) || query.year !== null || query.from !== null || query.through !== null;
  return (
    <div className="space-y-5 pt-4">
      <p className="max-w-4xl text-sm text-muted-foreground">
        Cost of Poor Quality = Internal Failure + External Failure items in the Quality Cost Register. Confirmed cost is
        reported apart from potential exposure (items still Potential or Validating); the two are never added together.
      </p>
      <CostFilters
        query={query}
        onChange={setQuery}
        data={data}
        fetching={summary.isFetching && !summary.isPending}
        classes={POOR_CLASSES}
      />
      {summary.isError ? (
        <CostError error={summary.error} onRetry={() => void summary.refetch()} />
      ) : data && (data.year === null || data.copq.figures.count === 0) ? (
        <NoRecords
          filtered={filtered}
          action={filtered ? undefined : <AddCostRecordButton coqClass="internal_failure" />}
        />
      ) : (
        <>
          <Kpis data={data} loading={summary.isPending} />
          {data && (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <Pareto data={data} />
              <Trend data={data} />
            </div>
          )}
          {data && <MonthlyTable data={data} />}
          {data && (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
              <Aging data={data} />
              <CategoryTable data={data} />
            </div>
          )}
          {data && <OpenItems data={data} query={query} />}
          {data && <DataChecks data={data} />}
          {data && <Definitions data={data} />}
        </>
      )}
    </div>
  );
}

function Kpis({ data, loading }: { data: CostSummary | undefined; loading: boolean }) {
  const copq = data?.copq;
  const figures = copq?.figures;
  const label = data ? periodLabel(data) : undefined;
  return (
    <section aria-label="Cost of Poor Quality" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard
        label="Confirmed COPQ"
        value={figures?.confirmed ? usd(figures.confirmed) : null}
        caption={figures ? `${label} · ${recordsLabel(figures.confirmedCount)} confirmed` : undefined}
        detail={figures && figures.confirmed === null ? "No confirmed cost in this selection." : null}
        icon={CircleDollarSign}
        emphasis
        loading={loading}
      />
      <MetricCard
        label="Potential exposure"
        value={figures?.potential ? usd(figures.potential) : null}
        caption={figures ? `${recordsLabel(figures.potentialCount)} Potential or Validating; not in confirmed COPQ` : undefined}
        icon={TriangleAlert}
        emphasis
        loading={loading}
      />
      <MetricCard
        label="Net COPQ"
        value={figures?.net ? usd(figures.net) : null}
        caption="Confirmed COPQ less recovered cost"
        icon={Wallet}
        emphasis
        loading={loading}
      />
      <MetricCard
        label="COPQ % of sales"
        value={copq?.copqPctOfSales ? percent(copq.copqPctOfSales) : null}
        caption={copq?.salesRevenue ? `Confirmed COPQ ÷ sales revenue of ${usd(copq.salesRevenue)}` : "Sales revenue not reported"}
        icon={Percent}
        loading={loading}
      />
      <MetricCard
        label="Recovered"
        value={figures?.recovered ? usd(figures.recovered) : null}
        caption="From customers, suppliers or insurance (confirmed items)"
        icon={HandCoins}
        loading={loading}
      />
      <MetricCard
        label="Avoided"
        value={figures?.avoided ? usd(figures.avoided) : null}
        caption="Reported separately; not deducted from COPQ"
        icon={ShieldCheck}
        loading={loading}
      />
      <MetricCard
        label="Internal failure per lb"
        value={copq?.internalCostPerLb ? usd(copq.internalCostPerLb, 4) : null}
        caption={copq?.productionLbs ? `Per lb produced (${quantity(copq.productionLbs)} lb)` : "Production not reported"}
        icon={Factory}
        loading={loading}
      />
      <MetricCard
        label="Open items"
        value={copq ? copq.openCount : null}
        caption={copq ? `${copq.overdueCount} overdue` : undefined}
        icon={ClipboardList}
        loading={loading}
      />
    </section>
  );
}

function dollars(value: string | null) {
  const number = toNumber(value);
  return number === null ? null : Math.round(number);
}

function Pareto({ data }: { data: CostSummary }) {
  const rows = data.categories.filter((category) => POOR_CLASSES.includes(category.coqClass));
  const confirmed = (cls: (typeof POOR_CLASSES)[number]) =>
    rows.map((row) => (row.coqClass === cls ? dollars(row.figures.confirmed) : null));
  return (
    <BarChart
      title="COPQ Pareto by category"
      description={`${periodLabel(data)}. Confirmed cost, largest first; the line is the cumulative share of confirmed COPQ. Potential exposure is drawn beside it, not added.`}
      categories={rows.map((row) => row.label)}
      series={[
        { name: "Internal failure", values: confirmed("internal_failure"), color: COQ_CLASS_COLORS.internal_failure, stack: "confirmed" },
        { name: "External failure", values: confirmed("external_failure"), color: COQ_CLASS_COLORS.external_failure, stack: "confirmed" },
        { name: "Potential exposure", values: rows.map((row) => dollars(row.figures.potential)), color: POTENTIAL_COLOR, stack: "potential" },
      ]}
      lines={[
        {
          name: "Cumulative %",
          values: rows.map((row) => {
            const share = toNumber(row.cumulativeShareOfPoor);
            return share === null ? null : Math.round(share * 1000) / 10;
          }),
          color: "#334155",
          axis: "right",
        },
      ]}
      rightAxisName="Cumulative"
      rightAxisPercent
      labelRotate={30}
      height={300}
      emptyState={<p className="text-sm text-muted-foreground">No categories with cost in this selection.</p>}
    />
  );
}

function periodMonths(data: CostSummary) {
  return data.months.filter((month) => month.month >= data.fromMonth && month.month <= data.throughMonth);
}

function Trend({ data }: { data: CostSummary }) {
  const months = periodMonths(data);
  return (
    <BarChart
      title="Monthly COPQ trend"
      description="Confirmed internal and external failure cost by month; the dashed line is potential exposure. A month without items draws no bar."
      categories={months.map((month) => MONTH_LABELS[month.month - 1])}
      series={[
        {
          name: "Internal failure",
          values: months.map((month) => dollars(month.confirmed.internal_failure)),
          color: COQ_CLASS_COLORS.internal_failure,
          stack: "copq",
        },
        {
          name: "External failure",
          values: months.map((month) => dollars(month.confirmed.external_failure)),
          color: COQ_CLASS_COLORS.external_failure,
          stack: "copq",
        },
      ]}
      lines={[{ name: "Potential exposure", values: months.map((month) => dollars(month.poorPotential)), color: POTENTIAL_COLOR, dashed: true }]}
      height={300}
    />
  );
}

function MonthlyTable({ data }: { data: CostSummary }) {
  const months = periodMonths(data);
  const max = Math.max(0, ...months.map((month) => toNumber(month.poor) ?? 0));
  const money = (value: string | null) => (value === null ? <NotEntered label="—" /> : usd(value));
  return (
    <TableSection
      id="copq-monthly"
      title={`COPQ by month, ${data.year}`}
      description="Confirmed cost by month; potential exposure is listed separately. Percentages are of reported sales revenue."
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[960px] text-left text-sm tabular-nums">
          <caption className="sr-only">COPQ by month</caption>
          <thead className="border-b">
            <tr>
              {["Month", "Items", "Internal failure", "External failure", "Confirmed COPQ", "Net COPQ", "Potential exposure", "Sales revenue", "COPQ % of sales"].map(
                (heading) => (
                  <th key={heading} scope="col" className={TH}>
                    {heading}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {months.map((month) => (
              <tr key={month.month} className={cn("border-b border-border/60 last:border-b-0", month.recordCount === 0 && "text-muted-foreground")}>
                <th scope="row" className={cn(TD, "font-medium")}>
                  {MONTH_LABELS[month.month - 1]}
                </th>
                <td className={TD}>{month.recordCount}</td>
                <td className={TD}>{money(month.confirmed.internal_failure)}</td>
                <td className={TD}>{money(month.confirmed.external_failure)}</td>
                <td className={cn(TD, "font-semibold")}>
                  {month.poor === null ? (
                    <NotEntered label="—" />
                  ) : (
                    <DataBar value={toNumber(month.poor)} max={max} color={COQ_CLASS_COLORS.external_failure}>
                      {usd(month.poor)}
                    </DataBar>
                  )}
                </td>
                <td className={TD}>{money(month.netPoor)}</td>
                <td className={cn(TD, "italic")}>{money(month.poorPotential)}</td>
                <td className={TD}>{money(month.salesRevenue)}</td>
                <td className={TD}>{month.copqPctOfSales === null ? <NotEntered label="—" /> : percent(month.copqPctOfSales)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </TableSection>
  );
}

function Aging({ data }: { data: CostSummary }) {
  const total = data.aging.reduce((sum, bucket) => sum + bucket.count, 0);
  const max = Math.max(0, ...data.aging.map((bucket) => bucket.count));
  return (
    <TableSection id="copq-aging" title="Open item aging" description="Open failure items by days since the item date.">
      {total === 0 ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">No open items in this selection.</p>
      ) : (
        <table className="w-full text-left text-sm tabular-nums">
          <caption className="sr-only">Open item aging</caption>
          <thead className="border-b">
            <tr>
              {["Days open", "Items", "Cost or exposure"].map((heading) => (
                <th key={heading} scope="col" className={TH}>
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.aging.map((bucket) => (
              <tr key={bucket.label} className="border-b border-border/60 last:border-b-0">
                <th scope="row" className={cn(TD, "font-medium whitespace-nowrap")}>
                  {bucket.label}
                </th>
                <td className={TD}>
                  <DataBar value={bucket.count} max={max} color={COQ_CLASS_COLORS.internal_failure}>
                    {bucket.count}
                  </DataBar>
                </td>
                <td className={TD}>{bucket.exposure === null ? <NotEntered label="—" /> : usd(bucket.exposure)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </TableSection>
  );
}

function CategoryTable({ data }: { data: CostSummary }) {
  const rows = data.categories.filter((category) => POOR_CLASSES.includes(category.coqClass));
  return (
    <TableSection id="copq-categories" title="COPQ by category" description="Confirmed cost and potential exposure kept apart.">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm tabular-nums">
          <caption className="sr-only">COPQ by category</caption>
          <thead className="border-b">
            <tr>
              {["Category", "Class", "Items", "Confirmed", "Potential exposure", "Recovered", "Net"].map((heading) => (
                <th key={heading} scope="col" className={TH}>
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.code} className="border-b border-border/60 last:border-b-0">
                <th scope="row" className={cn(TD, "font-medium")}>
                  {row.label}
                </th>
                <td className={cn(TD, "whitespace-nowrap")}>
                  {data.classes.find((item) => item.code === row.coqClass)?.label ?? row.coqClass}
                </td>
                <td className={TD}>{row.figures.count}</td>
                <td className={TD}>{row.figures.confirmed === null ? <NotEntered label="—" /> : usd(row.figures.confirmed)}</td>
                <td className={cn(TD, "italic")}>{row.figures.potential === null ? <NotEntered label="—" /> : usd(row.figures.potential)}</td>
                <td className={TD}>{row.figures.recovered === null ? <NotEntered label="—" /> : usd(row.figures.recovered)}</td>
                <td className={TD}>{row.figures.net === null ? <NotEntered label="—" /> : usd(row.figures.net)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </TableSection>
  );
}

function OpenItems({ data, query }: { data: CostSummary; query: CostSummaryQuery }) {
  const records = useCostRecords({ ...periodRecordQuery(data, query, POOR_CLASSES), open: true });
  const list = records.data;
  return (
    <TableSection
      id="copq-open"
      title="Open failure items"
      description={`${periodLabel(data)}. Items not yet Closed, newest first. Select a row to open the item.`}
    >
      {records.isError ? (
        <CostError error={records.error} onRetry={() => void records.refetch()} />
      ) : !list ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">Loading…</p>
      ) : list.records.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">No open failure items in this selection.</p>
      ) : (
        <RecordTable records={list.records} caption="Open failure items" />
      )}
    </TableSection>
  );
}
