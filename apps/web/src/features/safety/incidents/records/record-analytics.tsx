"use client";

import { AlertTriangle, ExternalLink, ListFilter } from "lucide-react";

import { Button } from "@/components/ui/button";

import { describeSafetyError } from "../api";
import type { CountRow, EventSummary } from "./insights-api";
import type { RegisterFilters } from "./incident-register";
import { EVENT_LABELS, formatRecordDate, MONTH_NAMES } from "./record-data";
import { useLopcRecords, useSeriousRisk } from "./use-records";

type GroupProps = {
  year: number;
  /** The dashboard's Through month; null before the year starts. */
  through: number | null;
  onDrill: (filters: RegisterFilters) => void;
  onOpenRecord: (id: number) => void;
};

const LOPC_SCOPE: RegisterFilters = { category: "spill_release_lopc", eventType: "incident" };

function Group({ title, basis, children }: { title: string; basis: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="space-y-3">
      <div className="px-1">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-xs text-muted-foreground">{basis}</p>
      </div>
      {children}
    </section>
  );
}

function Warnings({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <ul role="status" className="space-y-1 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
      {warnings.map((warning) => (
        <li key={warning} className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          {warning}
        </li>
      ))}
    </ul>
  );
}

/** One breakdown as a table; each filterable row drills to the matching Register records. */
function CountTable({
  title,
  basis,
  rows,
  drill,
  onDrill,
}: {
  title: string;
  basis: string;
  rows: CountRow[];
  drill: ((key: string) => RegisterFilters) | null;
  onDrill: (filters: RegisterFilters) => void;
}) {
  return (
    <div className="rounded-lg border bg-card">
      <header className="border-b px-4 py-2.5">
        <h3 className="text-sm font-semibold">{title}</h3>
        <p className="text-xs text-muted-foreground">{basis}</p>
      </header>
      {rows.length === 0 ? (
        <p className="px-4 py-3 text-sm text-muted-foreground">No records.</p>
      ) : (
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{title}</caption>
          <thead className="sr-only">
            <tr>
              <th scope="col">{title}</th>
              <th scope="col">Records</th>
              <th scope="col">Drill-through</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.key}-${row.name}`} className="border-b border-border/50 last:border-b-0">
                <th scope="row" className={row.key === "unknown" || row.key === null ? "px-4 py-1.5 font-normal italic text-muted-foreground" : "px-4 py-1.5 font-normal"}>
                  {row.name}
                </th>
                <td className="px-3 py-1.5 text-right tabular-nums">{row.count}</td>
                <td className="px-3 py-1.5 text-right">
                  {drill && row.key !== null && (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`View ${row.count} ${row.count === 1 ? "record" : "records"}: ${title}, ${row.name}`}
                      onClick={() => onDrill(drill(row.key!))}
                      className="pointer-coarse:h-11"
                    >
                      <ListFilter />
                      <span className="max-sm:sr-only">Records</span>
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function RecentEvents({ events, onOpenRecord }: { events: EventSummary[]; onOpenRecord: (id: number) => void }) {
  return (
    <div className="rounded-lg border bg-card">
      <header className="border-b px-4 py-2.5">
        <h3 className="text-sm font-semibold">Recent events</h3>
        <p className="text-xs text-muted-foreground">Record-derived, newest first.</p>
      </header>
      {events.length === 0 ? (
        <p className="px-4 py-3 text-sm text-muted-foreground">No records.</p>
      ) : (
        <ul className="divide-y">
          {events.map((event) => (
            <li key={event.id} className="flex items-start justify-between gap-3 px-4 py-2 text-sm">
              <div className="min-w-0">
                <p className="font-medium">
                  {event.incidentNumber ?? "No number"} · {formatRecordDate(event.incidentDate)} ·{" "}
                  {EVENT_LABELS[event.eventType].one}
                </p>
                <p className="line-clamp-2 text-muted-foreground">{event.description}</p>
              </div>
              <Button
                variant="outline"
                size="sm"
                aria-label={`Open ${event.incidentNumber ?? formatRecordDate(event.incidentDate)}`}
                onClick={() => onOpenRecord(event.id)}
                className="shrink-0 pointer-coarse:h-11"
              >
                <ExternalLink />
                <span className="max-sm:sr-only">Open</span>
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Loading({ label, error, retry }: { label: string; error: unknown; retry: () => void }) {
  if (error) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        <AlertTriangle className="size-4" />
        Could not load {label}. {describeSafetyError(error)}
        <Button variant="outline" size="sm" onClick={retry}>
          Retry
        </Button>
      </div>
    );
  }
  return <p className="px-1 text-sm text-muted-foreground">Loading {label}…</p>;
}

function periodText(year: number, through: number | null) {
  return through === null ? String(year) : `January–${MONTH_NAMES[through - 1]} ${year}`;
}

/** LOPC breakdowns from the Spill / Release records and their LOPC details. */
export function LopcRecordsGroup({ year, through, onDrill, onOpenRecord }: GroupProps) {
  const lopc = useLopcRecords(year, through, through !== null);
  const title = "LOPC records";
  if (through === null) return null;
  if (!lopc.data) return (
    <Group title={title} basis="Record-derived.">
      <Loading label="LOPC records" error={lopc.error} retry={() => void lopc.refetch()} />
    </Group>
  );
  const data = lopc.data;
  const period = periodText(year, data.throughMonth);
  const drill = (key: keyof RegisterFilters) => (value: string) => ({ ...LOPC_SCOPE, [key]: value });
  return (
    <Group
      title={title}
      basis={`Record-derived from ${data.records} Spill / Release ${data.records === 1 ? "record" : "records"}, ${period}; ${data.withDetails} with LOPC details. Counts are records, not the stored monthly LOPC count${data.monthlyCount === null ? " (not reported)" : ` (${data.monthlyCount}${data.monthlyCountComplete ? "" : ", partial"})`}. Unknown means not recorded.`}
    >
      <Warnings warnings={data.warnings} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 min-[1440px]:grid-cols-3">
        <CountTable title="Failure mechanism" basis="Count of records." rows={data.byFailureMechanism} drill={drill("failureMechanism")} onDrill={onDrill} />
        <CountTable title="Material released" basis="Count of records." rows={data.byMaterial} drill={drill("material")} onDrill={onDrill} />
        <CountTable title="Equipment" basis="Count of records, by equipment tag." rows={data.byEquipment} drill={drill("equipmentTag")} onDrill={onDrill} />
        <CountTable title="Secondary containment" basis="Count of records." rows={data.byContainment} drill={drill("containment")} onDrill={onDrill} />
        <CountTable title="Process safety incident" basis="Count of records." rows={data.byProcessSafety} drill={drill("processSafety")} onDrill={onDrill} />
        <div className="rounded-lg border bg-card">
          <header className="border-b px-4 py-2.5">
            <h3 className="text-sm font-semibold">Estimated quantity by unit</h3>
            <p className="text-xs text-muted-foreground">
              Quantity-based: totals per unit. Quantities in different units are never added together.
            </p>
          </header>
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Estimated quantity by unit</caption>
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-1.5 font-medium">Unit</th>
                <th scope="col" className="px-3 py-1.5 text-right font-medium">Total</th>
                <th scope="col" className="px-3 py-1.5 text-right font-medium">Records</th>
                <th scope="col" className="px-3 py-1.5"><span className="sr-only">Drill-through</span></th>
              </tr>
            </thead>
            <tbody>
              {data.quantities.map((row) => (
                <tr key={row.unitCode} className="border-t border-border/50">
                  <th scope="row" className="px-4 py-1.5 font-normal">{row.unitName}</th>
                  <td className="px-3 py-1.5 text-right tabular-nums">{row.total}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{row.records}</td>
                  <td className="px-3 py-1.5 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`View records measured in ${row.unitName}`}
                      onClick={() => onDrill({ ...LOPC_SCOPE, quantityUnit: row.unitCode })}
                      className="pointer-coarse:h-11"
                    >
                      <ListFilter />
                      <span className="max-sm:sr-only">Records</span>
                    </Button>
                  </td>
                </tr>
              ))}
              <tr className="border-t border-border/50">
                <th scope="row" className="px-4 py-1.5 font-normal italic text-muted-foreground">Quantity unknown</th>
                <td className="px-3 py-1.5 text-right text-muted-foreground">–</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{data.recordsWithoutQuantity}</td>
                <td className="px-3 py-1.5 text-right">
                  {data.recordsWithoutQuantity > 0 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label="View records with no quantity recorded"
                      onClick={() => onDrill({ ...LOPC_SCOPE, quantityUnit: "unknown" })}
                      className="pointer-coarse:h-11"
                    >
                      <ListFilter />
                      <span className="max-sm:sr-only">Records</span>
                    </Button>
                  )}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <RecentEvents events={data.recent} onOpenRecord={onOpenRecord} />
    </Group>
  );
}

/** PSIF-designated records, beside the stored monthly PSIF count. */
export function SeriousRiskGroup({ year, through, onDrill, onOpenRecord }: GroupProps) {
  const risk = useSeriousRisk(year, through, through !== null);
  const title = "Serious risk (PSIF) records";
  if (through === null) return null;
  if (!risk.data) return (
    <Group title={title} basis="Record-derived.">
      <Loading label="serious-risk records" error={risk.error} retry={() => void risk.refetch()} />
    </Group>
  );
  const data = risk.data;
  const scope: RegisterFilters = { category: "psif", eventType: data.includesNearMisses ? undefined : "incident" };
  const period = periodText(year, data.throughMonth);
  return (
    <Group
      title={title}
      basis={`Record-derived from ${data.psifRecords} ${data.psifRecords === 1 ? "record" : "records"} designated PSIF, ${period}. The PSIF count itself is on the Overview; these views break the documented records down.`}
    >
      <Warnings warnings={data.warnings} />
      <div className="flex flex-wrap items-center gap-2 px-1">
        <Button variant="outline" size="sm" onClick={() => onDrill(scope)} className="pointer-coarse:h-11">
          <ListFilter />
          View all PSIF records
        </Button>
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 min-[1440px]:grid-cols-3">
        <div className="rounded-lg border bg-card">
          <header className="border-b px-4 py-2.5">
            <h3 className="text-sm font-semibold">Records vs monthly count</h3>
            <p className="text-xs text-muted-foreground">
              Count-based: PSIF records per month beside the stored aggregate; – is not reported.
            </p>
          </header>
          <table className="w-full text-left text-sm">
            <caption className="sr-only">PSIF records and stored monthly count by month</caption>
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-1.5 font-medium">Month</th>
                <th scope="col" className="px-3 py-1.5 text-right font-medium">Records</th>
                <th scope="col" className="px-3 py-1.5 text-right font-medium">Monthly count</th>
                <th scope="col" className="px-3 py-1.5 font-medium">Check</th>
              </tr>
            </thead>
            <tbody>
              {data.monthly.map((row) => {
                const short = row.monthlyCount !== null && row.monthlyCount > row.records;
                return (
                  <tr key={row.month} className="border-t border-border/50">
                    <th scope="row" className="px-4 py-1.5 font-normal">{MONTH_NAMES[row.month - 1].slice(0, 3)}</th>
                    <td className="px-3 py-1.5 text-right tabular-nums">{row.records}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{row.monthlyCount ?? "–"}</td>
                    <td className="px-3 py-1.5 text-xs">
                      {short && (
                        <span className="text-amber-700 dark:text-warning">
                          {row.monthlyCount! - row.records} not documented
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <CountTable
          title="By classification"
          basis="Count of records; a record with more than one classification counts under each."
          rows={data.byClassification}
          drill={(key) => ({ ...scope, classificationId: Number(key) })}
          onDrill={onDrill}
        />
        <CountTable
          title="By area"
          basis="Count of records."
          rows={data.byArea}
          drill={(key) => ({ ...scope, areaId: Number(key) })}
          onDrill={onDrill}
        />
        <CountTable
          title="By potential severity"
          basis="Count of records."
          rows={data.bySeverity}
          drill={null}
          onDrill={onDrill}
        />
        <CountTable
          title="By LOPC contributing factor"
          basis="Count of records with LOPC details."
          rows={data.byContributingFactor}
          drill={(key) => ({ ...scope, contributingFactor: key })}
          onDrill={onDrill}
        />
      </div>
      <RecentEvents events={data.recent} onOpenRecord={onOpenRecord} />
    </Group>
  );
}
