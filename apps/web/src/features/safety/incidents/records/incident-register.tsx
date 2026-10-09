"use client";

import { AlertTriangle, ListChecks, Plus } from "lucide-react";
import { useId, useState } from "react";

import {
  DisplayControls,
  HiddenNotice,
  useDisplayPreferences,
} from "@/components/common/display-controls";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar, FilterInput, FilterSelect } from "@/components/common/filter-bar";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { ApiError } from "@/lib/api-client";

import { describeSafetyError } from "../api";
import {
  allowsType,
  type EventType,
  type IncidentRecord,
  type MonthReconciliation,
  type RecordPermissions,
  type RecordStatus,
} from "./api";
import {
  describeReconciliation,
  EVENT_LABELS,
  formatRecordDate,
  MONTH_NAMES,
  STATUS_LABELS,
  stateShort,
  stateTone,
} from "./record-data";
import { RecordActions, RecordDialog, RecordStatusBadge, type RecordPanel } from "./record-dialog";
import { useRecordOptions, useRecordReconciliation, useRecords } from "./use-records";

export type RegisterFilters = { month?: number; eventType?: EventType };

const STATE_TONES = { ok: "success", warning: "warning", neutral: "neutral" } as const;
const EVENT_TYPES: EventType[] = ["incident", "near_miss"];

type RegisterProps = {
  year: number;
  /** The dashboard's Through month; null before the year starts. */
  through: number | null;
  today: string;
  initial?: RegisterFilters;
};

/**
 * Individual Incident and Near Miss records, grouped by month, beside each
 * month's authoritative total. Records never change the totals.
 */
