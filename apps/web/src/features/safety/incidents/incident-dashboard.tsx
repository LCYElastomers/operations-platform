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
  Wrench,
} from "lucide-react";
import Link from "next/link";

import { BarChart } from "@/components/common/bar-chart";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar, FilterSelect } from "@/components/common/filter-bar";
import { MetricCard } from "@/components/common/metric-card";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";

import {
  bars,
  classificationChart,
  COLORS,
  combinedKpiCaption,
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
  totalLabel,
} from "./analytics-data";
import {
  describeSafetyError,
  type AnalyticsKpi,
  type AnalyticsSeries,
  type IncidentAnalyticsResponse,
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

type IncidentDashboardProps = {
  title: string;
  description?: string;
  /** The Baytown date when the page was rendered on the server. */
  siteToday: string;
};

/** The Incident & Near Miss Dashboard, backed by the read-only Incident Analytics API. */
export function IncidentDashboard({ title, description, siteToday }: IncidentDashboardProps) {
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
  const analytics = useIncidentAnalytics(year, throughChoice.isAutomatic ? null : through);
  const data = analytics.data;
  const loading = analytics.isPending && !analytics.isError;
  const shownThrough = data?.throughMonth ?? null;
  const period = shownThrough === null ? String(year) : periodLabel(year, shownThrough);
  const months = monthLabels(shownThrough);
  const nothingReported = data !== undefined && data.kpis.every((kpi) => kpi.value === null);

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
  const chart = { height: CHART_HEIGHT, showValues: true, loading, emptyState };

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

      <section aria-label="Year to date" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {KPI_KEYS.map((key) => {
          const kpi = findKpi(data, key);
          const caption = key === "combined_damage" ? combinedKpiCaption : kpiCaption;
          return (
            <MetricCard
              key={key}
              label={KPI_LABELS[key]}
              value={kpi?.value ?? null}
              caption={analytics.isError ? "Unavailable" : kpi ? caption(kpi, year) : undefined}
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
            analytics.isError
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
        <BarChart
          title="Incident Classification"
          description={`Count per classification, ${period}. ${NOTES.classification}`}
          {...classificationChartProps(data, analytics.isError)}
          orientation="horizontal"
          footer={data && <ClassificationTable caption={`Incident Classification, ${period}`} rows={data.classifications} />}
          {...chart}
          height={420}
        />
        <BarChart
          title="LOPC by Month"
          description={`Loss of Primary Containment (LOPC) counts, ${period}. ${NOTES.lopc}`}
          categories={months}
          series={analytics.isError ? [] : [bars(data?.lopc, "LOPC", COLORS.lopc)]}
          footer={
            data && <MonthlyTable caption={`LOPC by month, ${period}`} months={months} columns={[["LOPC", data.lopc]]} />
          }
          {...chart}
        />
        <BarChart
          title="Property vs Equipment Damage by Month"
          description={
            data
              ? `${totalLabel(data.propertyDamage)}; ${totalLabel(data.equipmentDamage)}; combined ${formatCount(data.combinedDamage.total)}. ${NOTES.damage}`
              : NOTES.damage
          }
          categories={months}
          series={
            analytics.isError
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
          series={analytics.isError ? [] : [bars(data?.pit, "PIT incidents", COLORS.pit)]}
          footer={
            data && (
              <MonthlyTable caption={`${PIT_TITLE} by month, ${period}`} months={months} columns={[["PIT incidents", data.pit]]} />
            )
          }
          {...chart}
        />
        <BarChart
          title="PSIF by Month"
          description={`Monthly counts, ${period}. ${NOTES.psif}`}
          categories={months}
          series={analytics.isError ? [] : [bars(data?.psif, "PSIF", COLORS.psif)]}
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
          </ul>
          <Completeness data={data} period={period} />
        </section>
      )}

      {loading && <span className="sr-only">Loading Safety data</span>}
    </div>
  );
}

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
