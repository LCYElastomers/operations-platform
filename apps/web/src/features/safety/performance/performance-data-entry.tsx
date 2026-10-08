"use client";

import { AlertTriangle, ChartColumn, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { FilterBar, FilterSelect } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge, type StatusTone } from "@/components/common/status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";

import { reportingYearOptions } from "../incidents/grid";
import { yearOf } from "../site-calendar";
import { useAutomaticValue, useSiteToday } from "../use-site-calendar";
import { monthName } from "../observations/observation-data";
import {
  describePerformanceError,
  isEditConflict,
  type CountSource,
  type MonthCounts,
  type MonthStatus,
  type PerformanceMonth,
} from "./api";
import {
  checkDraft,
  draftFromMonth,
  formatHours,
  parseHours,
  STATUS_LABELS,
  type HoursDraft,
} from "./performance-data";
import { useChangeMonth, usePerformanceMonths } from "./use-performance";

const STATUS_TONES: Record<MonthStatus, StatusTone> = {
  not_reported: "neutral",
  reported: "info",
  closed: "success",
};

/** Hours years reach back before Incident & Near Miss, so any recent year is offered. */
const FIRST_HOURS_YEAR = 2000;

type CountRow = { label: string; value: number | null };

function countRows(counts: MonthCounts, source: CountSource): CountRow[] {
  if (source === "performance_legacy") {
    return [
      { label: "Recordable injuries & illnesses", value: counts.trir },
      { label: "First Aid", value: counts.firstAid },
      { label: "LOPC", value: counts.lopc },
      { label: "Property & Equipment Damage", value: counts.propertyEquipmentDamage },
    ];
  }
  return [
    { label: "Recordable injuries", value: counts.recordableInjury },
    { label: "Occupational illnesses", value: counts.occupationalIllness },
    { label: "First Aid", value: counts.firstAid },
    { label: "LOPC", value: counts.lopc },
    { label: "Property damage", value: counts.propertyDamage },
    { label: "Equipment damage / failure", value: counts.equipmentDamageFailure },
  ];
}

type PerformanceDataEntryProps = {
  title: string;
  description?: string;
  /** The Baytown date when the page was rendered on the server. */
  siteToday: string;
};

