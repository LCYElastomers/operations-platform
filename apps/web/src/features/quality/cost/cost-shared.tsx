"use client";

import { AlertTriangle, ClipboardList } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { FilterBar, FilterSelect } from "@/components/common/filter-bar";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

import {
  describeCostError,
  NO_DIMENSIONS,
  type CoqClass,
  type CostDimensions,
  type CostRecord,
  type CostRecordOptions,
  type CostRecordQuery,
  type CostSummary,
  type CostSummaryQuery,
} from "./api";
import { ClassLabel, CostRecordDialog, FinancialBadge, StatusLabel, type CostDialogTarget } from "./record-dialog";
import { formatDate, MONTH_LABELS, periodDates, usd } from "./format";
import { useCostRecordOptions } from "./use-cost";

const MONTH_OPTIONS = MONTH_LABELS.map((label, index) => ({ value: String(index + 1), label }));

/** The dashboard filter state shared by KPIs, charts, the matrix and detail lists. */
export function useCostSummaryQuery(poorOnly: boolean) {
  return useState<CostSummaryQuery>({ year: null, from: null, through: null, poorOnly, ...NO_DIMENSIONS });
}

/** The Register query listing the records behind a dashboard's figures. */
export function periodRecordQuery(data: CostSummary, query: CostSummaryQuery, classes: CoqClass[] = []): CostRecordQuery {
  const { from, to } = periodDates(data);
  return {
    areaId: query.areaId,
    coqClass: query.coqClass,
    category: query.category,
    product: query.product,
    owner: query.owner,
    financialStatus: query.financialStatus,
    from,
    to,
    status: null,
    open: false,
    classes,
    search: "",
  };
}

export function classChoices(options: CostRecordOptions | undefined, classes?: CoqClass[]) {
  return (options?.classes ?? [])
    .filter((item) => !classes || classes.includes(item.code))
    .map((item) => ({ value: item.code, label: item.label }));
}

export function categoryChoices(options: CostRecordOptions | undefined, coqClass: CoqClass | null, classes?: CoqClass[]) {
  return (options?.classes ?? [])
    .filter((item) => (coqClass ? item.code === coqClass : !classes || classes.includes(item.code)))
    .flatMap((item) =>
      item.categories.map((category) => ({
        value: category.code,
        label: coqClass ? category.label : `${category.label} (${item.label})`,
      })),
    );
}

/** Area, class, category, product, owner and financial status: the filters every Quality Cost view shares. */
export function DimensionFilters({
  value,
  onChange,
  options,
  classes,
}: {
  value: CostDimensions;
  onChange: (value: CostDimensions) => void;
  options: CostRecordOptions | undefined;
  /** The classes the view covers (COPQ: the failure classes). */
  classes?: CoqClass[];
}) {
  return (
    <>
      <FilterSelect
        label="Area"
        options={(options?.areas ?? []).map((area) => ({ value: String(area.id), label: area.name }))}
        value={value.areaId === null ? "" : String(value.areaId)}
        onChange={(event) => onChange({ ...value, areaId: event.target.value ? Number(event.target.value) : null })}
        className="pointer-coarse:h-11"
      />
      <FilterSelect
        label="COQ class"
        options={classChoices(options, classes)}
        value={value.coqClass ?? ""}
        onChange={(event) =>
          onChange({ ...value, coqClass: (event.target.value || null) as CoqClass | null, category: "" })
        }
        className="pointer-coarse:h-11"
      />
      <FilterSelect
        label="Category"
        options={categoryChoices(options, value.coqClass, classes)}
        value={value.category}
        onChange={(event) => onChange({ ...value, category: event.target.value })}
        className="pointer-coarse:h-11"
      />
      <FilterSelect
        label="Product"
        options={(options?.products ?? []).map((product) => ({ value: product, label: product }))}
        value={value.product}
        onChange={(event) => onChange({ ...value, product: event.target.value })}
        className="pointer-coarse:h-11"
      />
      <FilterSelect
        label="Owner"
        options={(options?.owners ?? []).map((owner) => ({ value: owner, label: owner }))}
        value={value.owner}
        onChange={(event) => onChange({ ...value, owner: event.target.value })}
        className="pointer-coarse:h-11"
      />
      <FilterSelect
        label="Financial status"
        options={(options?.financialStatuses ?? []).map((item) => ({ value: item.code, label: item.label }))}
        value={value.financialStatus ?? ""}
        onChange={(event) =>
          onChange({ ...value, financialStatus: (event.target.value || null) as CostDimensions["financialStatus"] })
        }
        className="pointer-coarse:h-11"
      />
    </>
  );
}