export function IncidentRegister({ year, through, today, initial }: RegisterProps) {
  const [month, setMonth] = useState(initial?.month ? String(initial.month) : "");
  const [eventType, setEventType] = useState<string>(initial?.eventType ?? "");
  const [areaId, setAreaId] = useState("");
  const [classificationId, setClassificationId] = useState("");
  const [status, setStatus] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [search, setSearch] = useState("");
  const [panel, setPanel] = useState<RecordPanel | null>(null);
  const display = useDisplayPreferences("safety.incidents.register");
  const toggleId = useId();
  const searchText = useDebouncedValue(search, 300);

  const statuses: RecordStatus[] = status
    ? [status as RecordStatus]
    : showInactive
      ? ["active", "voided", "reclassified"]
      : ["active"];
  const chosenMonth = month ? Number(month) : undefined;
  const records = useRecords(
    {
      year,
      through: chosenMonth === undefined && through !== null ? through : undefined,
      month: chosenMonth,
      eventType: (eventType || undefined) as EventType | undefined,
      areaId: areaId ? Number(areaId) : undefined,
      classificationId: classificationId ? Number(classificationId) : undefined,
      statuses,
      search: searchText,
    },
    through !== null,
  );
  const reconciliation = useRecordReconciliation(year);
  const options = useRecordOptions();
  const permissions = records.data ?? reconciliation.data;

  const accessDenied =
    records.error instanceof ApiError && (records.error.status === 401 || records.error.status === 403);
  if (through === null) {
    return <EmptyState icon={ListChecks} title={`${year} has not started.`} description="Records appear here by month." />;
  }
  if (records.isError) {
    return (
      <EmptyState
        icon={AlertTriangle}
        title={accessDenied ? "Incident records are not available to you" : "Could not load Incident records"}
        description={describeSafetyError(records.error)}
      />
    );
  }

  const months = (chosenMonth ? [chosenMonth] : Array.from({ length: through }, (_, index) => through - index)).filter(
    (m) => m <= through,
  );
  const byMonth = new Map<number, IncidentRecord[]>();
  for (const record of records.data?.records ?? []) {
    byMonth.set(record.reportingMonth, [...(byMonth.get(record.reportingMonth) ?? []), record]);
  }
  const shownMonths = display.preferences.hideEmptyMonths
    ? months.filter((m) => (byMonth.get(m)?.length ?? 0) > 0)
    : months;
  const hiddenMonths = months.length - shownMonths.length;
  const types = eventType ? [eventType as EventType] : EVENT_TYPES;
  const total = records.data?.total ?? 0;
  const shown = records.data?.records.length ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {EVENT_TYPES.filter((type) => allowsType(permissions, "creatableTypes", type)).map((type) => (
            <Button key={type} onClick={() => setPanel({ kind: "create", eventType: type })} className="pointer-coarse:h-11">
              <Plus />
              Add {EVENT_LABELS[type].one}
            </Button>
          ))}
        <DisplayControls
          className="ml-auto"
          preferences={display.preferences}
          onChange={display.update}
          onReset={display.reset}
          rowOptions={false}
          months
        />
      </div>

      <FilterBar>
        <FilterSelect
          label="Month"
          placeholder={`All through ${MONTH_NAMES[through - 1]}`}
          options={Array.from({ length: through }, (_, index) => ({ value: String(index + 1), label: MONTH_NAMES[index] }))}
          value={month}
          onChange={(event) => setMonth(event.target.value)}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Event type"
          options={EVENT_TYPES.map((type) => ({ value: type, label: EVENT_LABELS[type].one }))}
          value={eventType}
          onChange={(event) => setEventType(event.target.value)}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Area"
          options={(options.data?.areas ?? []).map((option) => ({ value: String(option.id), label: option.name }))}
          value={areaId}
          onChange={(event) => setAreaId(event.target.value)}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Classification"
          options={(options.data?.classifications ?? []).map((option) => ({
            value: String(option.id),
            label: option.name,
          }))}
          value={classificationId}
          onChange={(event) => setClassificationId(event.target.value)}
          className="pointer-coarse:h-11"
        />
        <FilterSelect
          label="Status"
          placeholder={showInactive ? "All statuses" : "Active only (default)"}
          options={(["active", "voided", "reclassified"] as const).map((value) => ({
            value,
            label: STATUS_LABELS[value],
          }))}
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="pointer-coarse:h-11"
        />
        <FilterInput
          label="Search"
          type="search"
          placeholder="Number or description"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="pointer-coarse:h-11"
        />
        <label htmlFor={toggleId} className="flex min-h-9 items-center gap-2 self-end text-sm pointer-coarse:min-h-11">
          <input
            id={toggleId}
            type="checkbox"
            checked={showInactive}
            onChange={(event) => setShowInactive(event.target.checked)}
            className="size-4 accent-primary"
          />
          Show inactive
        </label>
      </FilterBar>

      <p className="px-1 text-sm text-muted-foreground" aria-live="polite">
        {!records.data
          ? "Loading records…"
          : `${total.toLocaleString()} ${total === 1 ? "record" : "records"}${shown < total ? `, first ${shown} shown` : ""}. Monthly totals are authoritative; documented counts are compared with them as a warning only.`}
        {records.isFetching && records.data && (
          <StatusBadge tone="pending" pulse className="ml-2">
            Updating
          </StatusBadge>
        )}
      </p>
      <HiddenNotice
        hidden={hiddenMonths}
        noun={["month without records", "months without records"]}
        onShowAll={() => display.update({ hideEmptyMonths: false })}
      />

      <div className="space-y-4">
        {shownMonths.map((m) => (
          <MonthGroup
            key={m}
            year={year}
            month={m}
            types={types}
            records={byMonth.get(m) ?? []}
            reconciliation={reconciliation.data?.months ?? []}
            permissions={records.data}
            onPanel={setPanel}
          />
        ))}
      </div>

      {panel && permissions && (
        <RecordDialog
          key={
            panel.kind === "create"
              ? `create-${panel.eventType}`
              : panel.kind === "list"
                ? "list"
                : `${panel.kind}-${panel.record.id}`
          }
          open
          onClose={() => setPanel(null)}
          scope={{ kind: "register" }}
          initialPanel={panel}
          permissions={permissions}
          today={today}
        />
      )}
    </div>
  );
}

