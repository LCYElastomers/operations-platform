"use client";

import {
  AlertTriangle,
  ChartColumn,
  Droplet,
  Forklift,
  OctagonAlert,
  Siren,
  TableProperties,
  TriangleAlert,
  Users,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { BarChart, type BarSeries } from "@/components/common/bar-chart";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar, FilterSelect } from "@/components/common/filter-bar";
import { HeatmapTable } from "@/components/common/heatmap-table";
import { MetricCard } from "@/components/common/metric-card";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Tabs } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api-client";

import {
  bars,
  breakdownChart,
  classificationChart,
  COLORS,
  combinedKpiCaption,
  DASHBOARD_VIEWS,
  findKpi,
  formatCount,
  incompleteSeries,
  KPI_LABELS,
  kpiCaption,
  latestStartedMonth,
  monthLabels,
  monthList,
  NOTES,
  periodLabel,
  PIT_TITLE,
  PRIOR_YEAR_COLOR,
  priorYearCaption,
  reconciliationStatus,
  reconciliationSummary,
  totalLabel,
  type DashboardView,
} from "./analytics-data";
import {
  describeSafetyError,
  type AnalyticsBreakdown,
  type AnalyticsCategory,
  type AnalyticsKpi,
  type AnalyticsSeries,
  type IncidentAnalyticsResponse,
  type MonthReconciliation,
} from "./api";
import { monthOf, yearOf } from "../site-calendar";
import { useAutomaticValue, useSiteToday } from "../use-site-calendar";
import { defaultReportingYear, FIRST_REPORTING_YEAR, MONTH_LABELS } from "./grid";
import { ReportingYearSelect } from "./reporting-year-select";
import { useIncidentAnalytics } from "./use-incident-metrics";

const KPI_ICONS: Record<AnalyticsKpi["key"], React.ComponentType<{ className?: string }>> = {
  incidents: Siren,
  near_misses: TriangleAlert,
  lopc: Droplet,
  psif: OctagonAlert,
  pit: Forklift,
  combined_damage: Wrench,
};
const KPI_KEYS = Object.keys(KPI_ICONS) as AnalyticsKpi["key"][];

const CHART_HEIGHT = 300;
// Categorical colors for the LOPC contributing factors, in display order.
const FACTOR_COLORS = ["#7c3aed", "#0d9488", "#64748b"];
const CUMULATIVE_COLOR = "#0f172a";

type IncidentDashboardProps = {
  title: string;
  description?: string;
  /** The Baytown date when the page was rendered on the server. */
  siteToday: string;
  /** From `?view=`; Overview when missing or unknown. */
  initialView?: DashboardView;
};

type ChartDefaults = {
  height: number;
  showValues: boolean;
  loading: boolean;
  emptyState: React.ReactNode;
};

type ViewProps = {
  data: IncidentAnalyticsResponse | undefined;
  isError: boolean;
  year: number;
  period: string;
  months: string[];
  chart: ChartDefaults;
};

