"use client";

import { CircleDollarSign, ClipboardList, Factory, MessageSquareWarning, Percent, Users } from "lucide-react";
import { useState } from "react";

import { BarChart } from "@/components/common/bar-chart";
import { MetricCard } from "@/components/common/metric-card";
import { PageHeader } from "@/components/common/page-header";
import { Tabs } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

import type { CostSummary } from "./api";
import {
  CostError,
  CostFilters,
  CostLineRegister,
  DataBar,
  DataChecks,
  Definitions,
  NoFigures,
  NotReported,
  TableSection,
  TD,
  TH,
  useCostSummary,
} from "./cost-shared";
import { CostEstimator } from "./estimator";
import { COQ_CLASS_COLORS, MONTH_LABELS, percent, periodLabel, quantity, reportedLabel, toNumber, usd } from "./format";

type View = "monthly" | "estimator";

export function CopqPage({ title, description }: { title: string; description?: string }) {
  const [view, setView] = useState<View>("monthly");
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Quality · Cost of Quality" title={title} description={description} />
      <Tabs
        label="Cost of Poor Quality views"
        items={[
          { value: "monthly", label: "Monthly COPQ" },
          { value: "estimator", label: "Incident estimator" },
        ]}
        value={view}
        onValueChange={setView}
      >
        {view === "monthly" ? <MonthlyCopq /> : <CostEstimator />}
      </Tabs>
    </div>
  );
}

function MonthlyCopq() {
  const state = useCostSummary();
  const { summary } = state;
  const data = summary.data;
  return (
    <div className="space-y-5 pt-4">
      <p className="max-w-4xl text-sm text-muted-foreground">
        Cost of Poor Quality = internal failure (scrap and off-spec losses before shipment) + external failure (customer
        complaint costs after shipment). Every figure is calculated from the monthly source values; a blank in the source
        is shown as not reported, never as $0.
      </p>
      <CostFilters state={state} />
      {summary.isError ? (
        <CostError summary={summary} />
      ) : data && data.year === null ? (
        <NoFigures />
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
          {data && <CostLineRegister data={data} />}
          {data && <DataChecks data={data} />}
          {data && <Definitions data={data} />}
        </>
      )}
    </div>
  );
}

function Kpis({ data, loading }: { data: CostSummary | undefined; loading: boolean }) {
  const period = data?.period;
  const label = data && period ? `${periodLabel(data.year, period)} · ${reportedLabel(period)}` : undefined;
  return (
    <section aria-label="Cost of Poor Quality" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <MetricCard
        label="Total COPQ"
        value={period?.copq ? usd(period.copq) : null}
        caption={label}
        icon={CircleDollarSign}
        emphasis
        loading={loading}
      />
      <MetricCard
        label="COPQ % of sales"
        value={period?.copqPctOfSales ? percent(period.copqPctOfSales) : null}
        caption={period ? `COPQ ÷ sales revenue of ${usd(period.salesRevenue)}` : undefined}
        detail={period?.copq && !period.copqPctOfSales ? "Sales revenue not reported." : null}
        icon={Percent}
        emphasis
        loading={loading}
      />
      <MetricCard
        label="Internal failure (production)"
        value={period?.internalFailure ? usd(period.internalFailure) : null}
        caption={
          period?.internalCostPerLb
            ? `${usd(period.internalCostPerLb, 4)} per lb produced (${quantity(period.totalProductionLbs)} lb)`
            : "Scrap and off-spec losses"
        }
        icon={Factory}
        emphasis
        loading={loading}
      />
      <MetricCard
        label="External failure (complaints)"
        value={period?.externalFailure ? usd(period.externalFailure) : null}
        caption={period?.externalPctOfSales ? `${percent(period.externalPctOfSales)} of sales` : "Customer complaint costs"}
        icon={MessageSquareWarning}
        loading={loading}
      />
      <MetricCard
        label="Customer complaints"
        value={period?.complaintCount ?? null}
        caption={period ? `Returned product: ${quantity(period.returnedProductLbs)} lb` : undefined}
        icon={Users}
        loading={loading}
      />
      <MetricCard
        label="Open items · Avg days open · Recovery"
        value={null}
        caption="Not tracked: the source records monthly costs, not individual quality events or recoveries."
        icon={ClipboardList}
        loading={loading}
      />
    </section>
  );
}

