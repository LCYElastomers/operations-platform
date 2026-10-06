"use client";

import {
  AlertTriangle,
  Construction,
  Droplet,
  Forklift,
  OctagonAlert,
  Siren,
  TriangleAlert,
} from "lucide-react";
import { useMemo, useState } from "react";

import { BarChart } from "@/components/common/bar-chart";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { MetricCard } from "@/components/common/metric-card";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";

import { describeSafetyError } from "./api";
import {
  classificationBreakdown,
  findMetric,
  incidentsVsNearMisses,
  KPI_METRICS,
  reportedPeriod,
  type KpiCategoryCode,
} from "./dashboard-data";
import { MONTH_LABELS } from "./grid";
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

const CHART_HEIGHT = 320;

type IncidentDashboardProps = {
  title: string;
  description?: string;
};

export function IncidentDashboard({ title, description }: IncidentDashboardProps) {
  const [year, setYear] = useState(() => new Date().getFullYear());
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
    <div className="space-y-6">
      <PageHeader eyebrow="Safety · Incident & Near Miss" title={title} description={description} />

      <FilterBar
        actions={
          metrics.isFetching && !metrics.isPending ? (
            <StatusBadge tone="pending" pulse>
              Updating
            </StatusBadge>
          ) : undefined
        }
      >
        <ReportingYearSelect year={year} onChange={setYear} yearsWithData={data?.yearsWithData} />
      </FilterBar>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
        {KPI_METRICS.map((kpi) => {
          const metric = findMetric(data, kpi.sectionCode, kpi.categoryCode);
          return (
            <MetricCard
              key={kpi.categoryCode}
              label={kpi.label}
              value={metric?.ytd ?? null}
              caption={metrics.isError ? "Unavailable" : reportedPeriod(metric, year)}
              icon={KPI_ICONS[kpi.categoryCode]}
              loading={loading}
            />
          );
        })}
      </div>
      <p className="-mt-3 px-1 text-xs text-muted-foreground">
        YTD values are the sum of reported months. Incident and Near Miss are the reported monthly
        totals, not sums of Incident Classification; classifications can overlap.
      </p>

      <section aria-label="Charts" className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <BarChart
          title="Incidents vs Near Misses by Month"
          description={`Reported monthly totals, ${year}. Months without reported values show no bar.`}
          categories={MONTH_LABELS}
          series={metrics.isError ? [] : monthlySeries}
          height={CHART_HEIGHT}
          loading={loading}
          emptyState={metrics.isError ? errorState : undefined}
        />
        <BarChart
          title="Incident Classification YTD Breakdown"
          description={`Year-to-date count per classification, ${year}. One incident may have more than one classification.`}
          categories={breakdown.categories}
          series={metrics.isError ? [] : breakdown.series}
          orientation="horizontal"
          height={CHART_HEIGHT}
          loading={loading}
          emptyState={metrics.isError ? errorState : undefined}
        />
      </section>

      {loading && <span className="sr-only">Loading Safety data</span>}
    </div>
  );
}
