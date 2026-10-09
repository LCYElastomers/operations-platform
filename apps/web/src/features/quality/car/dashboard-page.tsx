"use client";

import { AlarmClock, CalendarCheck, ClipboardList, Hourglass, SearchCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { BarChart } from "@/components/common/bar-chart";
import { FilterBar, FilterInput, FilterSelect } from "@/components/common/filter-bar";
import { MetricCard } from "@/components/common/metric-card";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";

import { TableSection } from "../cost/cost-shared";
import { MONTH_LABELS, toNumber, usd } from "../cost/format";

import {
  carHref,
  carQueryParams,
  EMPTY_CAR_QUERY,
  type CarDashboard,
  type CarDashboardQuery,
  type CarQuery,
  type Count,
} from "./api";
import { CarError, filterOptions, NoCars } from "./car-shared";
import { CarTable, NewCarLink } from "./register-page";
import { useCarDashboard, useCarOptions, useCars } from "./use-car";

const NO_FILTERS: CarDashboardQuery = { from: "", to: "", department: "", source: "", assignedTo: "" };

const COLORS = {
  open: "#2563eb",
  closed: "#059669",
  pastDue: "#dc2626",
  neutral: "#64748b",
  cost: "#ea580c",
};

function registerHref(filters: CarDashboardQuery, extra: Partial<CarQuery> = {}) {
  const params = carQueryParams({ ...EMPTY_CAR_QUERY, ...filters, ...extra });
  const query = params.toString();
  return query ? `/quality/cars/register?${query}` : "/quality/cars/register";
}

function countChart(counts: Count[]) {
  return { categories: counts.map((c) => c.label), values: counts.map((c) => c.count) };
}

/** Counts with at least one CAR, largest first ("Not recorded" last). */
function present(counts: Count[]) {
  return counts
    .filter((c) => c.count > 0)
    .sort((a, b) => (a.code === null ? 1 : b.code === null ? -1 : b.count - a.count));
}

/**
 * CAR status at a glance: open and overdue work, effectiveness reviews waiting,
 * trends and cost. Every figure is calculated by the API from the CAR records.
 */
export function CarDashboardPage({ title, description }: { title: string; description?: string }) {
  const options = useCarOptions();
  const [filters, setFilters] = useState<CarDashboardQuery>(NO_FILTERS);
  const dashboard = useCarDashboard(filters);
  const pastDue = useCars({ ...EMPTY_CAR_QUERY, ...filters, pastDue: true });
  const data = dashboard.data;
  const filtered = JSON.stringify(filters) !== JSON.stringify(NO_FILTERS);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Quality · Corrective Action Reports"
        title={title}
        description={description}
        actions={options.data?.abilities.create ? <NewCarLink /> : undefined}
      />
      <FilterBar
        actions={
          <>
            {dashboard.isFetching && !dashboard.isPending && (
              <StatusBadge tone="pending" pulse>
                Updating
              </StatusBadge>
            )}
            {filtered && (
              <Button variant="ghost" size="sm" onClick={() => setFilters(NO_FILTERS)}>
                Clear filters
              </Button>
            )}
          </>
        }
      >
        <FilterInput
          label="Requested from"
          type="date"
          value={filters.from}
          max={filters.to || undefined}
          onChange={(event) => setFilters({ ...filters, from: event.target.value })}
          className="pointer-coarse:h-11"
        />
        <FilterInput
          label="Requested to"
          type="date"
          value={filters.to}
          min={filters.from || undefined}
          onChange={(event) => setFilters({ ...filters, to: event.target.value })}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Department"
          options={filterOptions(options.data?.departments)}
          value={filters.department}
          onChange={(event) => setFilters({ ...filters, department: event.target.value })}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Source"
          options={filterOptions(options.data?.sources)}
          value={filters.source}
          onChange={(event) => setFilters({ ...filters, source: event.target.value })}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Assigned to"
          options={(options.data?.assignees ?? []).map((name) => ({ value: name, label: name }))}
          value={filters.assignedTo}
          onChange={(event) => setFilters({ ...filters, assignedTo: event.target.value })}
          className="pointer-coarse:h-11"
        />
      </FilterBar>
      {dashboard.isError ? (
        <CarError error={dashboard.error} onRetry={() => void dashboard.refetch()} />
      ) : !data ? (
        <Kpis data={undefined} filters={filters} />
      ) : data.kpis.total === 0 ? (
        <NoCars filtered={filtered} action={filtered || !options.data?.abilities.create ? undefined : <NewCarLink />} />
      ) : (
        <>
          <Kpis data={data} filters={filters} />
          <Charts data={data} />
          <TableSection
            id="car-past-due"
            title="Past-due CARs"
            description="Not closed, with a due date before today."
            actions={
              <Link href={registerHref(filters, { pastDue: true })} className="text-sm font-medium text-primary hover:underline">
                Open in register
              </Link>
            }
          >
            {pastDue.data && pastDue.data.cars.length > 0 ? (
              <CarTable cars={pastDue.data.cars} />
            ) : (
              <p className="px-4 py-3 text-sm text-muted-foreground">
                {pastDue.isPending ? "Loading…" : "No CARs are past due."}
              </p>
            )}
          </TableSection>
          <RepeatCars data={data} />
        </>
      )}
    </div>
  );
}

