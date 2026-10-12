"use client";

import { ArrowDown, ArrowUp, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useDeferredValue } from "react";

import { ActiveFilters, type FilterChip } from "@/components/common/active-filters";
import { DashboardToolbar } from "@/components/common/dashboard-toolbar";
import { ExportMenu } from "@/components/common/export-menu";
import { FilterInput, FilterSelect } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { PeriodFilter } from "@/components/common/period-filter";
import { StatusBadge } from "@/components/common/status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { siteToday } from "@/features/safety/site-calendar";
import { useSiteToday } from "@/features/safety/use-site-calendar";
import { MIN_YEAR, resolvePeriod, yearsSince, type PeriodConfig } from "@/lib/period";
import { useUrlState } from "@/lib/use-url-state";
import { cn } from "@/lib/utils";

import { NotEntered, TableSection, TD, TH } from "../cost/cost-shared";
import { formatDate, usd } from "../cost/format";

import {
  ALL_DATES,
  CAR_PAGE_SIZE,
  carExportFilters,
  carHref,
  carQueryFromParams,
  carQueryParams,
  EMPTY_CAR_QUERY,
  type CarQuery,
  type CarSort,
  type CarSummary,
} from "./api";
import {
  ActionProgressLabel,
  CarError,
  CarStatusBadge,
  DueBadge,
  EffectivenessBadge,
  filterOptions,
  NoCars,
} from "./car-shared";
import { useCarOptions, useCars } from "./use-car";

export function NewCarLink({ className }: { className?: string }) {
  return (
    <Link href="/quality/cars/new" className={buttonVariants({ className: cn("pointer-coarse:h-11", className) })}>
      <Plus />
      New CAR
    </Link>
  );
}

function carsLabel(count: number) {
  return `${count.toLocaleString("en-US")} ${count === 1 ? "CAR" : "CARs"}`;
}

/** Filters only: sort and page are how the list is read, not what it holds. */
function criteria(query: CarQuery) {
  return JSON.stringify({ ...query, sort: undefined, page: undefined });
}

function isFiltered(query: CarQuery) {
  return criteria(query) !== criteria(EMPTY_CAR_QUERY);
}

/** Request-date periods offered by the register and the CAR dashboard. */
export function carPeriodConfig(today: string): PeriodConfig {
  return {
    presets: ["all", "this-month", "last-month", "ytd", "last-3-months", "last-6-months", "this-year"],
    browse: "year-month",
    custom: true,
    years: yearsSince(MIN_YEAR, today),
  };
}

const COLUMNS = [
  "CAR Number",
  "Request Date",
  "Subject",
  "Department",
  "Source",
  "Assigned To",
  "Due Date",
  "CAR Status",
  "Actions",
  "Effectiveness",
  "Days Open",
  "Cost Impact",
] as const;

type QuickView = { id: string; label: string; query: CarQuery };

/** Each quick view starts from a clean filter set. */
const QUICK_VIEWS: QuickView[] = [
  { id: "all", label: "All", query: EMPTY_CAR_QUERY },
  { id: "open", label: "Open", query: { ...EMPTY_CAR_QUERY, status: "open" } },
  { id: "past-due", label: "Past Due", query: { ...EMPTY_CAR_QUERY, pastDue: true } },
  { id: "due-soon", label: "Due Soon", query: { ...EMPTY_CAR_QUERY, dueSoon: true } },
  { id: "mine", label: "Mine", query: { ...EMPTY_CAR_QUERY, mine: true } },
  { id: "this-month", label: "This Month", query: { ...EMPTY_CAR_QUERY, period: { mode: "this-month" } } },
  { id: "closed", label: "Closed", query: { ...EMPTY_CAR_QUERY, status: "closed" } },
];

const writeQuery = (params: URLSearchParams, value: CarQuery) => {
  for (const key of [...params.keys()]) params.delete(key);
  carQueryParams(value).forEach((v, k) => params.set(k, v));
};
const readQuery = (params: URLSearchParams) => carQueryFromParams(Object.fromEntries(params));