/** The Incident & Near Miss Dashboard, backed by the read-only Incident Analytics API. */
export function IncidentDashboard({
  title,
  description,
  siteToday,
  initialView = "overview",
}: IncidentDashboardProps) {
  const today = useSiteToday(siteToday);
  const currentYear = yearOf(today);
  const yearChoice = useAutomaticValue(defaultReportingYear(currentYear));
  const year = yearChoice.value;
  const latest = latestStartedMonth(year, { year: currentYear, month: monthOf(today) });
  // Follows the latest started month until the user picks one; a pick never
  // runs past the latest started month.
  const throughChoice = useAutomaticValue<number | null>(latest);
  const through =
    throughChoice.isAutomatic || latest === null || throughChoice.value === null
      ? latest
      : Math.min(throughChoice.value, latest);
  const [view, setView] = useState<DashboardView>(initialView);
  // One request serves every tab; switching tabs keeps the year and month.
  const analytics = useIncidentAnalytics(year, throughChoice.isAutomatic ? null : through);
  const data = analytics.data;
  const loading = analytics.isPending && !analytics.isError;
  const shownThrough = data?.throughMonth ?? null;
  const period = shownThrough === null ? String(year) : periodLabel(year, shownThrough);
  const months = monthLabels(shownThrough);
  const nothingReported = data !== undefined && data.kpis.every((kpi) => kpi.value === null);

  const changeView = (next: DashboardView) => {
    setView(next);
    const url = new URL(window.location.href);
    url.searchParams.set("view", next);
    window.history.replaceState(window.history.state, "", url);
  };

  const accessDenied =
    analytics.error instanceof ApiError && (analytics.error.status === 401 || analytics.error.status === 403);

  const errorState = (
    <EmptyState
      variant="plain"
      icon={AlertTriangle}
      title={accessDenied ? "Safety data is not available to you" : "Could not load Safety data"}
      description={describeSafetyError(analytics.error)}
      action={
        accessDenied ? undefined : (
          <Button variant="outline" size="sm" onClick={() => void analytics.refetch()}>
            Retry
          </Button>
        )
      }
    />
  );
  const emptyState = analytics.isError ? (
    errorState
  ) : (
    <EmptyState
      variant="plain"
      icon={ChartColumn}
      title="Not reported"
      className="py-0"
      description={shownThrough === null ? `${year} has not started.` : `Nothing has been reported for ${period}.`}
    />
  );
  const viewProps: ViewProps = {
    data,
    isError: analytics.isError,
    year,
    period,
    months,
    chart: { height: CHART_HEIGHT, showValues: true, loading, emptyState },
  };

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Safety · Incident & Near Miss"
        title={title}
        description={description}
        actions={
          <Link href="/safety/incidents/data-entry" className={buttonVariants({ variant: "outline" })}>
            <TableProperties />
            Open data entry
          </Link>
        }
      />
      <p className="-mt-2 max-w-4xl text-sm text-muted-foreground">
        Counts calculated from the monthly values entered in Incident & Near Miss. A month with no entry is
        shown as not reported, never as zero. No targets, ratings or scores are applied.
      </p>

      <FilterBar
        actions={
          analytics.isFetching && !analytics.isPending ? (
            <StatusBadge tone="pending" pulse>
              Updating
            </StatusBadge>
          ) : undefined
        }
      >
        <div className="w-full sm:w-44">
          <ReportingYearSelect
            year={year}
            onChange={(value) => {
              yearChoice.choose(value);
              throughChoice.follow();
            }}
            currentYear={currentYear}
            firstYear={FIRST_REPORTING_YEAR}
            yearsWithData={data?.availableYears}
          />
        </div>
        <div className="w-full sm:w-44">
          <FilterSelect
            label="Through month"
            placeholder={false}
            options={MONTH_LABELS.slice(0, latest ?? 0).map((label, index) => ({
              value: String(index + 1),
              label,
            }))}
            value={through === null ? "" : String(through)}
            onChange={(event) => throughChoice.choose(Number(event.target.value))}
            disabled={latest === null}
            className="pointer-coarse:h-11"
          />
        </div>
      </FilterBar>

      {nothingReported && (
        <p role="status" className="rounded-lg border border-dashed bg-card px-4 py-3 text-sm text-muted-foreground">
          {shownThrough === null
            ? `${year} has not started.`
            : `No months have been reported for ${period}. Values appear here as they are entered in Incident & Near Miss Data Entry.`}
        </p>
      )}

      <Tabs label="Dashboard views" items={[...DASHBOARD_VIEWS]} value={view} onValueChange={changeView}>
        {view === "overview" && (
          <OverviewView {...viewProps} loading={loading} kpiUnavailable={analytics.isError} />
        )}
        {view === "area" && <AreaView {...viewProps} />}
        {view === "incident-analysis" && <IncidentAnalysisView {...viewProps} />}
        {view === "behavior" && <BehaviorView year={year} />}
      </Tabs>

      {loading && <span className="sr-only">Loading Safety data</span>}
    </div>
  );
}

// Overview ----------------------------------------------------------------------------