export function PerformanceDataEntry({ title, description, siteToday }: PerformanceDataEntryProps) {
  const currentYear = yearOf(useSiteToday(siteToday));
  const [drafts, setDrafts] = useState<Record<number, HoursDraft>>({});
  // Drafts are keyed by month only, so a year with unsaved hours never moves at midnight.
  const yearChoice = useAutomaticValue(currentYear, { hold: Object.keys(drafts).length > 0 });
  const year = yearChoice.value;
  const query = usePerformanceMonths(year);
  const data = query.data;
  const loading = query.isPending && !query.isError;
  const accessDenied =
    query.error instanceof ApiError && (query.error.status === 401 || query.error.status === 403);

  const changeYear = (next: number) => {
    yearChoice.choose(next);
    setDrafts({});
  };
  const years = reportingYearOptions(currentYear, [...(data?.yearsWithData ?? []), year], FIRST_HOURS_YEAR);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Safety · Safety Performance"
        title={title}
        description={description}
        actions={
          <Link
            href="/safety/performance/dashboard"
            className={buttonVariants({ variant: "outline", className: "pointer-coarse:h-11" })}
          >
            <ChartColumn />
            Open dashboard
          </Link>
        }
      />

      <FilterBar
        actions={
          query.isFetching && !query.isPending ? (
            <StatusBadge tone="pending" pulse>
              Updating
            </StatusBadge>
          ) : undefined
        }
      >
        <div className="w-full sm:w-44">
          <FilterSelect
            label="Reporting year"
            placeholder={false}
            options={years.map((value) => ({ value: String(value), label: String(value) }))}
            value={String(year)}
            onChange={(event) => changeYear(Number(event.target.value))}
            className="pointer-coarse:h-11"
          />
        </div>
      </FilterBar>

      <p className="px-1 text-sm text-muted-foreground">
        Enter the total hours worked each month. Only closed months with hours above zero are used in rates. Event
        counts are read-only here;{" "}
        {data?.countSource === "performance_legacy" ? (
          <>
            counts before 2026 come from the reviewed legacy workbook import. Closing a pre-2026 month confirms its
            hours only: a count left blank in the workbook stays unconfirmed, and rates that need it are unavailable.
          </>
        ) : (
          <>
            edit them in{" "}
            <Link href="/safety/incidents/data-entry" className="font-medium text-primary underline-offset-4 hover:underline">
              Incident &amp; Near Miss
              <ExternalLink className="ml-0.5 inline size-3.5 align-[-2px]" aria-hidden />
            </Link>
            . <strong className="font-medium text-foreground">Closing</strong> a month confirms its event counts are
            complete: a count left blank then counts as zero.
          </>
        )}
      </p>

      {query.isError ? (
        <div className="rounded-lg border bg-card">
          <EmptyState
            variant="plain"
            icon={AlertTriangle}
            title={accessDenied ? "Safety data is not available to you" : "Could not load Safety Performance"}
            description={describePerformanceError(query.error)}
            action={
              accessDenied ? undefined : (
                <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
                  Retry
                </Button>
              )
            }
          />
        </div>
      ) : loading || !data ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true">
          {Array.from({ length: 12 }, (_, index) => (
            <div key={index} className="h-72 animate-pulse rounded-lg border bg-muted/40" />
          ))}
          <span className="sr-only">Loading Safety Performance</span>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {data.months.map((month) => (
            <MonthCard
              key={month.month}
              year={year}
              month={month}
              countSource={data.countSource}
              canEdit={data.canEdit}
              draft={drafts[month.month] ?? null}
              onDraft={(draft) =>
                setDrafts((current) => {
                  const next = { ...current };
                  if (draft === null) delete next[month.month];
                  else next[month.month] = draft;
                  return next;
                })
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}

type MonthCardProps = {
  year: number;
  month: PerformanceMonth;
  countSource: CountSource;
  canEdit: boolean;
  draft: HoursDraft | null;
  onDraft: (draft: HoursDraft | null) => void;
};

export function MonthCard({ year, month, countSource, canEdit, draft, onDraft }: MonthCardProps) {
  const id = useId();
  const change = useChangeMonth(year);
  const [message, setMessage] = useState<{ tone: "error" | "info"; text: string } | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const values = draft ?? draftFromMonth(month);
  const check = checkDraft(values, month);
  const editable = canEdit && month.canEnter;
  const name = monthName(month.month);

  const update = (patch: Partial<HoursDraft>) => {
    setMessage(null);
    onDraft({ ...values, ...patch });
  };

  const fail = (error: unknown) => {
    setMessage({
      tone: "error",
      text: isEditConflict(error)
        ? `${name} was changed by someone else since you loaded it. Nothing was saved. The current values are now shown under "Saved"; review your entry and save again if it is still needed.`
        : describePerformanceError(error),
    });
  };

  const save = () => {
    if (!check.request) return;
    change.mutate(
      { kind: "save", month: month.month, request: check.request },
      {
        onSuccess: () => {
          onDraft(null);
          setMessage({ tone: "info", text: `${name} saved.` });
        },
        onError: fail,
      },
    );
  };

  const clear = () => {
    if (!month.hours) return;
    change.mutate(
      { kind: "clear", month: month.month, expectedUpdatedAt: month.hours.updatedAt },
      {
        onSuccess: () => {
          onDraft(null);
          setConfirmClear(false);
          setMessage({ tone: "info", text: `${name} cleared; it is Not Reported.` });
        },
        onError: (error) => {
          setConfirmClear(false);
          fail(error);
        },
      },
    );
  };

  return (
    <section aria-labelledby={`${id}-title`} className="flex flex-col gap-3 rounded-lg border bg-card p-4">
      <header className="flex items-center justify-between gap-2">
        <h2 id={`${id}-title`} className="text-base font-semibold">
          {name} {year}
        </h2>
        <StatusBadge tone={STATUS_TONES[month.status]}>{STATUS_LABELS[month.status]}</StatusBadge>
      </header>

      {!month.canEnter ? (
        <p className="text-sm text-muted-foreground">This month has not started.</p>
      ) : (
        <div className="space-y-3">
          <label className="block space-y-1">
            <span className="text-sm font-medium">Total hours</span>
            <input
              className="h-10 w-full rounded-md border bg-background px-3 text-sm tabular-nums pointer-coarse:h-11 disabled:opacity-70"
              inputMode="decimal"
              autoComplete="off"
              value={values.total}
              disabled={!editable || change.isPending}
              aria-invalid={!parseHours(values.total).ok}
              onChange={(event) => update({ total: event.target.value })}
            />
          </label>

          {editable ? (
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4 pointer-coarse:size-5"
                checked={values.breakdown}
                disabled={change.isPending}
                onChange={(event) => update({ breakdown: event.target.checked, hourly: "", salary: "" })}
              />
              Hourly / salary breakdown (optional)
            </label>
          ) : null}

          {values.breakdown && (
            <div className="grid grid-cols-2 gap-2">
              {(["hourly", "salary"] as const).map((field) => (
                <label key={field} className="block space-y-1">
                  <span className="text-sm font-medium capitalize">{field} hours</span>
                  <input
                    className="h-10 w-full rounded-md border bg-background px-3 text-sm tabular-nums pointer-coarse:h-11 disabled:opacity-70"
                    inputMode="decimal"
                    autoComplete="off"
                    value={values[field]}
                    disabled={!editable || change.isPending}
                    aria-invalid={!parseHours(values[field]).ok}
                    onChange={(event) => update({ [field]: event.target.value })}
                  />
                </label>
              ))}
            </div>
          )}

          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 size-4 pointer-coarse:size-5"
              checked={values.closed}
              disabled={!editable || change.isPending || (!month.canClose && !values.closed)}
              onChange={(event) => update({ closed: event.target.checked })}
            />
            <span>
              {countSource === "performance_legacy"
                ? "Month closed: worked hours are final"
                : "Month closed: event counts are complete"}
              {!month.canClose && <span className="block text-xs text-muted-foreground">Can be closed after the month ends.</span>}
            </span>
          </label>
        </div>
      )}

      <div className="rounded-md bg-muted/40 p-3">
        <p className="mb-1.5 text-xs font-medium text-muted-foreground">
          Event counts{" "}
          {countSource === "performance_legacy"
            ? "(workbook import; a blank is not confirmed)"
            : month.countsConfirmed
              ? "(confirmed; blanks count as zero)"
              : "(not confirmed until the month is closed)"}
        </p>
        <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 text-sm">
          {countRows(month.counts, countSource).map((row) => (
            <div key={row.label} className="contents">
              <dt className="text-muted-foreground">{row.label}</dt>
              <dd className="text-right tabular-nums">{row.value ?? "—"}</dd>
            </div>
          ))}
        </dl>
      </div>

      {month.hours && (
        <p className="text-xs text-muted-foreground">
          Saved: {formatHours(month.hours.totalHours)} h{month.hours.monthClosed ? ", closed" : ", open"} · by{" "}
          {month.hours.updatedBy}
        </p>
      )}

      {editable && draft !== null && check.errors.length > 0 && (
        <ul className="space-y-0.5 text-sm text-destructive" role="alert">
          {check.errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}
      {message && (
        <p role="status" className={message.tone === "error" ? "text-sm text-destructive" : "text-sm text-muted-foreground"}>
          {message.text}
        </p>
      )}

      {editable && (
        <div className="mt-auto flex flex-wrap gap-2 pt-1">
          <Button
            size="sm"
            className="pointer-coarse:h-11"
            disabled={!check.dirty || check.request === null || change.isPending}
            onClick={save}
          >
            Save {name}
          </Button>
          {draft !== null && (
            <Button
              size="sm"
              variant="outline"
              className="pointer-coarse:h-11"
              disabled={change.isPending}
              onClick={() => {
                onDraft(null);
                setMessage(null);
              }}
            >
              Discard changes
            </Button>
          )}
          {month.hours && draft === null && (
            confirmClear ? (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  className="text-destructive pointer-coarse:h-11"
                  disabled={change.isPending}
                  onClick={clear}
                >
                  Confirm clear
                </Button>
                <Button size="sm" variant="ghost" className="pointer-coarse:h-11" onClick={() => setConfirmClear(false)}>
                  Keep
                </Button>
              </>
            ) : (
              <Button size="sm" variant="ghost" className="pointer-coarse:h-11" onClick={() => setConfirmClear(true)}>
                Clear month
              </Button>
            )
          )}
        </div>
      )}
    </section>
  );
}