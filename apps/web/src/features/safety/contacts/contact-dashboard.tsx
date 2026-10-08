"use client";

import { AlertTriangle, CalendarDays, Percent, UserRoundCheck, Users } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { BarChart } from "@/components/common/bar-chart";
import { DataTable, type DataTableColumn } from "@/components/common/data-table";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { MetricCard } from "@/components/common/metric-card";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { TrendChart } from "@/components/common/trend-chart";
import { Button, buttonVariants } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";

import { MONTH_LABELS } from "../incidents/grid";
import { ReportingYearSelect } from "../incidents/reporting-year-select";
import { monthName } from "../observations/observation-data";
import { yearOf } from "../site-calendar";
import { useAutomaticValue, useSiteToday } from "../use-site-calendar";
import { describeContactError, type ContactDashboardResponse } from "./api";
import {
  contactsByMonth,
  countAxis,
  FIRST_CONTACT_YEAR,
  formatParticipation,
  formatRate,
  headlineMonth,
  participationByMonth,
  runningContactTotal,
} from "./contact-data";
import { useContactDashboard } from "./use-contacts";

const CHART_HEIGHT = 320;

type SupervisorRow = ContactDashboardResponse["supervisors"][number];

/** Supervisor | Jan..Dec | YTD. Rows stay alphabetical: the table is never sortable. */
export const supervisorMonthColumns: DataTableColumn<SupervisorRow>[] = [
  {
    accessorKey: "displayName",
    header: "Supervisor",
    cell: ({ row }) => (
      <span className="font-medium">
        {row.original.displayName}
        {!row.original.active && <span className="ml-2 text-xs font-normal text-muted-foreground">Inactive</span>}
      </span>
    ),
  },
  ...MONTH_LABELS.map(
    (label, index): DataTableColumn<SupervisorRow> => ({
      id: `month-${index + 1}`,
      header: label,
      accessorFn: (row) => row.monthly[index],
    }),
  ),
  { accessorKey: "total", header: "YTD", cell: ({ row }) => <span className="font-semibold">{row.original.total}</span> },
];

type ContactDashboardProps = {
  title: string;
  description?: string;
  /** The Baytown date when the page was rendered on the server. */
  siteToday: string;
};