function OverviewView({
  data,
  isError,
  year,
  period,
  months,
  chart,
  loading,
  kpiUnavailable,
}: ViewProps & { loading: boolean; kpiUnavailable: boolean }) {
  return (
    <div className="space-y-5">
      <section aria-label="Year to date" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {KPI_KEYS.map((key) => {
          const kpi = findKpi(data, key);
          const caption = key === "combined_damage" ? combinedKpiCaption : kpiCaption;
          return (
            <MetricCard
              key={key}
              label={KPI_LABELS[key]}
              value={kpi?.value ?? null}
              caption={kpiUnavailable ? "Unavailable" : kpi ? caption(kpi, year) : undefined}
              detail={priorYearCaption(kpi)}
              icon={KPI_ICONS[key]}
              emphasis
              loading={loading}
            />
          );
        })}
      </section>
      <p className="-mt-2 px-1 text-xs text-muted-foreground">{NOTES.psifDefinition}</p>

      <section aria-label="Charts" className="grid grid-cols-1 gap-5 min-[1440px]:grid-cols-2">
        <BarChart
          title="Incidents vs Near Misses by Month"
          description={`Reported monthly counts, ${period}. No bar means the month was not reported; 0 is a reported zero.`}
          categories={months}
          series={
            isError
              ? []
              : [
                  bars(data?.incidents, "Incidents", COLORS.incidents),
                  bars(data?.nearMisses, "Near Misses", COLORS.nearMisses),
                ]
          }
          footer={
            data && (
              <MonthlyTable
                caption={`Incidents and Near Misses by month, ${period}`}
                months={months}
                columns={[
                  ["Incidents", data.incidents],
                  ["Near Misses", data.nearMisses],
                ]}
              />
            )
          }
          {...chart}
        />
        <PriorYearChart
          measure="Incidents"
          year={year}
          months={months}
          current={data?.incidents}
          prior={data?.incidentsPriorYearMonthly}
          available={data?.incidentsPriorYearAvailable ?? false}
          isError={isError}
          chart={chart}
        />
        <BarChart
          title="Incident Classification"
          description={`Count per classification, ${period}. ${NOTES.classification}`}
          {...classificationChartProps(data, isError)}
          orientation="horizontal"
          footer={data && <ClassificationTable caption={`Incident Classification, ${period}`} rows={data.classifications} />}
          {...chart}
          height={420}
        />
        <BarChart
          title="PSIF by Month"
          description={`Monthly counts, ${period}. ${NOTES.psif}`}
          categories={months}
          series={isError ? [] : [bars(data?.psif, "PSIF", COLORS.psif)]}
          footer={data && <MonthlyTable caption={`PSIF by month, ${period}`} months={months} columns={[["PSIF", data.psif]]} />}
          {...chart}
        />
      </section>

      {data && (
        <section aria-label="Methodology and data completeness" className="rounded-lg border bg-card px-4 py-3 text-sm">
          <h2 className="font-semibold">Methodology and data completeness</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
            <li>{NOTES.unreported}</li>
            <li>{NOTES.classification}</li>
            <li>{NOTES.damage}</li>
            <li>{NOTES.lopc}</li>
            <li>{NOTES.pit}</li>
            <li>{NOTES.psifDefinition}</li>
            <li>{NOTES.priorYear}</li>
            <li>{NOTES.area}</li>
            <li>{NOTES.tags}</li>
          </ul>
          <Completeness data={data} period={period} />
        </section>
      )}
    </div>
  );
}

/** Prior year in neutral grey beside the selected year; both years in the title. */
function PriorYearChart({
  measure,
  year,
  months,
  current,
  prior,
  available,
  isError,
  chart,
}: {
  measure: string;
  year: number;
  months: string[];
  current: AnalyticsSeries | undefined;
  prior: AnalyticsSeries | undefined;
  available: boolean;
  isError: boolean;
  chart: ChartDefaults;
}) {
  const priorYear = year - 1;
  const color = measure === "LOPC" ? COLORS.lopc : COLORS.incidents;
  const series: BarSeries[] =
    isError || !available
      ? []
      : [bars(prior, String(priorYear), PRIOR_YEAR_COLOR), bars(current, String(year), color)];
  return (
    <BarChart
      title={`${measure} vs Prior Year by Month (${year} vs ${priorYear})`}
      description={`${measure} per month, ${year} and the same months of ${priorYear}. ${NOTES.priorYear}`}
      categories={months}
      series={series}
      footer={
        current &&
        prior &&
        available && (
          <MonthlyTable
            caption={`${measure} by month, ${year} and ${priorYear}`}
            months={months}
            columns={[
              [String(priorYear), prior],
              [String(year), current],
            ]}
          />
        )
      }
      {...chart}
      emptyState={
        isError || available ? (
          chart.emptyState
        ) : (
          <EmptyState
            variant="plain"
            icon={ChartColumn}
            title="No prior-year values"
            className="py-0"
            description={`No ${measure} values are recorded for ${priorYear}, so there is nothing to compare.`}
          />
        )
      }
    />
  );
}

