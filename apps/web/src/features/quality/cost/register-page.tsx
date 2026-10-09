"use client";

import { useDeferredValue, useState } from "react";

import { FilterBar, FilterInput, FilterSelect } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";

import { NO_DIMENSIONS, type CostRecordQuery, type OperationalStatus } from "./api";
import { CostError, DimensionFilters, isFiltered, NoRecords, RecordTable, TableSection } from "./cost-shared";
import { recordsLabel } from "./format";
import { AddCostRecordButton } from "./record-dialog";
import { useCostRecordOptions, useCostRecords } from "./use-cost";

const NO_FILTERS: CostRecordQuery = {
  ...NO_DIMENSIONS,
  from: "",
  to: "",
  status: null,
  open: false,
  classes: [],
  search: "",
};

/**
 * Every Quality Cost item (all four COQ classes) in one register. COPQ and
 * the COQ Matrix are calculated from these same records.
 */
export function CostRegisterPage({ title, description }: { title: string; description?: string }) {
  const options = useCostRecordOptions();
  const [filters, setFilters] = useState<CostRecordQuery>(NO_FILTERS);
  const query = { ...filters, search: useDeferredValue(filters.search) };
  const records = useCostRecords(query);
  const filtered =
    isFiltered(filters) || filters.from !== "" || filters.to !== "" || filters.status !== null || filters.search.trim() !== "";
  const data = records.data;
  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Quality · Cost of Quality"
        title={title}
        description={description}
        actions={<AddCostRecordButton />}
      />
      <FilterBar
        actions={
          <>
            {records.isFetching && !records.isPending && (
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
          label="Search"
          type="search"
          placeholder="ID, title, lot, customer…"
          value={filters.search}
          onChange={(event) => setFilters({ ...filters, search: event.target.value })}
          className="pointer-coarse:h-11"
        />
        <FilterInput
          label="Date from"
          type="date"
          value={filters.from}
          max={filters.to || undefined}
          onChange={(event) => setFilters({ ...filters, from: event.target.value })}
          className="pointer-coarse:h-11"
        />
        <FilterInput
          label="Date to"
          type="date"
          value={filters.to}
          min={filters.from || undefined}
          onChange={(event) => setFilters({ ...filters, to: event.target.value })}
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
      </FilterBar>
      {records.isError ? (
        <CostError error={records.error} onRetry={() => void records.refetch()} />
      ) : records.isPending ? (
        <p className="py-6 text-sm text-muted-foreground">Loading quality cost items…</p>
      ) : data && data.records.length === 0 ? (
        <NoRecords filtered={filtered} action={filtered ? undefined : <AddCostRecordButton />} />
      ) : (
        data && (
          <TableSection
            id="cost-register"
            title="Quality cost items"
            description={
              data.total > data.records.length
                ? `Showing the newest ${data.records.length.toLocaleString("en-US")} of ${recordsLabel(data.total)}. Narrow the filters to see the rest.`
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
