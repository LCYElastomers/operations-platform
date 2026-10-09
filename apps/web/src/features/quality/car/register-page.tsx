"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useDeferredValue, useState } from "react";

import { FilterBar, FilterInput, FilterSelect } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { NotEntered, TableSection, TD, TH } from "../cost/cost-shared";
import { formatDate, usd } from "../cost/format";

import { carHref, carQueryParams, EMPTY_CAR_QUERY, type CarQuery, type CarSummary } from "./api";
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

function isFiltered(query: CarQuery) {
  return JSON.stringify(query) !== JSON.stringify(EMPTY_CAR_QUERY);
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

/**
 * Every Corrective Action Report, newest request first. The filters are kept
 * in the page URL so a dashboard figure can link to its CARs and the back
 * button returns to the same list.
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
  const options = useCarOptions();
  const [filters, setFiltersState] = useState<CarQuery>(initial);
  const query = { ...filters, search: useDeferredValue(filters.search) };
  const cars = useCars(query);
  const filtered = isFiltered(filters);
  const data = cars.data;

  const setFilters = (next: CarQuery) => {
    setFiltersState(next);
    const params = carQueryParams(next).toString();
    window.history.replaceState(null, "", params ? `?${params}` : window.location.pathname);
  };

  const choice = (key: keyof CarQuery, label: string, items: { value: string; label: string }[]) => (
    <FilterSelect
      label={label}
      options={items}
      value={filters[key] as string}
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
      <FilterBar
        actions={
          <>
            {cars.isFetching && !cars.isPending && (
              <StatusBadge tone="pending" pulse>
                Updating
              </StatusBadge>
            )}
            {filtered && (
              <Button variant="ghost" size="sm" onClick={() => setFilters(EMPTY_CAR_QUERY)}>
                Clear filters
              </Button>
            )}
          </>
        }
      >
        <FilterInput
          label="Search"
          type="search"
          placeholder="CAR number, subject, lot…"
          value={filters.search}
          onChange={(event) => setFilters({ ...filters, search: event.target.value })}
          className="pointer-coarse:h-11"
        />
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
        {choice("status", "CAR status", filterOptions(options.data?.carStatuses))}
        {choice("department", "Department", filterOptions(options.data?.departments))}
        {choice("source", "Source", filterOptions(options.data?.sources))}
        {choice(
          "assignedTo",
          "Assigned to",
          (options.data?.assignees ?? []).map((name) => ({ value: name, label: name })),
        )}
        {choice("rootCause", "Root cause", filterOptions(options.data?.rootCauses))}
        {choice("effectiveness", "Effectiveness", filterOptions(options.data?.effectivenessResults))}
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
      </FilterBar>
      {cars.isError ? (
        <CarError error={cars.error} onRetry={() => void cars.refetch()} />
      ) : cars.isPending ? (
        <p className="py-6 text-sm text-muted-foreground">Loading Corrective Action Reports…</p>
      ) : data && data.cars.length === 0 ? (
        <NoCars filtered={filtered} action={filtered || !data.abilities.create ? undefined : <NewCarLink />} />
      ) : (
        data && (
          <TableSection
            id="car-register"
            title="Corrective Action Reports"
            description={
              data.total > data.cars.length
                ? `Showing the newest ${data.cars.length.toLocaleString("en-US")} of ${carsLabel(data.total)}. Narrow the filters to see the rest.`
                : `${carsLabel(data.total)}, newest request first. Select a row to open the CAR.`
            }
          >
            <CarTable cars={data.cars} />
          </TableSection>
        )
      )}
    </div>
  );
}

export function CarTable({ cars }: { cars: CarSummary[] }) {
  const router = useRouter();
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1400px] text-left text-sm tabular-nums">
        <caption className="sr-only">Corrective Action Reports</caption>
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