/**
 * Every Corrective Action Report, newest request first. The period, filters,
 * sort and page are kept in the page URL so a dashboard figure can link to its
 * CARs, a view can be bookmarked and Back / Forward step through changes.
 */
export function CarRegisterPage({
  title,
  description,
  initial,
}: {
  title: string;
  description?: string;
  initial: CarQuery;
}) {
  const today = useSiteToday(siteToday());
  const options = useCarOptions();
  const [filters, setQuery] = useUrlState<CarQuery>(initial, readQuery, writeQuery);
  const query = { ...filters, search: useDeferredValue(filters.search) };
  const cars = useCars(query, today);
  const filtered = isFiltered(filters);
  const data = cars.data;
  const period = resolvePeriod(filters.period, today);

  /** A filter change returns to the first page. */
  const setFilters = (next: CarQuery, replace = false) => setQuery({ ...next, page: 1 }, { replace });
  const clear = () => setFilters({ ...EMPTY_CAR_QUERY, sort: filters.sort });

  const lists = {
    status: filterOptions(options.data?.carStatuses),
    department: filterOptions(options.data?.departments),
    source: filterOptions(options.data?.sources),
    assignedTo: (options.data?.assignees ?? []).map((name) => ({ value: name, label: name })),
    rootCause: filterOptions(options.data?.rootCauses),
    effectiveness: filterOptions(options.data?.effectivenessResults),
  };
  const labelOf = (key: keyof typeof lists) => lists[key].find((item) => item.value === filters[key])?.label ?? filters[key];

  const chips: FilterChip[] = [];
  const chip = (key: string, label: string, reset: Partial<CarQuery>) =>
    chips.push({ key, label, onRemove: () => setFilters({ ...filters, ...reset }) });
  if (filters.period.mode !== "all") chip("period", `Requested: ${period?.fullLabel ?? "invalid period"}`, { period: ALL_DATES });
  if (filters.search.trim()) chip("search", `Search: “${filters.search.trim()}”`, { search: "" });
  if (filters.status) chip("status", `Status: ${labelOf("status")}`, { status: "" });
  if (filters.department) chip("department", `Department: ${labelOf("department")}`, { department: "" });
  if (filters.source) chip("source", `Source: ${labelOf("source")}`, { source: "" });
  if (filters.assignedTo) chip("assignedTo", `Assigned to: ${filters.assignedTo}`, { assignedTo: "" });
  if (filters.mine) chip("mine", "Assigned to me", { mine: false });
  if (filters.rootCause) chip("rootCause", `Root cause: ${labelOf("rootCause")}`, { rootCause: "" });
  if (filters.effectiveness) chip("effectiveness", `Effectiveness: ${labelOf("effectiveness")}`, { effectiveness: "" });
  if (filters.pastDue) chip("pastDue", "Past due", { pastDue: false });
  if (filters.dueSoon) chip("dueSoon", "Due soon", { dueSoon: false });
  if (filters.repeat) chip("repeat", filters.repeat === "yes" ? "Repeat occurrence" : "Not a repeat", { repeat: "" });

  const activeView = QUICK_VIEWS.find((view) => criteria(view.query) === criteria(filters))?.id;
  const pages = data ? Math.max(1, Math.ceil(data.total / CAR_PAGE_SIZE)) : 1;
  const first = (filters.page - 1) * CAR_PAGE_SIZE + 1;

  const choice = (key: keyof typeof lists, label: string) => (
    <FilterSelect
      label={label}
      options={lists[key]}
      value={filters[key]}
      onChange={(event) => setFilters({ ...filters, [key]: event.target.value })}
      className="pointer-coarse:h-11"
    />
  );

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Quality · Corrective Action Reports"
        title={title}
        description={description}
        actions={options.data?.abilities.create ? <NewCarLink /> : undefined}
      />
      <nav aria-label="Quick views" className="-mx-1 overflow-x-auto px-1">
        <ul className="flex w-max gap-1 rounded-lg border bg-muted/40 p-1">
          {QUICK_VIEWS.map((view) => (
            <li key={view.id}>
              <button
                type="button"
                aria-pressed={activeView === view.id}
                onClick={() => setFilters({ ...view.query, sort: filters.sort })}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none pointer-coarse:py-2.5",
                  activeView === view.id && "bg-card text-foreground shadow-sm",
                )}
              >
                {view.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>
      <DashboardToolbar
        period={
          <PeriodFilter
            label="Request date"
            hint="by request date"
            value={filters.period}
            onChange={(next) => setFilters({ ...filters, period: next })}
            today={today}
            config={carPeriodConfig(today)}
          />
        }
        actions={
          cars.isFetching &&
          !cars.isPending && (
            <StatusBadge tone="pending" pulse>
              Updating
            </StatusBadge>
          )
        }
        exportMenu={
          <ExportMenu
            reportKey="car-register"
            title="CAR Register"
            formats={["xlsx"]}
            requires={["car.view", "car.export"]}
            disabled={!data}
            context={() => ({ period: filters.period, filters: carExportFilters(filters) })}
          />
        }
      >
        <FilterInput
          label="Search"
          type="search"
          placeholder="CAR number, subject, lot…"
          value={filters.search}
          onChange={(event) => setFilters({ ...filters, search: event.target.value }, true)}
          className="pointer-coarse:h-11"
        />
        {choice("status", "CAR status")}
        {choice("department", "Department")}
        {choice("source", "Source")}
        {choice("assignedTo", "Assigned to")}
        {choice("rootCause", "Root cause")}
        {choice("effectiveness", "Effectiveness")}
        <FilterSelect
          label="Past due"
          options={[{ value: "true", label: "Past due only" }]}
          value={filters.pastDue ? "true" : ""}
          onChange={(event) => setFilters({ ...filters, pastDue: event.target.value === "true" })}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Previous / repeat"
          options={[
            { value: "yes", label: "Repeat occurrence" },
            { value: "no", label: "Not a repeat" },
          ]}
          value={filters.repeat}
          onChange={(event) => setFilters({ ...filters, repeat: event.target.value as CarQuery["repeat"] })}
          className="pointer-coarse:h-11"
        />
      </DashboardToolbar>
      <ActiveFilters chips={chips} onClearAll={clear} />
      {cars.isError ? (
        <CarError error={cars.error} onRetry={() => void cars.refetch()} />
      ) : cars.isPending ? (
        <p className="py-6 text-sm text-muted-foreground">Loading Corrective Action Reports…</p>
      ) : data && data.cars.length === 0 ? (
        <NoCars
          filtered={filtered}
          action={
            filtered ? (
              <Button variant="outline" size="sm" onClick={clear}>
                Clear filters
              </Button>
            ) : data.abilities.create ? (
              <NewCarLink />
            ) : undefined
          }
        />
      ) : (
        data && (
          <TableSection
            id="car-register"
            title="Corrective Action Reports"
            description={`${carsLabel(data.total)}${period && period.mode !== "all" ? ` requested ${period.fullLabel}` : ""}, ${
              filters.sort === "oldest" ? "oldest" : "newest"
            } request first. Select a row to open the CAR.`}
          >
            <CarTable
              cars={data.cars}
              sort={filters.sort}
              onSort={(sort) => setQuery({ ...filters, sort, page: 1 })}
            />
            {data.total > CAR_PAGE_SIZE && (
              <nav aria-label="Register pages" className="flex flex-wrap items-center justify-between gap-2 border-t px-4 py-3 text-sm">
                <p className="text-muted-foreground" aria-live="polite">
                  {first.toLocaleString("en-US")}–{(first + data.cars.length - 1).toLocaleString("en-US")} of{" "}
                  {carsLabel(data.total)} · Page {filters.page} of {pages}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={filters.page <= 1}
                    onClick={() => setQuery({ ...filters, page: filters.page - 1 })}
                    className="pointer-coarse:h-11"
                  >
                    Previous
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={filters.page >= pages}
                    onClick={() => setQuery({ ...filters, page: filters.page + 1 })}
                    className="pointer-coarse:h-11"
                  >
                    Next
                  </Button>
                </div>
              </nav>
            )}
          </TableSection>
        )
      )}
    </div>
  );
}

/**
 * The CAR table. With `onSort` the Request Date heading sorts newest / oldest
 * first (the server sorts, so every page follows the same order).
 */
export function CarTable({
  cars,
  sort = "newest",
  onSort,
}: {
  cars: CarSummary[];
  sort?: CarSort;
  onSort?: (sort: CarSort) => void;
}) {
  const router = useRouter();
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1400px] text-left text-sm tabular-nums">
        <caption className="sr-only">Corrective Action Reports</caption>
        <thead className="border-b bg-muted/30">
          <tr>
            {COLUMNS.map((heading) =>
              heading === "Request Date" && onSort ? (
                <th key={heading} scope="col" className={TH} aria-sort={sort === "oldest" ? "ascending" : "descending"}>
                  <button
                    type="button"
                    onClick={() => onSort(sort === "oldest" ? "newest" : "oldest")}
                    className="inline-flex items-center gap-1 rounded-sm hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
                  >
                    {heading}
                    {sort === "oldest" ? <ArrowUp aria-hidden className="size-3.5" /> : <ArrowDown aria-hidden className="size-3.5" />}
                    <span className="sr-only">
                      , {sort === "oldest" ? "oldest first" : "newest first"}. Select to show{" "}
                      {sort === "oldest" ? "newest" : "oldest"} first.
                    </span>
                  </button>
                </th>
              ) : (
                <th key={heading} scope="col" className={TH}>
                  {heading}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {cars.map((car) => (
            <tr
              key={car.id}
              onClick={() => router.push(carHref(car.id))}
              className="cursor-pointer border-b border-border/60 last:border-b-0 hover:bg-muted/40"
            >
              <td className={cn(TD, "whitespace-nowrap")}>
                <Link
                  href={carHref(car.id)}
                  onClick={(event) => event.stopPropagation()}
                  className="font-medium text-primary underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
                  aria-label={`Open ${car.carNumber}: ${car.subject}`}
                >
                  {car.carNumber}
                </Link>
              </td>
              <td className={cn(TD, "whitespace-nowrap")}>{formatDate(car.requestDate)}</td>
              <th scope="row" className={cn(TD, "max-w-72 font-medium")}>
                <span className="block truncate" title={car.subject}>
                  {car.subject}
                </span>
                <span className="mt-0.5 flex flex-wrap gap-1">
                  {car.previousOccurrence && <StatusBadge tone="warning">Repeat</StatusBadge>}
                  {car.source === "legacy_import" && <StatusBadge tone="neutral">Imported</StatusBadge>}
                </span>
              </th>
              <td className={TD}>{car.departmentLabel ?? <NotEntered label="—" />}</td>
              <td className={TD}>{car.sourceLabel ?? <NotEntered label="—" />}</td>
              <td className={cn(TD, "whitespace-nowrap")}>{car.assignedTo ?? <NotEntered label="—" />}</td>
              <td className={cn(TD, "whitespace-nowrap")}>
                {car.dueDate ? formatDate(car.dueDate) : <NotEntered label="—" />}
              </td>
              <td className={TD}>
                <span className="flex flex-wrap items-center gap-1">
                  <CarStatusBadge car={car} />
                  <DueBadge car={car} />
                </span>
              </td>
              <td className={TD}>
                <ActionProgressLabel car={car} />
              </td>
              <td className={TD}>
                <EffectivenessBadge car={car} />
              </td>
              <td className={cn(TD, "text-right")}>{car.daysOpen}</td>
              <td className={cn(TD, "text-right")}>
                {car.totalCost === null ? <NotEntered label="—" /> : usd(car.totalCost, 2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
