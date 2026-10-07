"use client";

import { AlertTriangle, CalendarRange, Clock, TableProperties } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { BarChart } from "@/components/common/bar-chart";
import { DataTable, type DataTableColumn } from "@/components/common/data-table";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar, FilterSelect } from "@/components/common/filter-bar";
import { MetricCard } from "@/components/common/metric-card";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge, type StatusTone } from "@/components/common/status-badge";
import { TrendChart } from "@/components/common/trend-chart";
import { Button, buttonVariants } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";

import { siteIsoDate } from "../contacts/contact-data";
import { MONTH_LABELS, reportingYearOptions } from "../incidents/grid";
import { describePerformanceError, type MonthStatus, type PerformanceMonth } from "./api";
import {
  annualTrirChart,
  formatHours,
  formatRate,
  hoursSeries,
  MEASURES,
  rateCaption,
  rateTrendSeries,
  ROLLING_LABEL,
  SHORT_LABELS,
  STATUS_LABELS,
  throughLabel,
} from "./performance-data";
import { usePerformanceDashboard } from "./use-performance";

const CHART_HEIGHT = 320;
const FIRST_HOURS_YEAR = 2000;
const LATEST = "latest";

const STATUS_TONES: Record<MonthStatus, StatusTone> = {
  not_reported: "neutral",
  reported: "info",
  closed: "success",
};

const count = (value: number | null) => value ?? "—";

export const monthColumns: DataTableColumn<PerformanceMonth>[] = [
  { id: "month", header: "Month", accessorFn: (row) => MONTH_LABELS[row.month - 1] },
  {
    id: "status",
    header: "Status",
    cell: ({ row }) => (
      <StatusBadge tone={STATUS_TONES[row.original.status]}>{STATUS_LABELS[row.original.status]}</StatusBadge>
    ),
  },
  { id: "total", header: "Total hours", accessorFn: (row) => formatHours(row.hours?.totalHours ?? null) },
  { id: "hourly", header: "Hourly", accessorFn: (row) => formatHours(row.hours?.hourlyHours ?? null) },
  { id: "salary", header: "Salary", accessorFn: (row) => formatHours(row.hours?.salaryHours ?? null) },
  { id: "trir", header: "Recordables", accessorFn: (row) => count(row.counts.trir) },
  { id: "firstAid", header: "First Aid", accessorFn: (row) => count(row.counts.firstAid) },
  { id: "lopc", header: "LOPC", accessorFn: (row) => count(row.counts.lopc) },
  { id: "property", header: "Property", accessorFn: (row) => count(row.counts.propertyDamage) },
  { id: "equipment", header: "Equipment", accessorFn: (row) => count(row.counts.equipmentDamageFailure) },
  { id: "damage", header: "P&E Damage", accessorFn: (row) => count(row.counts.propertyEquipmentDamage) },
  {
    id: "counts",
    header: "Counts",
    accessorFn: (row) => (row.countsConfirmed ? "Confirmed" : "Not confirmed"),
  },
];

type PerformanceDashboardProps = { title: string; description?: string };

