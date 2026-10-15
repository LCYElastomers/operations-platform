"use client";

import { AlertTriangle, CalendarClock, ExternalLink, ListFilter } from "lucide-react";
import { useId, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

import { describeSafetyError } from "../api";
import type { EventSummary, ExperienceCategory } from "./insights-api";
import { categoryEventTypes, daysSinceText, STATUS_TEXT, ytdText } from "./insights-data";
import type { RegisterFilters } from "./incident-register";
import { EVENT_LABELS, formatRecordDate } from "./record-data";
import { useEventExperience } from "./use-records";

type EventExperienceProps = {
  year: number;
  /** Opens one record in the Incident Register. */
  onOpenRecord: (id: number) => void;
  /** Shows the Incident Register filtered to a category. */
  onViewAll: (filters: RegisterFilters) => void;
};

const STATUS_EXPLANATION: Record<ExperienceCategory["status"], (asOf: string) => string> = {
  complete: () => "Every record in this category is classified.",
  no_event_in_scope: (asOf) => `No event in this category from January 1 to ${formatRecordDate(asOf)}.`,
  insufficient_classification_data: () =>
    "Some records are unclassified or missing details, so the count is a minimum and the last event may be later than shown.",
  source_unavailable: (asOf) => `No Incident Register records are on file up to ${formatRecordDate(asOf)}.`,
};

/** Days since the last event, per category, from the Incident Register records. */
export function EventExperienceView({ year, onOpenRecord, onViewAll }: EventExperienceProps) {
  const experience = useEventExperience(year);
  const [selected, setSelected] = useState<string | null>(null);
  const panelId = useId();

  if (experience.isError) {
    const denied =
      experience.error instanceof ApiError && (experience.error.status === 401 || experience.error.status === 403);
    return (
      <EmptyState
        icon={AlertTriangle}
        title={denied ? "Event Experience is not available to you" : "Could not load Event Experience"}
        description={describeSafetyError(experience.error)}
        action={
          denied ? undefined : (
            <Button variant="outline" size="sm" onClick={() => void experience.refetch()}>
              Retry
            </Button>
          )
        }
      />
    );
  }
  const data = experience.data;
  if (!data) return <p className="px-1 text-sm text-muted-foreground">Loading Event Experience…</p>;

  const current = data.categories.find((category) => category.code === selected) ?? null;
  const viewAll = (category: ExperienceCategory) =>
    onViewAll({ category: category.code, eventType: categoryEventTypes(category.code, data.includesNearMisses) });

  return (
    <div className="space-y-5">
      <p className="max-w-4xl px-1 text-sm text-muted-foreground">
        Calculated from active Incident Register records as of {formatRecordDate(data.asOf)} ({data.siteTimeZone}).
        Days since counts calendar days from the last event to that date. Categories cover incidents;{" "}
        {data.includesNearMisses ? "PSIF also includes near misses." : "near misses are not available to you."} A
        category with no event on file shows no value, never zero.
      </p>

      <section aria-label="Event Experience categories" className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {data.categories.map((category) => (
          <CategoryCard
            key={category.code}
            category={category}
            selected={category.code === selected}
            controls={panelId}
            onSelect={() => setSelected(category.code === selected ? null : category.code)}
          />
        ))}
      </section>

      <div id={panelId} aria-live="polite">
        {current && (
          <CategoryDetails
            category={current}
            onOpenRecord={onOpenRecord}
            onViewAll={() => viewAll(current)}
            onClose={() => setSelected(null)}
          />
        )}
      </div>

      <ComparisonTable categories={data.categories} />
    </div>
  );
}

function CategoryCard({
  category,
  selected,
  controls,
  onSelect,
}: {
  category: ExperienceCategory;
  selected: boolean;
  controls: string;
  onSelect: () => void;
}) {
  const days = daysSinceText(category.daysSinceLatestEvent);
  const status = STATUS_TEXT[category.status];
  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-controls={controls}
      onClick={onSelect}
      className={cn(
        "flex min-h-36 flex-col gap-2 rounded-lg border bg-card p-4 text-left shadow-xs transition-colors",
        "hover:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:outline-none",
        selected && "border-primary ring-1 ring-primary",
      )}
    >
      <span className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium">{category.name}</span>
        <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
      </span>
      <span className="text-2xl font-semibold tabular-nums" data-testid={`days-${category.code}`}>
        {days ?? <span className="text-base font-normal text-muted-foreground">No event on file</span>}
      </span>
      <span className="text-xs text-muted-foreground">
        {category.latestEventDate
          ? `Since ${formatRecordDate(category.latestEventDate)}${category.latestInSelectedYear ? "" : " (an earlier year)"}`
          : "No last event"}
      </span>
      <span className="mt-auto text-xs">
        This year: <span className="font-medium tabular-nums">{ytdText(category)}</span>
      </span>
    </button>
  );
}