export function isFiltered(value: CostDimensions) {
  return (
    value.areaId !== null ||
    value.coqClass !== null ||
    value.category !== "" ||
    value.product !== "" ||
    value.owner !== "" ||
    value.financialStatus !== null
  );
}

/** Period and dimension filters of the COPQ and COQ Matrix dashboards. */
export function CostFilters({
  query,
  onChange,
  data,
  fetching,
  classes,
}: {
  query: CostSummaryQuery;
  onChange: (query: CostSummaryQuery) => void;
  data: CostSummary | undefined;
  fetching: boolean;
  classes?: CoqClass[];
}) {
  const options = useCostRecordOptions();
  const years = [...new Set([...(data?.availableYears ?? []), ...(query.year !== null ? [query.year] : [])])].sort(
    (a, b) => b - a,
  );
  const latest = data?.latestMonth;
  return (
    <FilterBar
      actions={
        <>
          {fetching && (
            <StatusBadge tone="pending" pulse>
              Updating
            </StatusBadge>
          )}
          {(isFiltered(query) || query.year !== null || query.from !== null || query.through !== null) && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onChange({ ...query, year: null, from: null, through: null, ...NO_DIMENSIONS })}
            >
              Clear filters
            </Button>
          )}
        </>
      }
    >
      <FilterSelect
        label="Year"
        placeholder={data?.year ? `Latest (${data.year})` : "Latest"}
        options={years.map((value) => ({ value: String(value), label: String(value) }))}
        value={query.year === null ? "" : String(query.year)}
        onChange={(event) =>
          onChange({ ...query, year: event.target.value ? Number(event.target.value) : null, from: null, through: null })
        }
        className="pointer-coarse:h-11"
      />
      <FilterSelect
        label="From"
        placeholder="Jan"
        options={MONTH_OPTIONS}
        value={query.from === null ? "" : String(query.from)}
        onChange={(event) => onChange({ ...query, from: event.target.value ? Number(event.target.value) : null })}
        className="pointer-coarse:h-11"
      />
      <FilterSelect
        label="Through"
        placeholder={latest ? `Latest (${MONTH_LABELS[latest - 1]})` : "Latest"}
        options={MONTH_OPTIONS}
        value={query.through === null ? "" : String(query.through)}
        onChange={(event) => onChange({ ...query, through: event.target.value ? Number(event.target.value) : null })}
        className="pointer-coarse:h-11"
      />
      <DimensionFilters value={query} onChange={(value) => onChange({ ...query, ...value })} options={options.data} classes={classes} />
    </FilterBar>
  );
}

export function CostError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const accessDenied = error instanceof ApiError && (error.status === 401 || error.status === 403);
  return (
    <EmptyState
      icon={AlertTriangle}
      title={accessDenied ? "Cost of Quality data is not available to you" : "Could not load Cost of Quality data"}
      description={describeCostError(error)}
      action={
        accessDenied ? undefined : (
          <Button variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        )
      }
    />
  );
}

export function NoRecords({ filtered, action }: { filtered: boolean; action?: React.ReactNode }) {
  return (
    <EmptyState
      icon={ClipboardList}
      title={filtered ? "No quality cost items match these filters" : "No quality cost items yet"}
      description={
        filtered
          ? "Change or clear the filters to see more items."
          : "Figures appear here once items are added to the Quality Cost Register or imported from the reviewed COQ workbook mapping. Nothing is shown until then."
      }
      action={action}
    />
  );
}

/** A value cell with a data bar scaled to the largest value in its column. */
export function DataBar({ value, max, color, children }: { value: number | null; max: number; color: string; children: React.ReactNode }) {
  const width = value !== null && max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <span className="relative block min-w-24 rounded-sm">
      {width > 0 && (
        <span aria-hidden className="absolute inset-y-0 left-0 rounded-sm opacity-15" style={{ width: `${width}%`, backgroundColor: color }} />
      )}
      <span className="relative px-1">{children}</span>
    </span>
  );
}

export function NotEntered({ label = "Not entered" }: { label?: string }) {
  return <span className="text-xs text-muted-foreground">{label}</span>;
}

export const TH = "px-3 py-2 text-xs font-medium whitespace-nowrap text-muted-foreground first:pl-4";
export const TD = "px-3 py-2 first:pl-4";