export function ContactDashboard({ title, description, siteToday }: ContactDashboardProps) {
  const today = useSiteToday(siteToday);
  const currentYear = yearOf(today);
  const yearChoice = useAutomaticValue(currentYear);
  const year = yearChoice.value;
  const dashboard = useContactDashboard(year);
  const data = dashboard.data;
  const loading = dashboard.isPending && !dashboard.isError;
  const failed = dashboard.isError;

  const monthly = useMemo(() => contactsByMonth(data), [data]);
  const participating = useMemo(() => participationByMonth(data), [data]);
  const running = useMemo(() => runningContactTotal(data, today), [data, today]);
  const runningAxis = useMemo(() => countAxis(running), [running]);
  const headline = headlineMonth(data);

  const accessDenied =
    dashboard.error instanceof ApiError &&
    (dashboard.error.status === 401 || dashboard.error.status === 403);
  const errorState = (
    <EmptyState
      variant="plain"
      icon={AlertTriangle}
      title={accessDenied ? "Safety data is not available to you" : "Could not load Safety data"}
      description={describeContactError(dashboard.error)}
      action={
        accessDenied ? undefined : (
          <Button variant="outline" size="sm" onClick={() => void dashboard.refetch()}>
            Retry
          </Button>
        )
      }
    />
  );

  const through = data?.throughMonth ?? 0;
  const yearCaption = failed
    ? "Unavailable"
    : through === 0
      ? `${year} has not started`
      : through === 12
        ? `Jan–Dec ${year}`
        : `Jan–${MONTH_LABELS[through - 1]} ${year} (to date)`;
  const isCurrentYear = year === Number(today.slice(0, 4));
  const monthLabel = headline ? `${monthName(headline.month)} ${year}` : null;
  const monthCaption = failed ? "Unavailable" : monthLabel ? (isCurrentYear ? `${monthLabel} (to date)` : monthLabel) : `${year} has not started`;
  const participation = headline?.participation ?? null;
  const empty = !failed && data !== undefined && data.contacts === 0;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Safety · Supervisor Safety Contacts"
        title={title}
        description={description}
        actions={
          <Link
            href="/safety/contacts"
            className={buttonVariants({ variant: "outline", className: "pointer-coarse:h-11" })}
          >
            <UserRoundCheck />
            Open contacts
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
          <ReportingYearSelect
            year={year}
            onChange={yearChoice.choose}
            currentYear={currentYear}
            firstYear={FIRST_CONTACT_YEAR}
            yearsWithData={data?.yearsWithData}
          />
        </div>
      </FilterBar>

      <section aria-label="Headline figures" className="space-y-2">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Contacts YTD" value={failed ? null : (data?.contacts ?? null)} caption={yearCaption} icon={CalendarDays} emphasis loading={loading} />
          <MetricCard
            label={isCurrentYear || !headline ? "Contacts this month" : `Contacts in ${monthName(headline.month)}`}
            value={failed ? null : (headline?.contacts ?? null)}
            caption={monthCaption}
            icon={UserRoundCheck}
            emphasis
            loading={loading}
          />
          <MetricCard
            label={
              isCurrentYear || !headline
                ? "Participating supervisors this month"
                : `Participating supervisors, ${monthName(headline.month)}`
            }
            value={failed ? null : formatParticipation(participation)}
            caption={failed ? "Unavailable" : participation ? `${monthCaption}; eligible supervisors with a contact` : monthCaption}
            icon={Users}
            emphasis
            loading={loading}
          />
          <MetricCard
            label="Participation"
            value={failed ? null : formatRate(participation?.rate ?? null)}
            caption={
              failed
                ? "Unavailable"
                : participation && participation.eligible > 0
                  ? `${participation.participating} ÷ ${participation.eligible} eligible, ${monthLabel}`
                  : "No eligible supervisors"
            }
            icon={Percent}
            emphasis
            loading={loading}
          />
        </div>
        <p className="px-1 text-xs text-muted-foreground">
          Every figure counts individual contact records. Participation for a month is the number of eligible
          supervisors with at least one contact, out of the supervisors eligible for that month (marked eligible,
          with effective dates overlapping the month). No targets are applied. Legacy workbook tallies are not
          included.
        </p>
      </section>

      {empty && (
        <EmptyState
          icon={UserRoundCheck}
          title={`No contacts recorded for ${year}`}
          description="Charts fill in as contacts are recorded on the Contacts page."
        />
      )}

      <section aria-label="Charts" className="grid grid-cols-1 gap-5 min-[1440px]:grid-cols-2">
        <BarChart
          title="Contacts by Month"
          description={`Contacts recorded per month, ${year}. Months that have not started show no bar.`}
          categories={MONTH_LABELS}
          series={failed ? [] : monthly}
          height={CHART_HEIGHT}
          showValues
          loading={loading}
          emptyState={failed ? errorState : undefined}
        />
        <BarChart
          title="Participating Supervisors by Month"
          description={`Eligible supervisors with at least one contact, beside the number eligible, ${year}.`}
          categories={MONTH_LABELS}
          series={failed ? [] : participating}
          height={CHART_HEIGHT}
          showValues
          loading={loading}
          emptyState={failed ? errorState : undefined}
        />
        <TrendChart
          title="Running Contact Total"
          description={`Cumulative contacts through each month end, ${year}; the current month is to date.`}
          series={failed ? [] : running}
          precision={0}
          yAxisRange={runningAxis}
          height={CHART_HEIGHT}
          loading={loading}
          emptyState={failed ? errorState : undefined}
          className="min-[1440px]:col-span-2"
        />
      </section>

      <section aria-labelledby="supervisor-month-heading" className="space-y-2">
        <h2 id="supervisor-month-heading" className="text-base font-semibold">
          Contacts by Supervisor and Month, {year}
        </h2>
        <p className="text-sm text-muted-foreground">
          Alphabetical. Includes supervisors in the program during {year} and anyone with contacts in it. A dash marks
          a month that has not started.
        </p>
        {failed ? (
          <div className="rounded-lg border bg-card">{errorState}</div>
        ) : (
          <DataTable
            columns={supervisorMonthColumns}
            data={data?.supervisors ?? []}
            loading={loading}
            enableSorting={false}
            caption={`Contacts by supervisor and month, ${year}`}
            emptyState={<EmptyState variant="plain" icon={Users} title={`No supervisors in the program in ${year}`} />}
          />
        )}
      </section>

      {loading && <span className="sr-only">Loading Safety data</span>}
    </div>
  );
}