function EventCard({ event }: { event: EventSummary }) {
  return (
    <div className="space-y-1 text-sm">
      <p className="font-medium">
        {event.incidentNumber ?? "No number"} · {formatRecordDate(event.incidentDate)} · {EVENT_LABELS[event.eventType].one}
      </p>
      <p className="text-muted-foreground">
        {event.areaName ?? "Area not recorded"} ·{" "}
        {event.classifications.length ? event.classifications.join(", ") : "Unclassified"}
      </p>
      <p className="whitespace-pre-line">{event.description}</p>
    </div>
  );
}

function CategoryDetails({
  category,
  onOpenRecord,
  onViewAll,
  onClose,
}: {
  category: ExperienceCategory;
  onOpenRecord: (id: number) => void;
  onViewAll: () => void;
  onClose: () => void;
}) {
  const latest = category.latestEvent;
  return (
    <section aria-label={`${category.name} details`} className="space-y-3 rounded-lg border bg-card p-4">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">{category.name}</h2>
          <p className="text-sm text-muted-foreground">{STATUS_EXPLANATION[category.status](category.asOf)}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} className="pointer-coarse:h-11">
          Close
        </Button>
      </header>
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <Stat label="Days since last event" value={daysSinceText(category.daysSinceLatestEvent) ?? "No event on file"} />
        <Stat label="Last event" value={category.latestEventDate ? formatRecordDate(category.latestEventDate) : "None on file"} />
        <Stat label={`Records, ${category.year}`} value={ytdText(category)} />
        <Stat
          label="Monthly count (stored)"
          value={category.monthlyCount === null ? "Not reported" : String(category.monthlyCount)}
        />
      </dl>
      {category.warnings.length > 0 && (
        <ul className="space-y-1 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
          {category.warnings.map((warning) => (
            <li key={warning} className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              {warning}
            </li>
          ))}
        </ul>
      )}
      {latest && (
        <div className="rounded-md border bg-muted/30 p-3">
          <p className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <CalendarClock className="size-3.5" />
            Last event
          </p>
          <EventCard event={latest} />
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          onClick={() => latest && onOpenRecord(latest.id)}
          disabled={!latest}
          className="pointer-coarse:h-11"
        >
          <ExternalLink />
          View Last Event
        </Button>
        <Button variant="outline" onClick={onViewAll} className="pointer-coarse:h-11">
          <ListFilter />
          View All Matching Events
        </Button>
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  );
}

function ComparisonTable({ categories }: { categories: ExperienceCategory[] }) {
  return (
    <section aria-label="Event Experience comparison" className="overflow-x-auto rounded-lg border bg-card">
      <table className="w-full text-left text-sm">
        <caption className="px-4 py-3 text-left text-sm font-semibold">
          Category comparison
          <span className="block text-xs font-normal text-muted-foreground">
            Record-derived. The stored monthly count is shown beside the records for comparison; – is not reported.
          </span>
        </caption>
        <thead className="border-y text-xs text-muted-foreground">
          <tr>
            {["Category", "Last event", "Days since", "Records this year", "Monthly count (stored)", "Status"].map((h) => (
              <th key={h} scope="col" className="px-3 py-2 font-medium first:pl-4">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {categories.map((category) => (
            <tr key={category.code} className="border-b border-border/60 last:border-b-0">
              <th scope="row" className="px-3 py-2 pl-4 font-medium">
                {category.name}
              </th>
              <td className="px-3 py-2 whitespace-nowrap">
                {category.latestEventDate ? formatRecordDate(category.latestEventDate) : "None on file"}
              </td>
              <td className="px-3 py-2 tabular-nums">{daysSinceText(category.daysSinceLatestEvent) ?? "–"}</td>
              <td className="px-3 py-2 tabular-nums">{ytdText(category)}</td>
              <td className="px-3 py-2 tabular-nums">{category.monthlyCount ?? "–"}</td>
              <td className="px-3 py-2">
                <StatusBadge tone={STATUS_TEXT[category.status].tone}>{STATUS_TEXT[category.status].label}</StatusBadge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