// Area --------------------------------------------------------------------------------

function AreaView({ data, isError, period, months, chart }: ViewProps) {
  const incidents = breakdownChart(data?.incidentsByArea ?? [], "Incidents", COLORS.incidents);
  const nearMisses = breakdownChart(data?.nearMissesByArea ?? [], "Near Misses", COLORS.nearMisses);
  return (
    <div className="space-y-5">
      <p className="px-1 text-sm text-muted-foreground">{NOTES.area}</p>
      <section aria-label="Totals by area" className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <BarChart
          title="Incidents by Area"
          description={`Areas with at least one reported month, ${period}. Highest first.`}
          categories={incidents.categories}
          series={isError ? [] : incidents.series}
          orientation="horizontal"
          footer={data && <BreakdownTable caption={`Incidents by Area, ${period}`} label="Area" rows={data.incidentsByArea} />}
          {...chart}
          height={incidents.height}
        />
        <BarChart
          title="Near Misses by Area"
          description={`Areas with at least one reported month, ${period}. Highest first.`}
          categories={nearMisses.categories}
          series={isError ? [] : nearMisses.series}
          orientation="horizontal"
          footer={
            data && <BreakdownTable caption={`Near Misses by Area, ${period}`} label="Area" rows={data.nearMissesByArea} />
          }
          {...chart}
          height={nearMisses.height}
        />
      </section>
      {data && !isError && (
        <>
          <AreaGrid
            title="Incidents by Area and Month"
            period={period}
            months={months}
            rows={data.incidentAreaMonthly}
            reconciliation={data.areaReconciliation.incidents}
            authoritative="Incidents"
            rgb="37 99 235"
          />
          <AreaGrid
            title="Near Misses by Area and Month"
            period={period}
            months={months}
            rows={data.nearMissAreaMonthly}
            reconciliation={data.areaReconciliation.nearMisses}
            authoritative="Near Misses"
            rgb="13 148 136"
          />
        </>
      )}
    </div>
  );
}

function AreaGrid({
  title,
  period,
  months,
  rows,
  reconciliation,
  authoritative,
  rgb,
}: {
  title: string;
  period: string;
  months: string[];
  rows: AnalyticsCategory[];
  reconciliation: MonthReconciliation[];
  authoritative: string;
  rgb: string;
}) {
  const columnTotals = reconciliation.map((month) => month.dimensionTotal);
  const reported = columnTotals.filter((value): value is number => value !== null);
  return (
    <section aria-label={title} className="rounded-lg border bg-card">
      <header className="border-b px-4 py-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {period}. – is not reported; 0 is a reported zero. {reconciliationSummary(reconciliation, authoritative)}
        </p>
      </header>
      {months.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">No months to show.</p>
      ) : (
        <HeatmapTable
          caption={`${title}, ${period}`}
          rowHeader="Area"
          columns={months}
          rows={rows.map((row) => ({
            id: row.code,
            label: row.name,
            description: row.description,
            values: row.values,
            total: row.total,
          }))}
          columnTotals={columnTotals}
          total={reported.length ? reported.reduce((a, b) => a + b, 0) : null}
          statusLabel={`vs ${authoritative}`}
          statuses={reconciliation.map((month) => reconciliationStatus(month, "areas", authoritative))}
          rgb={rgb}
        />
      )}
    </section>
  );
}

// Incident Analysis ---------------------------------------------------------------------

function AnalysisGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="space-y-3">
      <h2 className="px-1 text-base font-semibold">{title}</h2>
      <div className="grid grid-cols-1 gap-5 min-[1440px]:grid-cols-2">{children}</div>
    </section>
  );
}