function Kpis({ data, filters }: { data: CarDashboard | undefined; filters: CarDashboardQuery }) {
  const loading = data === undefined;
  const k = data?.kpis;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      <MetricCard
        label="Open CARs"
        value={k?.open ?? null}
        icon={ClipboardList}
        caption={
          k
            ? `Not closed, of ${k.total} CARs${k.statusNotRecorded > 0 ? ` · ${k.statusNotRecorded} imported with no status` : ""}`
            : undefined
        }
        loading={loading}
        emphasis
      />
      <Link href={registerHref(filters, { pastDue: true })} className="rounded-lg focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none">
        <MetricCard
          label="Past due"
          value={k?.pastDue ?? null}
          icon={AlarmClock}
          caption="Not closed, due date passed"
          detail={k && k.actionsOverdue > 0 ? `${k.actionsOverdue} corrective actions overdue` : null}
          loading={loading}
          emphasis
          className="h-full hover:bg-muted/40"
        />
      </Link>
      <MetricCard
        label="Due soon"
        value={k?.dueSoon ?? null}
        icon={Hourglass}
        caption={data ? `Due within ${data.dueSoonDays} days` : undefined}
        loading={loading}
        emphasis
      />
      <MetricCard
        label="Awaiting effectiveness"
        value={k?.awaitingEffectiveness ?? null}
        icon={SearchCheck}
        caption="All actions complete, not yet reviewed"
        loading={loading}
        emphasis
      />
      <MetricCard
        label="Closed YTD"
        value={k?.closedYtd ?? null}
        icon={CalendarCheck}
        caption={data ? `Closed in ${data.year}` : undefined}
        loading={loading}
        emphasis
      />
    </div>
  );
}

function Charts({ data }: { data: CarDashboard }) {
  const trendLabels = data.trend.map((m) => `${MONTH_LABELS[m.month - 1]} ${String(m.year).slice(2)}`);
  const status = countChart(data.byStatus.filter((c) => c.count > 0));
  const department = countChart(present(data.byDepartment));
  const source = countChart(present(data.bySource));
  const rootCause = countChart(present(data.byRootCause));
  const effectiveness = countChart(data.effectiveness);
  const repeat = countChart(data.repeat);
  const cost = data.cost;
  const costByDepartment = [...cost.byDepartment].sort((a, b) => Number(b.total) - Number(a.total));
  const rowHeight = (n: number) => Math.max(160, n * 34 + 40);
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <BarChart
        title="CARs by status"
        categories={status.categories}
        series={[{ name: "CARs", values: status.values, color: COLORS.open }]}
        showValues
      />
      <BarChart
        title="Opened vs closed"
        description="CARs requested and closed each month, last 12 months."
        categories={trendLabels}
        series={[
          { name: "Opened", values: data.trend.map((m) => m.opened), color: COLORS.open },
          { name: "Closed", values: data.trend.map((m) => m.closed), color: COLORS.closed },
        ]}
      />
      <BarChart
        title="Aging of CARs not closed"
        description="Days since the request date."
        categories={data.aging.map((b) => b.label)}
        series={[{ name: "CARs", values: data.aging.map((b) => b.count), color: COLORS.pastDue }]}
        showValues
      />
      <BarChart
        title="Effectiveness review"
        description="Result of the effectiveness review, all CARs."
        categories={effectiveness.categories}
        series={[{ name: "CARs", values: effectiveness.values, color: COLORS.closed }]}
        showValues
      />
      <BarChart
        title="CARs by department"
        orientation="horizontal"
        height={rowHeight(department.categories.length)}
        categories={department.categories}
        series={[{ name: "CARs", values: department.values, color: COLORS.open }]}
        showValues
      />
      <BarChart
        title="CARs by source"
        orientation="horizontal"
        height={rowHeight(source.categories.length)}
        categories={source.categories}
        series={[{ name: "CARs", values: source.values, color: COLORS.open }]}
        showValues
      />
      <BarChart
        title="CARs by root cause"
        orientation="horizontal"
        height={rowHeight(rootCause.categories.length)}
        categories={rootCause.categories}
        series={[{ name: "CARs", values: rootCause.values, color: COLORS.neutral }]}
        showValues
      />
      <BarChart
        title="Repeat occurrences"
        description="CARs marked as a previous occurrence of the same problem."
        categories={repeat.categories}
        series={[{ name: "CARs", values: repeat.values, color: COLORS.cost }]}
        showValues
      />
      <BarChart
        title="Cost impact by department"
        description={
          cost.total === null
            ? "No CAR has a cost entered."
            : `${usd(cost.total, 0)} across ${cost.withCost} CARs with a cost entered; ${cost.withoutCost} have none (not counted as $0). ${cost.linkedToQualityCost} linked to a Quality Cost record.`
        }
        orientation="horizontal"
        height={rowHeight(costByDepartment.length)}
        categories={costByDepartment.map((d) => d.label)}
        series={[{ name: "Cost impact ($)", values: costByDepartment.map((d) => toNumber(d.total)), color: COLORS.cost }]}
        showValues
        className="xl:col-span-2"
      />
    </div>
  );
}

function RepeatCars({ data }: { data: CarDashboard }) {
  if (data.repeatCars.length === 0) return null;
  return (
    <TableSection id="car-repeat" title="Repeat CARs" description="Marked as a previous occurrence of the same problem.">
      <ul className="divide-y">
        {data.repeatCars.map((car) => (
          <li key={car.id} className="px-4 py-2 text-sm">
            <Link href={carHref(car.id)} className="font-medium text-primary hover:underline">
              {car.carNumber}
            </Link>{" "}
            {car.subject}
            {car.previousCar && <span className="text-muted-foreground"> · previous: {car.previousCar}</span>}
          </li>
        ))}
      </ul>
    </TableSection>
  );
}