export function TableSection({
  id,
  title,
  description,
  actions,
  children,
}: {
  id: string;
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="overflow-hidden rounded-lg border bg-card">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <h2 id={id} className="text-sm font-semibold">
            {title}
          </h2>
          {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
        </div>
        {actions}
      </header>
      {children}
    </section>
  );
}

const COLUMNS = [
  "Record ID",
  "Date",
  "Title",
  "Area",
  "COQ classification",
  "Category",
  "Product",
  "Lot",
  "Owner",
  "Financial status",
  "Total cost",
  "Recovered",
  "Net cost",
  "Status",
  "Days open",
] as const;

function Money({ value, muted }: { value: string | null; muted?: boolean }) {
  if (value === null) return <NotEntered label="—" />;
  return <span className={cn(muted && "text-muted-foreground italic")}>{usd(value, 2)}</span>;
}

/**
 * Quality Cost records as the Register lists them. A row opens the item's
 * detail. Potential and Validating amounts are shown muted and in italics:
 * they are exposure, not confirmed cost.
 */
export function RecordTable({ records, caption }: { records: CostRecord[]; caption: string }) {
  const [target, setTarget] = useState<CostDialogTarget | null>(null);
  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1500px] text-left text-sm tabular-nums">
          <caption className="sr-only">{caption}</caption>
          <thead className="border-b bg-muted/30">
            <tr>
              {COLUMNS.map((heading) => (
                <th key={heading} scope="col" className={TH}>
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {records.map((record) => (
              <tr
                key={record.id}
                onClick={() => setTarget({ kind: "view", id: record.id })}
                className="cursor-pointer border-b border-border/60 last:border-b-0 hover:bg-muted/40"
              >
                <td className={cn(TD, "whitespace-nowrap")}>
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      setTarget({ kind: "view", id: record.id });
                    }}
                    className="font-medium text-primary underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
                    aria-label={`Open ${record.recordNumber}: ${record.title}`}
                  >
                    {record.recordNumber}
                  </button>
                </td>
                <td className={cn(TD, "whitespace-nowrap")}>{formatDate(record.recordDate)}</td>
                <th scope="row" className={cn(TD, "max-w-72 truncate font-medium")} title={record.title}>
                  {record.title}
                  {record.source === "legacy_import" && (
                    <span className="ml-1.5 align-middle">
                      <StatusBadge tone="neutral">Imported</StatusBadge>
                    </span>
                  )}
                </th>
                <td className={TD}>{record.areaName ?? <NotEntered label="—" />}</td>
                <td className={TD}>
                  <ClassLabel record={record} />
                </td>
                <td className={cn(TD, "whitespace-nowrap")}>{record.categoryLabel}</td>
                <td className={TD}>{record.product ?? <NotEntered label="—" />}</td>
                <td className={TD}>{record.lot ?? <NotEntered label="—" />}</td>
                <td className={cn(TD, "whitespace-nowrap")}>{record.owner ?? <NotEntered label="—" />}</td>
                <td className={TD}>
                  <FinancialBadge record={record} />
                </td>
                <td className={cn(TD, "text-right")}>
                  <Money value={record.totalCost} muted={!record.costConfirmed} />
                </td>
                <td className={cn(TD, "text-right")}>
                  <Money value={record.recoveredCost} />
                </td>
                <td className={cn(TD, "text-right font-medium")}>
                  <Money value={record.netCost} muted={!record.costConfirmed} />
                </td>
                <td className={TD}>
                  <StatusLabel record={record} />
                </td>
                <td className={cn(TD, "text-right")}>{record.daysOpen}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <CostRecordDialog target={target} onClose={() => setTarget(null)} />
    </>
  );
}

export function DataChecks({ data }: { data: CostSummary }) {
  if (data.dataChecks.length === 0) return null;
  return (
    <section aria-labelledby="cost-checks" className="rounded-lg border bg-card px-4 py-3 text-sm">
      <h2 id="cost-checks" className="font-semibold">
        Data checks
      </h2>
      <p className="mt-0.5 text-xs text-muted-foreground">
        About the records behind these figures. Nothing is changed or filled in to make figures complete.
      </p>
      <ul className="mt-2 space-y-1.5">
        {data.dataChecks.map((check, index) => (
          <li key={index} className="flex items-start gap-2">
            <StatusBadge tone={check.status === "warning" ? "warning" : "info"}>
              {check.status === "warning" ? "Check" : "Note"}
            </StatusBadge>
            <span>{check.message}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Definitions({ data }: { data: CostSummary }) {
  return (
    <details className="rounded-lg border bg-card px-4 py-3 text-sm">
      <summary className="cursor-pointer font-semibold">Definitions</summary>
      <p className="mt-1 text-xs text-muted-foreground">From the Definitions sheet of the COQ workbook.</p>
      <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-[max-content_1fr]">
        {data.definitions.map((item) => (
          <div key={item.term} className="contents">
            <dt className="font-medium">{item.term}</dt>
            <dd className="text-muted-foreground">{item.definition}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
