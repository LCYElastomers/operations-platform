"use client";

import { useDeferredValue } from "react";

import { DashboardToolbar } from "@/components/common/dashboard-toolbar";
import { ExportMenu } from "@/components/common/export-menu";
import { FilterInput, FilterSelect } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { PeriodFilter } from "@/components/common/period-filter";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { siteToday } from "@/features/safety/site-calendar";
import { useSiteToday } from "@/features/safety/use-site-calendar";
import { useUrlState } from "@/lib/use-url-state";

import type { OperationalStatus } from "./api";
import {
  costRegisterFromParams,
  costRegisterParams,
  costRegisterReportContext,
  EMPTY_COST_REGISTER,
  recordQueryOf,
  registerPeriodConfig,
  type CostRegisterQuery,
} from "./cost-query";
import { CostError, DimensionFilters, isFiltered, NoRecords, RecordTable, TableSection } from "./cost-shared";
import { recordsLabel } from "./format";
import { AddCostRecordButton } from "./record-dialog";
import { useCostRecordOptions, useCostRecords } from "./use-cost";

const writeQuery = (params: URLSearchParams, value: CostRegisterQuery) => {
  for (const key of [...params.keys()]) params.delete(key);
  costRegisterParams(value).forEach((v, k) => params.set(k, v));
};

/**
 * Every Quality Cost item (all four COQ classes) in one register. COPQ and
 * the COQ Matrix are calculated from these same records.
 */
export function CostRegisterPage({
  title,
  description,
  initial = EMPTY_COST_REGISTER,
}: {
  title: string;
  description?: string;
  initial?: CostRegisterQuery;
}) {
  const today = useSiteToday(siteToday());
  const options = useCostRecordOptions();
  const [filters, setQuery] = useUrlState<CostRegisterQuery>(initial, costRegisterFromParams, writeQuery);
  const setFilters = (next: CostRegisterQuery, replace = false) => setQuery(next, { replace });
  const records = useCostRecords(recordQueryOf({ ...filters, search: useDeferredValue(filters.search) }, today));
  const filtered = isFiltered(filters) || filters.period.mode !== "all" || filters.status !== null || filters.search.trim() !== "";
  const data = records.data;
  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Quality · Cost of Quality"
        title={title}
        description={description}
        actions={<AddCostRecordButton />}
      />
      <DashboardToolbar
        period={
          <PeriodFilter
            label="Item date"
            value={filters.period}
            onChange={(period) => setFilters({ ...filters, period })}
            today={today}
            config={registerPeriodConfig(today)}
          />
        }
        actions={
          <>
            {records.isFetching && !records.isPending && (
              <StatusBadge tone="pending" pulse>
                Updating
              </StatusBadge>
            )}
            {filtered && (
              <Button variant="ghost" size="sm" onClick={() => setFilters(EMPTY_COST_REGISTER)}>
                Clear filters
              </Button>
            )}
          </>
        }
        exportMenu={
          <ExportMenu
            reportKey="quality-cost-register"
            title="Quality Cost Register"
            formats={["xlsx"]}
            requires={["qualityCost.view", "qualityCost.export"]}
            disabled={!data}
            context={() => costRegisterReportContext(filters)}
          />
        }
      >
        <FilterInput
          label="Search"
          type="search"
          placeholder="ID, title, lot, customer…"
          value={filters.search}
          onChange={(event) => setFilters({ ...filters, search: event.target.value }, true)}
          className="pointer-coarse:h-11"
        />
        <DimensionFilters value={filters} onChange={(value) => setFilters({ ...filters, ...value })} options={options.data} />
        <FilterSelect
          label="Status"
          options={(options.data?.operationalStatuses ?? []).map((item) => ({ value: item.code, label: item.label }))}
          value={filters.status ?? ""}
          onChange={(event) => setFilters({ ...filters, status: (event.target.value || null) as OperationalStatus | null })}
          className="pointer-coarse:h-11"
        />
      </DashboardToolbar>
      {records.isError ? (
        <CostError error={records.error} onRetry={() => void records.refetch()} />
      ) : records.isPending ? (
        <p className="py-6 text-sm text-muted-foreground">Loading quality cost items…</p>
      ) : data && data.records.length === 0 ? (
        <NoRecords
          filtered={filtered}
          action={
            filtered ? (
              <Button variant="outline" size="sm" onClick={() => setFilters(EMPTY_COST_REGISTER)}>
                Clear filters
              </Button>
            ) : (
              <AddCostRecordButton />
            )
          }
        />
      ) : (
        data && (
          <TableSection
            id="cost-register"
            title="Quality cost items"
            description={
              data.total > data.records.length
                ? `Showing the newest ${data.records.length.toLocaleString("en-US")} of ${recordsLabel(data.total)}. Narrow the filters to see the rest; the Excel export has every item.`
                : `${recordsLabel(data.total)}, newest first. Select a row to open the item. Potential and Validating amounts are in italics: exposure, not confirmed cost.`
            }
          >
            <RecordTable records={data.records} caption="Quality cost items" />
          </TableSection>
        )
      )}
    </div>
  );
}
