"use client";

import { AlertTriangle, Droplets, FlaskConical, Hash, Palette, RotateCcw, SearchX, Tag } from "lucide-react";
import { useMemo } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { FilterBar, FilterInput, FilterSelect } from "@/components/common/filter-bar";
import { MetricCard } from "@/components/common/metric-card";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { TrendChart } from "@/components/common/trend-chart";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";

import { hasActiveFilters, type MoistureRecord } from "./api";
import { buildTrendSeries, formatSourceDate, MEASUREMENT_PRECISION } from "./format";
import { RecentMaterialsTable } from "./recent-materials-table";
import { useMoistureDashboard } from "./use-moisture-dashboard";

const NO_RECORDS: MoistureRecord[] = [];
// Full-width stacked trend cards; the plot area alone is taller than the card minimum.
const TREND_PLOT_HEIGHT = 340;
const TREND_CARD_CLASS = "w-full min-h-[375px]";

function describeError(error: unknown): string {
  if (error instanceof ApiError) return `The API responded with HTTP ${error.status}.`;
  return "The API could not be reached.";
}

function valueCountCaption(count: number | undefined): string | undefined {
  if (count === undefined) return undefined;
  if (count === 0) return "No values in view";
  return `Mean of ${count.toLocaleString()} value${count === 1 ? "" : "s"}`;
}

type MoistureDashboardProps = {
  title: string;
  description?: string;
};

