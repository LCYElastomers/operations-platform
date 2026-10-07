"use client";

import {
  AlertTriangle,
  Construction,
  Droplet,
  Forklift,
  OctagonAlert,
  Siren,
  TableProperties,
  TriangleAlert,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { BarChart } from "@/components/common/bar-chart";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { MetricCard } from "@/components/common/metric-card";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";

import { describeSafetyError } from "./api";
import {
  classificationBreakdown,
  findMetric,
  incidentsVsNearMisses,
  KPI_METRICS,
  reportedCaption,
  type KpiCategoryCode,
} from "./dashboard-data";
import { defaultReportingYear, MONTH_LABELS } from "./grid";
import { ReportingYearSelect } from "./reporting-year-select";
import { useIncidentMetrics } from "./use-incident-metrics";

const KPI_ICONS: Record<KpiCategoryCode, React.ComponentType<{ className?: string }>> = {
  incident: Siren,
  near_miss: TriangleAlert,
  lopc: Droplet,
  property_equipment_damage: Construction,
  pit: Forklift,
  psif: OctagonAlert,
};

const CHART_HEIGHT = 360;
/** Incident and Near Miss lead the page; the rest follow in a smaller row. */
const HEADLINE_KPIS = 2;

type IncidentDashboardProps = {
  title: string;
  description?: string;
};

export function IncidentDashboard({ title, description }: IncidentDashboardProps) {
  const [year, setYear] = useState(() => defaultReportingYear(new Date().getFullYear()));
  const metrics = useIncidentMetrics(year);
  const data = metrics.data;
  const loading = metrics.isPending && !metrics.isError;

  const monthlySeries = useMemo(() => incidentsVsNearMisses(data), [data]);
  const breakdown = useMemo(() => classificationBreakdown(data), [data]);

  const accessDenied =
    metrics.error instanceof ApiError && (metrics.error.status === 401 || metrics.error.status === 403);

  const errorState = (
    <EmptyState
      variant="plain"
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
  );

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Safety · Incident & Near Miss"
        title={title}
        description={description}
        actions={
          <Link
            href="/safety/incidents/data-entry"
            className={buttonVariants({ variant: "outline" })}
          >
            <TableProperties />
            Open data entry
          </Link>
        }
      />

      <FilterBar
        actions={
          metrics.isFetching && !metrics.isPending ? (
            <StatusBadge tone="pending" pulse>
              Updating
            </StatusBadge>
          ) : undefined
        }
      >
        <div className="w-full sm:w-44">
          <ReportingYearSelect year={year} onChange={setYear} yearsWithData={data?.yearsWithData} />
        </div>
      </FilterBar>

      <section aria-label="Year to date" className="space-y-2">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {KPI_METRICS.map((kpi, index) => {
            const metric = findMetric(data, kpi.sectionCode, kpi.categoryCode);
            const headline = index < HEADLINE_KPIS;
            return (
              <MetricCard
                key={kpi.categoryCode}
                label={kpi.label}
                value={metric?.ytd ?? null}
                caption={metrics.isError ? "Unavailable" : reportedCaption(metric, year)}
                icon={KPI_ICONS[kpi.categoryCode]}
                emphasis={headline}
                loading={loading}
                className={headline ? "xl:col-span-2" : undefined}
              />
            );
          })}
        </div>
        <p className="px-1 text-xs text-muted-foreground">
          YTD is the sum of reported months. Incident and Near Miss are reported totals;
          classifications can overlap and are not added together.
        </p>
      </section>

      <section aria-label="Charts" className="grid grid-cols-1 gap-5 min-[1440px]:grid-cols-2">
        <BarChart
          title="Incidents vs Near Misses by Month"
          description={`Reported monthly totals, ${year}. No bar means the month was not reported.`}
          categories={MONTH_LABELS}
          series={metrics.isError ? [] : monthlySeries}
          height={CHART_HEIGHT}
          showValues
          loading={loading}
          emptyState={metrics.isError ? errorState : undefined}
        />
        <BarChart
          title="Incident Classification, Year to Date"
          description={`Count per classification, ${year}. One incident may have more than one classification.`}
          categories={breakdown.categories}
          series={metrics.isError ? [] : breakdown.series}
          orientation="horizontal"
          height={CHART_HEIGHT}
          showValues
          loading={loading}
          emptyState={metrics.isError ? errorState : undefined}
        />
      </section>

      {loading && <span className="sr-only">Loading Safety data</span>}
    </div>
  );
}