export function PerformanceDashboard({ title, description }: PerformanceDashboardProps) {
  const currentYear = Number(siteIsoDate(new Date()).slice(0, 4));
  const [year, setYear] = useState(currentYear);
  const [through, setThrough] = useState<number | null>(null);
  const query = usePerformanceDashboard(year, through);
  const data = query.data;
  const loading = query.isPending && !query.isError;
  const failed = query.isError;

  const hours = useMemo(() => hoursSeries(data), [data]);
  const trir = useMemo(
    () =>
      rateTrendSeries(data, [
        { measure: "trir", window: "ytd", name: "TRIR YTD" },
        { measure: "trir", window: "rolling", name: "TRIR 12MRA" },
      ]),
    [data],
  );
  const otherRolling = useMemo(
    () =>
      rateTrendSeries(
        data,
        (["first_aid", "lopc", "property_equipment_damage"] as const).map((measure) => ({
          measure,
          window: "rolling" as const,
          name: `${SHORT_LABELS[measure]} 12MRA`,
        })),
      ),
    [data],
  );
  const otherYtd = useMemo(
    () =>
      rateTrendSeries(
        data,
        (["first_aid", "lopc", "property_equipment_damage"] as const).map((measure) => ({
          measure,
          window: "ytd" as const,
          name: `${SHORT_LABELS[measure]} YTD`,
        })),
      ),
    [data],
  );
  const annual = useMemo(() => annualTrirChart(data), [data]);

  const accessDenied =
    query.error instanceof ApiError && (query.error.status === 401 || query.error.status === 403);
  const errorState = (
    <EmptyState
      variant="plain"
      icon={AlertTriangle}
      title={accessDenied ? "Safety data is not available to you" : "Could not load Safety Performance"}
      description={describePerformanceError(query.error)}
      action={
        accessDenied ? undefined : (
          <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
            Retry
          </Button>
        )
      }
    />
  );

  const years = reportingYearOptions(currentYear, [...(data?.yearsWithData ?? []), year], FIRST_HOURS_YEAR);
  const label = data ? throughLabel(data.year, data.throughMonth) : "";
  const noClosedMonths = !failed && data !== undefined && data.throughMonth === null;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Safety · Safety Performance"
        title={title}
        description={description}
        actions={
          <Link
            href="/safety/performance/data-entry"
            className={buttonVariants({ variant: "outline", className: "pointer-coarse:h-11" })}
          >
            <TableProperties />
            Open data entry
          </Link>
        }
      />

      <FilterBar
        actions={
          query.isFetching && !query.isPending ? (
            <StatusBadge tone="pending" pulse>
              Updating
            </StatusBadge>
          ) : undefined
        }
      >
        <div className="w-full sm:w-44">
          <FilterSelect
            label="Reporting year"
            placeholder={false}
            options={years.map((value) => ({ value: String(value), label: String(value) }))}
            value={String(year)}
            onChange={(event) => {
              setYear(Number(event.target.value));
              setThrough(null);
            }}
            className="pointer-coarse:h-11"
          />
        </div>
        <div className="w-full sm:w-56">
          <FilterSelect
            label="Through month"
            placeholder={false}
            options={[
              { value: LATEST, label: "Latest closed month" },
              ...MONTH_LABELS.map((month, index) => ({ value: String(index + 1), label: `${month} ${year}` })),
            ]}
            value={through === null ? LATEST : String(through)}
            onChange={(event) => setThrough(event.target.value === LATEST ? null : Number(event.target.value))}
            className="pointer-coarse:h-11"
          />
        </div>
      </FilterBar>

      <section aria-labelledby="kpi-heading" className="space-y-2">
        <h2 id="kpi-heading" className="px-1 text-base font-semibold">
          {failed ? "Rates unavailable" : loading ? "Loading rates" : label}
        </h2>
        {failed ? (
          <div className="rounded-lg border bg-card">{errorState}</div>
        ) : noClosedMonths ? (
          <EmptyState
            icon={CalendarRange}
            title={`No closed months in ${year}`}
            description="Rates start once January's hours are entered and the month is closed. YTD needs every month from January to the selected month closed with hours above zero."
          />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="Worked hours YTD"
              value={data?.ytdHours ?? null}
              precision={0}
              unit="h"
              caption={
                data?.ytdHours == null
                  ? "Unavailable"
                  : `Jan ${year} – ${MONTH_LABELS[(data.throughMonth ?? 1) - 1]} ${year}`
              }
              icon={Clock}
              loading={loading}
              className="sm:col-span-2 xl:col-span-4"
            />
            {MEASURES.map(({ measure, label: measureLabel }) => {
              const kpi = data?.kpis.find((k) => k.measure === measure);
              return (
                <div key={measure} className="grid content-start gap-2">
                  <MetricCard
                    label={`${measureLabel} · YTD`}
                    value={kpi ? formatRate(kpi.ytd.rate) : null}
                    caption={kpi ? rateCaption(kpi.ytd) : undefined}
                    loading={loading}
                  />
                  <MetricCard
                    label={`${measureLabel} · 12MRA`}
                    value={kpi ? formatRate(kpi.rolling.rate) : null}
                    caption={kpi ? rateCaption(kpi.rolling) : undefined}
                    loading={loading}
                  />
                </div>
              );
            })}
          </div>
        )}
        <p className="px-1 text-xs text-muted-foreground">
          Every rate is events × 200,000 ÷ worked hours over the same months. YTD is January through the month shown;
          the {ROLLING_LABEL} is the 12 months ending in it and is shown only when all 12 are closed with hours. A month
          counts only when its hours are above zero and it is closed; blank Incident &amp; Near Miss counts in a closed
          month are zero. TRIR counts recordable injuries plus occupational illnesses. Property &amp; Equipment Damage is
          property damage plus equipment damage/failure: monthly counts cannot identify an event recorded under both,
          so it is counted twice and the rate is not a count of distinct events. Counts before 2026 come from the legacy
          workbook import, where a blank count is not confirmed and makes the rates that need it unavailable.
        </p>
      </section>

      <section aria-label="Charts" className="grid grid-cols-1 gap-5 min-[1440px]:grid-cols-2">
        <BarChart
          title="Worked Hours by Month"
          description={`Total hours reported per month, ${year}. No bar means not reported.`}
          categories={MONTH_LABELS}
          series={failed ? [] : hours}
          height={CHART_HEIGHT}
          loading={loading}
          emptyState={failed ? errorState : undefined}
        />
        <TrendChart
          title="TRIR: YTD vs 12MRA"
          description={`Through each month end, ${year}. A month with no point has no rate yet.`}
          series={failed ? [] : trir}
          precision={2}
          height={CHART_HEIGHT}
          loading={loading}
          emptyState={failed ? errorState : undefined}
        />
        <TrendChart
          title="First Aid, LOPC and Property & Equipment Damage: 12MRA"
          description={`${ROLLING_LABEL} through each month end, ${year}.`}
          series={failed ? [] : otherRolling}
          precision={2}
          height={CHART_HEIGHT}
          loading={loading}
          emptyState={failed ? errorState : undefined}
        />
        <TrendChart
          title="First Aid, LOPC and Property & Equipment Damage: YTD"
          description={`Year to date through each month end, ${year}.`}
          series={failed ? [] : otherYtd}
          precision={2}
          height={CHART_HEIGHT}
          loading={loading}
          emptyState={failed ? errorState : undefined}
        />
        <BarChart
          title="Annual TRIR"
          description="Full years, and the current year to date (marked YTD). Years before monthly records use the workbook's annual recordables and hours; a year with no bar has no accepted figures."
          categories={annual.categories}
          series={failed ? [] : annual.series}
          height={CHART_HEIGHT}
          showValues
          loading={loading}
          emptyState={failed ? errorState : undefined}
          className="min-[1440px]:col-span-2"
        />
      </section>

      <section aria-labelledby="month-table-heading" className="space-y-2">
        <h2 id="month-table-heading" className="text-base font-semibold">
          Monthly Hours, Status and Event Counts, {year}
        </h2>
        <p className="text-sm text-muted-foreground">
          {data?.countSource === "performance_legacy"
            ? "Counts are from the legacy workbook import, which has a single combined damage count."
            : "Counts are read from Incident & Near Miss."}{" "}
          Recordables are recordable injuries plus occupational illnesses. A dash is not reported.
        </p>
        {failed ? (
          <div className="rounded-lg border bg-card">{errorState}</div>
        ) : (
          <DataTable
            columns={monthColumns}
            data={data?.months ?? []}
            loading={loading}
            enableSorting={false}
            caption={`Monthly hours, status and event counts, ${year}`}
          />
        )}
      </section>

      {loading && <span className="sr-only">Loading Safety Performance</span>}
    </div>
  );
}