export function MoistureDashboard({ title, description }: MoistureDashboardProps) {
  const {
    filters,
    setFilter,
    resetFilters,
    invalidDateRange,
    filterOptions,
    recent,
    trends,
    retry,
    dataSource,
    isUpdating,
  } = useMoistureDashboard();

  const options = filterOptions.data;
  const records = recent.data?.records ?? NO_RECORDS;
  const points = trends.data?.points ?? NO_RECORDS;
  const summary = trends.data?.summary;
  const latest = records[0];

  const dataLoading = recent.isPending || trends.isPending;
  const dataError = recent.error ?? trends.error;
  const filtersActive = hasActiveFilters(filters);

  const moistureSeries = useMemo(() => buildTrendSeries(points, "avgMoisture"), [points]);
  const colorSeries = useMemo(() => buildTrendSeries(points, "avgColor"), [points]);
  const bdSeries = useMemo(() => buildTrendSeries(points, "avgCombinedBd"), [points]);

  const unavailable = dataError ? "Unavailable" : undefined;

  const errorState = (
    <EmptyState
      variant="plain"
      icon={AlertTriangle}
      title="Could not load moisture data"
      description={describeError(dataError)}
      action={
        <Button variant="outline" size="sm" onClick={retry}>
          Retry
        </Button>
      }
    />
  );

  const noResultsState = filtersActive ? (
    <EmptyState
      variant="plain"
      icon={SearchX}
      title="No records match these filters"
      description="Adjust or reset the filters to see more records."
      action={
        <Button variant="outline" size="sm" onClick={resetFilters}>
          <RotateCcw />
          Reset filters
        </Button>
      }
    />
  ) : (
    <EmptyState
      variant="plain"
      icon={Droplets}
      title="No moisture records"
      description="The data source returned no records."
    />
  );

  const chartEmptyState = dataError ? (
    errorState
  ) : (
    <EmptyState
      variant="plain"
      icon={SearchX}
      title="No values to chart"
      description={
        points.length > 0
          ? "Matching records have no values for this measurement."
          : "No records match the current filters."
      }
    />
  );

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Quality · Raw Materials"
        title={title}
        description={description}
        status={
          dataSource?.isFixture ? (
            <StatusBadge tone="warning">Development fixture</StatusBadge>
          ) : undefined
        }
      />

      {dataSource?.isFixture && (
        <div
          role="note"
          className="flex items-start gap-3 rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />
          <p>
            <span className="font-medium">{dataSource.label}</span>{" "}
            <span className="text-muted-foreground">
              Records are synthetic and shaped like the source query. Do not use them for
              quality decisions.
            </span>
          </p>
        </div>
      )}

      <div className="space-y-2">
        <FilterBar
          actions={
            <>
              {isUpdating && (
                <StatusBadge tone="pending" pulse>
                  Updating
                </StatusBadge>
              )}
              <Button
                variant="outline"
                onClick={resetFilters}
                disabled={!filtersActive}
                aria-label="Reset filters"
              >
                <RotateCcw />
                Reset Filters
              </Button>
            </>
          }
        >
          <FilterSelect
            label="Product"
            placeholder="All products"
            options={(options?.products ?? []).map((value) => ({ value, label: value }))}
            value={filters.product}
            onChange={(event) => setFilter("product", event.target.value)}
            disabled={!options}
          />
          <FilterInput
            label="Lot / campaign"
            type="search"
            placeholder="Search lot or campaign"
            maxLength={100}
            autoComplete="off"
            value={filters.search}
            onChange={(event) => setFilter("search", event.target.value)}
          />
          <FilterSelect
            label="Location"
            placeholder="All locations"
            options={(options?.locations ?? []).map((value) => ({ value, label: value }))}
            value={filters.location}
            onChange={(event) => setFilter("location", event.target.value)}
            disabled={!options}
          />
          <FilterInput
            label="Start date"
            type="date"
            min={options?.dateRange.min ?? undefined}
            max={filters.endDate || options?.dateRange.max || undefined}
            value={filters.startDate}
            onChange={(event) => setFilter("startDate", event.target.value)}
            aria-invalid={invalidDateRange || undefined}
          />
          <FilterInput
            label="End date"
            type="date"
            min={filters.startDate || options?.dateRange.min || undefined}
            max={options?.dateRange.max ?? undefined}
            value={filters.endDate}
            onChange={(event) => setFilter("endDate", event.target.value)}
            aria-invalid={invalidDateRange || undefined}
          />
        </FilterBar>
        {invalidDateRange && (
          <p role="alert" className="px-1 text-sm text-destructive">
            Start date must be on or before end date. Results are not updated until the range is
            valid.
          </p>
        )}
        {filterOptions.isError && (
          <p role="alert" className="px-1 text-sm text-destructive">
            Filter options could not be loaded. {describeError(filterOptions.error)}
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <MetricCard
          label="Records in view"
          value={summary?.recordCount ?? null}
          caption={unavailable ?? "Matching current filters"}
          icon={FlaskConical}
          loading={trends.isPending && !trends.isError}
        />
        <MetricCard
          label="Latest product"
          value={latest?.product ?? null}
          caption={unavailable ?? (latest ? formatSourceDate(latest.date) : undefined)}
          icon={Tag}
          loading={recent.isPending && !recent.isError}
        />
        <MetricCard
          label="Latest lot"
          value={latest?.lot ?? null}
          caption={
            unavailable ??
            (latest?.campaignNo ? `Campaign ${latest.campaignNo}` : latest ? "No campaign" : undefined)
          }
          icon={Hash}
          loading={recent.isPending && !recent.isError}
        />
        <MetricCard
          label="Average moisture"
          value={summary?.avgMoisture ?? null}
          precision={MEASUREMENT_PRECISION.avgMoisture}
          caption={unavailable ?? valueCountCaption(summary?.moistureValueCount)}
          icon={Droplets}
          loading={trends.isPending && !trends.isError}
        />
        <MetricCard
          label="Average color"
          value={summary?.avgColor ?? null}
          precision={MEASUREMENT_PRECISION.avgColor}
          caption={unavailable ?? valueCountCaption(summary?.colorValueCount)}
          icon={Palette}
          loading={trends.isPending && !trends.isError}
        />
      </div>

      <section aria-labelledby="recent-materials-heading" className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="recent-materials-heading" className="text-sm font-semibold">
            Recent materials
          </h2>
          {recent.data && (
            <p className="text-xs text-muted-foreground">
              {recent.data.totalMatching === 0
                ? "No matching records"
                : `Newest ${records.length.toLocaleString()} of ${recent.data.totalMatching.toLocaleString()} matching records`}
            </p>
          )}
        </div>
        <RecentMaterialsTable
          records={recent.isError ? NO_RECORDS : records}
          loading={recent.isPending && !recent.isError}
          emptyState={recent.isError ? errorState : noResultsState}
        />
      </section>

      <section aria-label="Trends" className="flex flex-col gap-5">
        <TrendChart
          title="Moisture Trend"
          description="Average moisture by date, per product"
          series={trends.isError ? [] : moistureSeries}
          precision={MEASUREMENT_PRECISION.avgMoisture}
          height={TREND_PLOT_HEIGHT}
          className={TREND_CARD_CLASS}
          loading={trends.isPending && !trends.isError}
          emptyState={chartEmptyState}
        />
        <TrendChart
          title="Color Trend"
          description="Average color by date, per product"
          series={trends.isError ? [] : colorSeries}
          precision={MEASUREMENT_PRECISION.avgColor}
          height={TREND_PLOT_HEIGHT}
          className={TREND_CARD_CLASS}
          loading={trends.isPending && !trends.isError}
          emptyState={chartEmptyState}
        />
        <TrendChart
          title="Combined BD Trend"
          description="Average combined BD by date, per product"
          series={trends.isError ? [] : bdSeries}
          precision={MEASUREMENT_PRECISION.avgCombinedBd}
          height={TREND_PLOT_HEIGHT}
          className={TREND_CARD_CLASS}
          loading={trends.isPending && !trends.isError}
          emptyState={chartEmptyState}
        />
      </section>

      {dataLoading && <span className="sr-only">Loading moisture data</span>}
    </div>
  );
}