function IncidentAnalysisView({ data, isError, year, period, months, chart }: ViewProps) {
  return (
    <div className="space-y-8">
      <AnalysisGroup title="Containment">
        <BarChart
          title="LOPC by Month"
          description={`Loss of Primary Containment (LOPC) counts, ${period}. ${NOTES.lopc}`}
          categories={months}
          series={isError ? [] : [bars(data?.lopc, "LOPC", COLORS.lopc)]}
          footer={
            data && <MonthlyTable caption={`LOPC by month, ${period}`} months={months} columns={[["LOPC", data.lopc]]} />
          }
          {...chart}
        />
        <PriorYearChart
          measure="LOPC"
          year={year}
          months={months}
          current={data?.lopc}
          prior={data?.lopcPriorYearMonthly}
          available={data?.lopcPriorYearAvailable ?? false}
          isError={isError}
          chart={chart}
        />
        <LopcFactorChart data={data} isError={isError} period={period} months={months} chart={chart} />
      </AnalysisGroup>

      <AnalysisGroup title="Damage & vehicles">
        <BarChart
          title="Property vs Equipment Damage by Month"
          description={
            data
              ? `${totalLabel(data.propertyDamage)}; ${totalLabel(data.equipmentDamage)}; combined ${formatCount(data.combinedDamage.total)}. ${NOTES.damage}`
              : NOTES.damage
          }
          categories={months}
          series={
            isError
              ? []
              : [
                  bars(data?.propertyDamage, data?.propertyDamage.name ?? "Property Damage", COLORS.propertyDamage),
                  bars(data?.equipmentDamage, data?.equipmentDamage.name ?? "Equipment Damage", COLORS.equipmentDamage),
                ]
          }
          footer={
            data && (
              <MonthlyTable
                caption={`Property and Equipment Damage by month, ${period}`}
                months={months}
                columns={[
                  [data.propertyDamage.name, data.propertyDamage],
                  [data.equipmentDamage.name, data.equipmentDamage],
                  ["Combined damage", data.combinedDamage],
                ]}
              />
            )
          }
          {...chart}
        />
        <BarChart
          title={PIT_TITLE}
          description={`Monthly counts, ${period}. ${NOTES.pit}`}
          categories={months}
          series={isError ? [] : [bars(data?.pit, "PIT incidents", COLORS.pit)]}
          footer={
            data && (
              <MonthlyTable caption={`${PIT_TITLE} by month, ${period}`} months={months} columns={[["PIT incidents", data.pit]]} />
            )
          }
          {...chart}
        />
      </AnalysisGroup>

      <AnalysisGroup title="Injuries">
        <TagChart
          title="Injury Cause"
          breakdown={data?.injuryCause}
          reconciliation={data?.injuryReconciliation.injuryCause}
          authoritative="First Aid + Recordable"
          note={NOTES.injuries}
          color="#dc2626"
          isError={isError}
          period={period}
          chart={chart}
        />
        <TagChart
          title="Body Part"
          breakdown={data?.bodyPart}
          reconciliation={data?.injuryReconciliation.bodyPart}
          authoritative="First Aid + Recordable"
          note={NOTES.injuries}
          color="#db2777"
          isError={isError}
          period={period}
          chart={chart}
        />
      </AnalysisGroup>

      <AnalysisGroup title="Near misses">
        <TagChart
          title="Near-Miss Potential"
          breakdown={data?.nearMissPotential}
          note={NOTES.tags}
          color={COLORS.nearMisses}
          isError={isError}
          period={period}
          chart={chart}
        />
        <TagChart
          title="Near-Miss Cause"
          breakdown={data?.nearMissCause}
          note={NOTES.tags}
          color="#0891b2"
          isError={isError}
          period={period}
          chart={chart}
        />
      </AnalysisGroup>
    </div>
  );
}

/**
 * Stacked monthly factor counts with the cumulative total on a second axis.
 * Per-factor cumulative values are in the data table; three cumulative lines
 * on one small chart would not be legible.
 */