function Pareto({ data }: { data: CostSummary }) {
  const reported = data.elements.filter((element) => element.value !== null);
  const values = (cls: "internal_failure" | "external_failure") =>
    reported.map((element) => (element.coqClass === cls ? Math.round(toNumber(element.value)!) : null));
  return (
    <BarChart
      title="COPQ Pareto by cost line"
      description={`${periodLabel(data.year, data.period)}. Bars are dollars, largest first; the line is the cumulative share of COPQ.`}
      categories={reported.map((element) => element.label)}
      series={[
        { name: "Internal failure", values: values("internal_failure"), color: COQ_CLASS_COLORS.internal_failure, stack: "cost" },
        { name: "External failure", values: values("external_failure"), color: COQ_CLASS_COLORS.external_failure, stack: "cost" },
      ]}
      lines={[
        {
          name: "Cumulative %",
          values: reported.map((element) => {
            const share = toNumber(element.cumulativeShare);
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
    />
  );
}

function Trend({ data }: { data: CostSummary }) {
  const { fromMonth, throughMonth } = data.period;
  const months = data.months.filter(
    (month) => fromMonth !== null && throughMonth !== null && month.month >= fromMonth && month.month <= throughMonth,
  );
  const dollars = (value: string | null) => {
    const number = toNumber(value);
    return number === null ? null : Math.round(number);
  };
  return (
    <BarChart
      title="Monthly COPQ trend"
      description="Internal and external failure cost by month. A month without figures draws no bar."
      categories={months.map((month) => MONTH_LABELS[month.month - 1])}
      series={[
        {
          name: "Internal failure",
          values: months.map((month) => dollars(month.internalFailure)),
          color: COQ_CLASS_COLORS.internal_failure,
          stack: "copq",
        },
        {
          name: "External failure",
          values: months.map((month) => dollars(month.externalFailure)),
          color: COQ_CLASS_COLORS.external_failure,
          stack: "copq",
        },
      ]}
      height={300}
    />
  );
}

function MonthlyTable({ data }: { data: CostSummary }) {
  const { fromMonth, throughMonth } = data.period;
  const months = data.months.filter(
    (month) => fromMonth !== null && throughMonth !== null && month.month >= fromMonth && month.month <= throughMonth,
  );
  const max = Math.max(0, ...months.map((month) => toNumber(month.copq) ?? 0));
  const maxPct = Math.max(0, ...months.map((month) => toNumber(month.copqPctOfSales) ?? 0));
  const cell = (value: string | null, format: (v: string) => string) =>
    value === null ? <NotReported /> : format(value);
  return (
    <TableSection
      id="copq-monthly"
      title={`COPQ by month, ${data.year}`}
      description="Bars compare months within the period. Production cost is per pound produced; percentages are of sales revenue."
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1080px] text-left text-sm tabular-nums">
          <caption className="sr-only">COPQ by month</caption>
          <thead className="border-b">
            <tr>
              {[
                "Month",
                "Production (lb)",
                "Scrap (lb)",
                "Off-spec (lb)",
                "Internal failure",
                "Per lb produced",
                "Complaints",
                "External failure",
                "COPQ",
                "Sales revenue",
                "COPQ % of sales",
              ].map((heading) => (
                <th key={heading} scope="col" className={TH}>
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {months.map((month) => (
              <tr
                key={month.month}
                className={cn("border-b border-border/60 last:border-b-0", !month.reported && "text-muted-foreground")}
              >
                <th scope="row" className={cn(TD, "font-medium")}>
                  {MONTH_LABELS[month.month - 1]}
                </th>
                {month.reported ? (
                  <>
                    <td className={TD}>{cell(month.totalProductionLbs, (v) => quantity(v))}</td>
                    <td className={TD}>{cell(month.scrapProducedLbs, (v) => quantity(v))}</td>
                    <td className={TD}>{cell(month.offspecProducedLbs, (v) => quantity(v))}</td>
                    <td className={TD}>{cell(month.internalFailure, (v) => usd(v))}</td>
                    <td className={TD}>{cell(month.internalCostPerLb, (v) => usd(v, 4))}</td>
                    <td className={TD}>{month.complaintCount ?? <NotReported />}</td>
                    <td className={TD}>{cell(month.externalFailure, (v) => usd(v))}</td>
                    <td className={cn(TD, "font-semibold")}>
                      {month.copq === null ? (
                        <NotReported />
                      ) : (
                        <DataBar value={toNumber(month.copq)} max={max} color={COQ_CLASS_COLORS.external_failure}>
                          {usd(month.copq)}
                        </DataBar>
                      )}
                    </td>
                    <td className={TD}>{cell(month.salesRevenue, (v) => usd(v))}</td>
                    <td className={TD}>
                      {month.copqPctOfSales === null ? (
                        <NotReported />
                      ) : (
                        <DataBar value={toNumber(month.copqPctOfSales)} max={maxPct} color={COQ_CLASS_COLORS.internal_failure}>
                          {percent(month.copqPctOfSales)}
                        </DataBar>
                      )}
                    </td>
                  </>
                ) : (
                  <td className={TD} colSpan={10}>
                    No figures in the source for this month.
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {months.some((month) => month.note) && (
        <ul className="space-y-1 border-t px-4 py-3 text-xs text-muted-foreground">
          {months
            .filter((month) => month.note)
            .map((month) => (
              <li key={month.month}>
                <span className="font-medium text-foreground">{MONTH_LABELS[month.month - 1]}:</span> {month.note}
              </li>
            ))}
        </ul>
      )}
    </TableSection>
  );
}
