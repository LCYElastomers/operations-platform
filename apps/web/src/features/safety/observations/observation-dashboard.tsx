"use client";

import { AlertTriangle, ClipboardList, Eye, Percent, ShieldAlert, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { BarChart } from "@/components/common/bar-chart";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar, FilterSelect } from "@/components/common/filter-bar";
import { MetricCard } from "@/components/common/metric-card";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { TrendChart } from "@/components/common/trend-chart";
import { Button, buttonVariants } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";

import { defaultReportingYear, MONTH_LABELS } from "../incidents/grid";
import { ReportingYearSelect } from "../incidents/reporting-year-select";
import { describeObservationError } from "./api";
import {
  actConditionBreakdown,
  categoryOverTime,
  categoryYearToDate,
  formatShare,
  localIsoDate,
  monthlySafeVsUnsafe,
  runningTotals,
} from "./observation-data";
import { useObservationDashboard } from "./use-observations";

const CHART_HEIGHT = 340;
const CATEGORY_ROW_HEIGHT = 26;

type ObservationDashboardProps = { title: string; description?: string };

export function ObservationDashboard({ title, description }: ObservationDashboardProps) {
  const today = localIsoDate(new Date());
  const [year, setYear] = useState(() => defaultReportingYear(Number(today.slice(0, 4))));
  const [categoryCode, setCategoryCode] = useState<string>("");
  const dashboard = useObservationDashboard(year);
  const data = dashboard.data;
  const loading = dashboard.isPending && !dashboard.isError;
  const failed = dashboard.isError;

  const monthly = useMemo(() => monthlySafeVsUnsafe(data), [data]);
  const actCondition = useMemo(() => actConditionBreakdown(data), [data]);
  const byCategory = useMemo(() => categoryYearToDate(data), [data]);
  const running = useMemo(() => runningTotals(data, today), [data, today]);

  const categoryOptions = (data?.categories ?? []).map((c) => ({ value: c.code, label: c.name }));
  const selectedCode =
    categoryOptions.find((option) => option.value === categoryCode)?.value ??
    [...(data?.categories ?? [])].sort((a, b) => b.total - a.total)[0]?.code ??
    "";
  const overTime = useMemo(() => categoryOverTime(data, selectedCode), [data, selectedCode]);

  const accessDenied =
    dashboard.error instanceof ApiError &&
    (dashboard.error.status === 401 || dashboard.error.status === 403);
  const errorState = (
    <EmptyState
      variant="plain"
      icon={AlertTriangle}
      title={accessDenied ? "Safety data is not available to you" : "Could not load Safety data"}
      description={describeObservationError(dashboard.error)}
      action={
        accessDenied ? undefined : (
          <Button variant="outline" size="sm" onClick={() => void dashboard.refetch()}>
            Retry
          </Button>
        )
      }
    />
  );

  const counts = data?.counts;
  const through = data?.throughMonth ?? 0;
  const caption = failed
    ? "Unavailable"
    : through === 0
      ? `${year} has not started`
      : through === 12
        ? `Jan–Dec ${year}`
        : `Jan–${MONTH_LABELS[through - 1]} ${year} (to date)`;
  const empty = !failed && counts?.total === 0;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Safety · Safety Observations"
        title={title}
        description={description}
        actions={
          <Link
            href="/safety/observations"
            className={buttonVariants({ variant: "outline", className: "pointer-coarse:h-11" })}
          >
            <ClipboardList />
            Open observations
          </Link>
        }
      />

      <FilterBar
        actions={
          dashboard.isFetching && !dashboard.isPending ? (
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
        <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
          <MetricCard label="Total Observations" value={failed ? null : (counts?.total ?? null)} caption={caption} icon={Eye} emphasis loading={loading} />
          <MetricCard label="Safe" value={failed ? null : (counts?.safe ?? null)} caption={caption} icon={ShieldCheck} emphasis loading={loading} />
          <MetricCard label="Unsafe" value={failed ? null : (counts?.unsafe ?? null)} caption={caption} icon={ShieldAlert} emphasis loading={loading} />
          <MetricCard
            label="Unsafe share"
            value={failed ? null : formatShare(data?.unsafeShare ?? null)}
            caption={failed ? "Unavailable" : counts?.total ? "Unsafe ÷ total observations" : "No observations yet"}
            icon={Percent}
            emphasis
            loading={loading}
          />
        </div>
        <p className="px-1 text-xs text-muted-foreground">
          Every figure counts individual observation records, so Safe + Unsafe and Act + Condition
          both equal the total. Legacy workbook tallies are not included.
        </p>
      </section>

      {empty && (
        <EmptyState
          icon={ClipboardList}
          title={`No observations recorded for ${year}`}
          description="Charts fill in as observations are added on the Observations page."
        />
      )}

      <section aria-label="Charts" className="grid grid-cols-1 gap-5 min-[1440px]:grid-cols-2">
        <BarChart
          title="Safe vs Unsafe by Month"
          description={`Observations per month, ${year}. Months that have not started show no bar.`}
          categories={MONTH_LABELS}
          series={failed ? [] : monthly}
          height={CHART_HEIGHT}
          showValues
          loading={loading}
          emptyState={failed ? errorState : undefined}
        />
        <TrendChart
          title="Running Totals, Safe vs Unsafe"
          description={`Cumulative observations through each month end, ${year}; the current month is to date.`}
          series={failed ? [] : running}
          precision={0}
          height={CHART_HEIGHT}
          loading={loading}
          emptyState={failed ? errorState : undefined}
        />
        <BarChart
          title="Act / Condition Breakdown, Year to Date"
          description={`Safe and Unsafe observations by Act or Condition, ${year}.`}
          categories={actCondition.categories}
          series={failed ? [] : actCondition.series}
          height={CHART_HEIGHT}
          showValues
          loading={loading}
          emptyState={failed ? errorState : undefined}
        />
        <BarChart
          title="By Category, Year to Date"
          description={`Safe and Unsafe observations per category, ${year}.`}
          categories={byCategory.categories}
          series={failed ? [] : byCategory.series}
          orientation="horizontal"
          height={Math.max(CHART_HEIGHT, byCategory.categories.length * CATEGORY_ROW_HEIGHT)}
          showValues
          loading={loading}
          emptyState={failed ? errorState : undefined}
          className="min-[1440px]:row-span-2"
        />
        <section className="flex flex-col gap-3">
          <div className="w-full sm:w-72">
            <FilterSelect
              label="Category over time"
              placeholder={false}
              options={categoryOptions}
              value={selectedCode}
              onChange={(event) => setCategoryCode(event.target.value)}
              disabled={categoryOptions.length === 0}
              className="pointer-coarse:h-11"
            />
          </div>
          <BarChart
            title={`${overTime[0]?.name ?? "Category"} by Month`}
            description={`Observations in this category per month, ${year}.`}
            categories={MONTH_LABELS}
            series={failed ? [] : overTime}
            height={CHART_HEIGHT}
            showValues
            loading={loading}
            emptyState={failed ? errorState : undefined}
          />
        </section>
      </section>

      {loading && <span className="sr-only">Loading Safety data</span>}
    </div>
  );
}