function LopcFactorChart({
  data,
  isError,
  period,
  months,
  chart,
}: Omit<ViewProps, "year">) {
  const factors = data?.lopcContributingFactors;
  const reconciliation = data?.lopcFactorReconciliation ?? [];
  return (
    <BarChart
      title="LOPC Contributing Factors"
      description={`Monthly factor counts stacked, with the cumulative total, ${period}. ${NOTES.lopcFactor} ${reconciliationSummary(reconciliation, "LOPC")}`}
      categories={months}
      series={
        isError || !factors
          ? []
          : factors.breakdown.rows.map((row, index) => ({
              name: row.name,
              values: row.values,
              color: FACTOR_COLORS[index % FACTOR_COLORS.length],
              stack: "factors",
            }))
      }
      lines={
        isError || !factors
          ? []
          : [{ name: "Cumulative total", values: factors.cumulativeTotal, color: CUMULATIVE_COLOR, axis: "right" }]
      }
      rightAxisName="Cumulative"
      footer={
        data &&
        factors && (
          <DataTable caption={`LOPC contributing factors by month, ${period}`}>
            <thead>
              <tr className="border-b">
                <th scope="col" className="py-1 pr-4 font-medium">
                  Month
                </th>
                {factors.breakdown.rows.map((row) => (
                  <th key={row.code} scope="col" className="py-1 pr-4 font-medium">
                    {row.name}
                  </th>
                ))}
                <th scope="col" className="py-1 pr-4 font-medium">
                  Factors
                </th>
                <th scope="col" className="py-1 pr-4 font-medium">
                  LOPC
                </th>
                <th scope="col" className="py-1 pr-4 font-medium">
                  Check
                </th>
                {factors.cumulative.map((row) => (
                  <th key={row.code} scope="col" className="py-1 pr-4 font-medium">
                    {row.name} (cumulative)
                  </th>
                ))}
                <th scope="col" className="py-1 pr-4 font-medium">
                  Cumulative total
                </th>
              </tr>
            </thead>
            <tbody>
              {months.map((month, index) => {
                const check = reconciliation[index] && reconciliationStatus(reconciliation[index], "factors", "LOPC");
                return (
                  <tr key={month} className="border-b border-border/50">
                    <th scope="row" className="py-1 pr-4 font-normal">
                      {month}
                    </th>
                    {factors.breakdown.rows.map((row) => (
                      <td key={row.code} className="py-1 pr-4">
                        {formatCount(row.values[index] ?? null)}
                      </td>
                    ))}
                    <td className="py-1 pr-4">{formatCount(factors.breakdown.monthlyTotals[index] ?? null)}</td>
                    <td className="py-1 pr-4">{formatCount(data.lopc.values[index] ?? null)}</td>
                    <td className="py-1 pr-4" title={check?.description}>
                      {check && (
                        <>
                          <span aria-hidden>{check.text}</span>
                          <span className="sr-only">{check.description}</span>
                        </>
                      )}
                    </td>
                    {factors.cumulative.map((row) => (
                      <td key={row.code} className="py-1 pr-4">
                        {formatCount(row.values[index] ?? null)}
                      </td>
                    ))}
                    <td className="py-1 pr-4">{formatCount(factors.cumulativeTotal[index] ?? null)}</td>
                  </tr>
                );
              })}
            </tbody>
          </DataTable>
        )
      }
      {...chart}
    />
  );
}

/** Reported categories of a breakdown as sorted horizontal bars, with an optional reconciliation. */
function TagChart({
  title,
  breakdown,
  reconciliation,
  authoritative,
  note,
  color,
  isError,
  period,
  chart,
}: {
  title: string;
  breakdown: AnalyticsBreakdown | undefined;
  reconciliation?: MonthReconciliation[];
  authoritative?: string;
  note: string;
  color: string;
  isError: boolean;
  period: string;
  chart: ChartDefaults;
}) {
  const shown = breakdownChart(breakdown?.categories ?? [], title, color);
  const check = reconciliation && authoritative ? ` ${reconciliationSummary(reconciliation, authoritative)}` : "";
  return (
    <BarChart
      title={title}
      description={`Count per category, ${period}. ${note}${check}`}
      categories={shown.categories}
      series={isError ? [] : shown.series}
      orientation="horizontal"
      footer={
        breakdown && (
          <BreakdownTable
            caption={`${title}, ${period}`}
            label="Category"
            rows={breakdown.categories.filter((row) => row.total !== null)}
          />
        )
      }
      {...chart}
      height={shown.height}
    />
  );
}

// Behavior ----------------------------------------------------------------------------

function BehaviorView({ year }: { year: number }) {
  return (
    <EmptyState
      icon={Users}
      title={`No behavior data recorded for ${year}.`}
      description="Behavior data has no approved source on the platform yet, so nothing is shown here."
    />
  );
}

// Tables ------------------------------------------------------------------------------