function MonthGroup({
  year,
  month,
  types,
  records,
  reconciliation,
  permissions,
  onPanel,
}: {
  year: number;
  month: number;
  types: EventType[];
  records: IncidentRecord[];
  reconciliation: MonthReconciliation[];
  permissions: RecordPermissions | undefined;
  onPanel: (panel: RecordPanel) => void;
}) {
  const headingId = useId();
  const title = `${MONTH_NAMES[month - 1]} ${year}`;
  return (
    <section aria-labelledby={headingId} className="overflow-hidden rounded-lg border bg-card">
      <header className="flex flex-col gap-2 border-b bg-muted/40 px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between">
        <h3 id={headingId} className="text-sm font-semibold">
          {title}
        </h3>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {types.map((type) => {
            const check = reconciliation.find((r) => r.month === month && r.eventType === type);
            if (!check) return null;
            return (
              <li key={type} className="flex items-center gap-2" title={describeReconciliation(check)}>
                <span>
                  {EVENT_LABELS[type].many}: total {check.monthlyTotal ?? "not reported"} · documented {check.documented}
                </span>
                <StatusBadge tone={STATE_TONES[stateTone(check.state)]}>{stateShort(check.state)}</StatusBadge>
                <span className="sr-only">{describeReconciliation(check)}</span>
              </li>
            );
          })}
        </ul>
      </header>
      {records.length === 0 ? (
        <p className="px-4 py-3 text-sm text-muted-foreground">No records match for {title}.</p>
      ) : (
        <>
          <table className="hidden w-full text-left text-sm md:table">
            <caption className="sr-only">Records, {title}</caption>
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                {["Number", "Date", "Type", "Classification", "Area", "Description", "Status", "Actions"].map((h) => (
                  <th key={h} scope="col" className="px-3 py-2 font-medium first:pl-4">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {records.map((record) => (
                <tr key={record.id} className="border-b border-border/60 align-top last:border-b-0">
                  <th scope="row" className="px-3 py-2 pl-4 font-medium whitespace-nowrap tabular-nums">
                    {record.incidentNumber ?? <span className="text-muted-foreground">No number</span>}
                  </th>
                  <td className="px-3 py-2 whitespace-nowrap">{formatRecordDate(record.incidentDate)}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{EVENT_LABELS[record.eventType].one}</td>
                  <td className="px-3 py-2">{record.classificationName ?? <span className="text-muted-foreground">Unclassified</span>}</td>
                  <td className="px-3 py-2">{record.areaName ?? <span className="text-muted-foreground">Not recorded</span>}</td>
                  <td className="max-w-md px-3 py-2">
                    <p className="line-clamp-3" title={record.description}>
                      {record.description}
                    </p>
                  </td>
                  <td className="px-3 py-2">
                    <RecordStatusBadge status={record.status} />
                  </td>
                  <td className="px-3 py-2">
                    {permissions && <RecordActions record={record} permissions={permissions} onPanel={onPanel} compact />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="divide-y md:hidden" aria-label={`Records, ${title}`}>
            {records.map((record) => (
              <li key={record.id} className="space-y-1.5 px-4 py-3 text-sm">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="font-semibold tabular-nums">{record.incidentNumber ?? "No number"}</span>
                  <span className="text-muted-foreground">{formatRecordDate(record.incidentDate)}</span>
                  <RecordStatusBadge status={record.status} />
                </div>
                <p className="text-muted-foreground">
                  {EVENT_LABELS[record.eventType].one} · {record.classificationName ?? "Unclassified"} ·{" "}
                  {record.areaName ?? "No area"}
                </p>
                <p className="line-clamp-4">{record.description}</p>
                {permissions && <RecordActions record={record} permissions={permissions} onPanel={onPanel} />}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