function classificationChartProps(data: IncidentAnalyticsResponse | undefined, isError: boolean) {
  const { categories, series } = classificationChart(data);
  return { categories, series: isError ? [] : series };
}

function Completeness({ data, period }: { data: IncidentAnalyticsResponse; period: string }) {
  if (data.throughMonth === null) return null;
  const incomplete = incompleteSeries(data);
  if (incomplete.length === 0) {
    return <p className="mt-2 text-muted-foreground">Every month of {period} is reported for every series shown.</p>;
  }
  return (
    <>
      <p className="mt-3 font-medium">Not reported in {period}</p>
      <ul className="mt-1 space-y-0.5 text-muted-foreground">
        {incomplete.map(({ label, months }) => (
          <li key={label}>
            {label}: {monthList(months)}
          </li>
        ))}
      </ul>
    </>
  );
}

function DataTable({ caption, children }: { caption: string; children: React.ReactNode }) {
  return (
    <details className="text-xs">
      <summary className="cursor-pointer py-1 font-medium text-muted-foreground">Data table</summary>
      <div className="overflow-x-auto pb-1">
        <table className="mt-1 w-full text-left tabular-nums">
          <caption className="sr-only">{caption}</caption>
          {children}
        </table>
      </div>
    </details>
  );
}

function MonthlyTable({
  caption,
  months,
  columns,
}: {
  caption: string;
  months: string[];
  columns: [string, AnalyticsSeries][];
}) {
  return (
    <DataTable caption={caption}>
      <thead>
        <tr className="border-b">
          <th scope="col" className="py-1 pr-4 font-medium">
            Month
          </th>
          {columns.map(([name]) => (
            <th key={name} scope="col" className="py-1 pr-4 font-medium">
              {name}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {months.map((month, index) => (
          <tr key={month} className="border-b border-border/50">
            <th scope="row" className="py-1 pr-4 font-normal">
              {month}
            </th>
            {columns.map(([name, series]) => (
              <td key={name} className="py-1 pr-4">
                {formatCount(series.values[index] ?? null)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          <th scope="row" className="py-1 pr-4 font-medium">
            YTD
          </th>
          {columns.map(([name, series]) => (
            <td key={name} className="py-1 pr-4 font-medium">
              {formatCount(series.total)}
              {series.total !== null && !series.complete && " (partial)"}
            </td>
          ))}
        </tr>
      </tfoot>
    </DataTable>
  );
}

function ClassificationTable({ caption, rows }: { caption: string; rows: AnalyticsSeries[] }) {
  return (
    <DataTable caption={caption}>
      <thead>
        <tr className="border-b">
          <th scope="col" className="py-1 pr-4 font-medium">
            Classification
          </th>
          <th scope="col" className="py-1 pr-4 font-medium">
            Count
          </th>
          <th scope="col" className="py-1 pr-4 font-medium">
            Months reported
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={`${row.section}/${row.code}`} className="border-b border-border/50">
            <th scope="row" className="py-1 pr-4 font-normal">
              {row.name}
            </th>
            <td className="py-1 pr-4">{formatCount(row.total)}</td>
            <td className="py-1 pr-4">
              {row.monthsReported} of {row.values.length}
            </td>
          </tr>
        ))}
      </tbody>
    </DataTable>
  );
}

/** Reported categories with their totals; a reported 0 stays 0. */
function BreakdownTable({ caption, label, rows }: { caption: string; label: string; rows: AnalyticsCategory[] }) {
  return (
    <DataTable caption={caption}>
      <thead>
        <tr className="border-b">
          <th scope="col" className="py-1 pr-4 font-medium">
            {label}
          </th>
          <th scope="col" className="py-1 pr-4 font-medium">
            Count
          </th>
          <th scope="col" className="py-1 pr-4 font-medium">
            Months reported
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={3} className="py-1 text-muted-foreground">
              Nothing reported.
            </td>
          </tr>
        ) : (
          rows.map((row) => (
            <tr key={row.code} className="border-b border-border/50">
              <th scope="row" className="py-1 pr-4 font-normal" title={row.description ?? undefined}>
                {row.name}
              </th>
              <td className="py-1 pr-4">{formatCount(row.total)}</td>
              <td className="py-1 pr-4">
                {row.monthsReported} of {row.values.length}
              </td>
            </tr>
          ))
        )}
      </tbody>
    </DataTable>
  );
}
