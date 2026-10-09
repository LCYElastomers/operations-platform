"use client";

import { AlertTriangle, History, Pencil, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

import { describeCostError, type CoqClass, type CostHistoryEvent, type CostRecord, type CostRecordOptions } from "./api";
import { CostRecordForm } from "./record-form";
import { COQ_CLASS_COLORS, FINANCIAL_TONES, formatDate, formatTimestamp, usd } from "./format";
import { useCostRecord, useCostRecordHistory, useCostRecordOptions } from "./use-cost";
import { carHref } from "../car/api";
import { useLinkedCars } from "../car/use-car";

export type CostDialogTarget = { kind: "create"; coqClass?: CoqClass } | { kind: "view"; id: number };

type Panel = { kind: "create" } | { kind: "view" } | { kind: "edit"; record: CostRecord };

/**
 * A Quality Cost item in a modal dialog: the entry form for a new item, or
 * the record's detail with edit and history. The same dialog is opened from
 * the Register, COPQ and the COQ Matrix.
 */
export function CostRecordDialog({ target, onClose }: { target: CostDialogTarget | null; onClose: () => void }) {
  const [shown, setShown] = useState<{ target: CostDialogTarget; panel: Panel["kind"] } | null>(null);
  const panel = shown && shown.target === target ? shown.panel : target?.kind === "create" ? "create" : "view";
  return (
    <Dialog
      open={target !== null}
      onClose={onClose}
      title={panel === "create" ? "Add quality cost item" : panel === "edit" ? "Edit quality cost item" : "Quality cost item"}
      className="sm:w-[min(60rem,calc(100vw-2rem))]"
    >
      {target && (
        <DialogBody
          key={target.kind === "view" ? target.id : "create"}
          target={target}
          onClose={onClose}
          onPanel={(kind) => setShown({ target, panel: kind })}
        />
      )}
    </Dialog>
  );
}

function DialogBody({
  target,
  onClose,
  onPanel,
}: {
  target: CostDialogTarget;
  onClose: () => void;
  onPanel: (kind: Panel["kind"]) => void;
}) {
  const options = useCostRecordOptions();
  const [viewId, setViewId] = useState<number | null>(target.kind === "view" ? target.id : null);
  const [panel, setPanelState] = useState<Panel>(target.kind === "create" ? { kind: "create" } : { kind: "view" });
  const setPanel = (next: Panel) => {
    setPanelState(next);
    onPanel(next.kind);
  };
  const [notice, setNotice] = useState<string | null>(null);
  const loaded = useCostRecord(viewId);

  if (options.isError) return <LoadError error={options.error} />;
  if (!options.data) return <p className="py-6 text-sm text-muted-foreground">Loading…</p>;

  if (panel.kind === "create" || panel.kind === "edit") {
    const record = panel.kind === "edit" ? panel.record : null;
    return (
      <CostRecordForm
        key={record ? `${record.id}:${record.version}` : "create"}
        record={record}
        defaultClass={target.kind === "create" ? target.coqClass : undefined}
        options={options.data}
        onCancel={() => (record ? setPanel({ kind: "view" }) : onClose())}
        onSaved={(saved, created) => {
          setViewId(saved.id);
          setNotice(`${created ? "Added" : "Saved"} ${saved.recordNumber}.`);
          setPanel({ kind: "view" });
        }}
        onReload={(current) => setPanel({ kind: "edit", record: current })}
      />
    );
  }

  if (loaded.isError) return <LoadError error={loaded.error} />;
  if (!loaded.data) return <p className="py-6 text-sm text-muted-foreground">Loading…</p>;
  return (
    <RecordDetail
      record={loaded.data.record}
      canEdit={loaded.data.canEdit}
      options={options.data}
      notice={notice}
      onEdit={() => {
        setNotice(null);
        setPanel({ kind: "edit", record: loaded.data.record });
      }}
    />
  );
}

function LoadError({ error }: { error: unknown }) {
  return <EmptyState icon={AlertTriangle} title="Could not load this item" description={describeCostError(error)} />;
}

/** Opens the shared entry dialog. Shown only to users who may add items. */
export function AddCostRecordButton({ coqClass, className }: { coqClass?: CoqClass; className?: string }) {
  const options = useCostRecordOptions();
  const [target, setTarget] = useState<CostDialogTarget | null>(null);
  if (!options.data?.abilities.create) return null;
  return (
    <>
      <Button onClick={() => setTarget({ kind: "create", coqClass })} className={cn("pointer-coarse:h-11", className)}>
        <Plus />
        Add Quality Cost Item
      </Button>
      <CostRecordDialog target={target} onClose={() => setTarget(null)} />
    </>
  );
}

export function FinancialBadge({ record }: { record: Pick<CostRecord, "financialStatus" | "financialStatusLabel"> }) {
  return <StatusBadge tone={FINANCIAL_TONES[record.financialStatus]}>{record.financialStatusLabel}</StatusBadge>;
}

export function StatusLabel({ record }: { record: Pick<CostRecord, "status" | "statusLabel" | "overdue"> }) {
  return (
    <StatusBadge tone={record.status === "closed" ? "neutral" : record.overdue ? "warning" : "info"}>
      {record.statusLabel}
      {record.overdue ? " · overdue" : ""}
    </StatusBadge>
  );
}

export function ClassLabel({ record }: { record: Pick<CostRecord, "coqClass" | "coqClassLabel"> }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span aria-hidden className="size-2 rounded-full" style={{ backgroundColor: COQ_CLASS_COLORS[record.coqClass] }} />
      {record.coqClassLabel}
    </span>
  );
}

function Item({ label, children, wide }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={cn("min-w-0", wide && "sm:col-span-2 lg:col-span-3")}>
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm break-words whitespace-pre-line">{children}</dd>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border p-4">
      <h3 className="mb-3 text-sm font-semibold">{title}</h3>
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">{children}</dl>
    </section>
  );
}

const NOT_ENTERED = <span className="text-muted-foreground">Not entered</span>;

/** The CAR this item records the cost of. Nothing is shown to users who cannot view CARs. */
function LinkedCar({ recordId }: { recordId: number }) {
  const linked = useLinkedCars(recordId);
  if (!Array.isArray(linked.data) || linked.data.length === 0) return null;
  return (
    <Item label="Corrective Action Report" wide>
      {linked.data.map((car) => (
        <Link
          key={car.id}
          href={carHref(car.id)}
          className="font-medium text-primary underline-offset-2 hover:underline"
        >
          {car.carNumber}: {car.subject}
        </Link>
      ))}
    </Item>
  );
}

function text(value: string | null) {
  return value ?? NOT_ENTERED;
}

function money(value: string | null) {
  return value === null ? NOT_ENTERED : <span className="tabular-nums">{usd(value, 2)}</span>;
}

function RecordDetail({
  record,
  canEdit,
  options,
  notice,
  onEdit,
}: {
  record: CostRecord;
  canEdit: boolean;
  options: CostRecordOptions;
  notice: string | null;
  onEdit: () => void;
}) {
  const [showHistory, setShowHistory] = useState(false);
  return (
    <div className="space-y-4">
      {notice && (
        <p role="status" className="rounded-md border border-emerald-600/30 bg-emerald-600/10 px-3 py-2 text-sm text-emerald-800 dark:text-emerald-300">
          {notice}
        </p>
      )}
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-muted-foreground">
            {record.recordNumber} · {formatDate(record.recordDate)}
            {record.source === "legacy_import" && " · Imported"}
          </p>
          <h3 className="text-lg font-semibold">{record.title}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
            <ClassLabel record={record} />
            <span className="text-muted-foreground">·</span>
            <span>{record.categoryLabel}</span>
            <FinancialBadge record={record} />
            <StatusLabel record={record} />
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setShowHistory((value) => !value)} aria-expanded={showHistory} className="pointer-coarse:h-11">
            <History />
            History
          </Button>
          {canEdit && (
            <Button size="sm" onClick={onEdit} className="pointer-coarse:h-11">
              <Pencil />
              Edit
            </Button>
          )}
        </div>
      </header>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Figure label={record.costConfirmed ? "Total cost (confirmed)" : "Total cost (potential exposure)"} value={record.totalCost} muted={!record.costConfirmed} />
        <Figure label="Recovered" value={record.recoveredCost} />
        <Figure label="Net quality cost" value={record.netCost} muted={!record.costConfirmed} />
        <div className="rounded-lg border px-3 py-2">
          <p className="text-xs text-muted-foreground">{record.status === "closed" ? "Days open (closed)" : "Days open"}</p>
          <p className="text-lg font-semibold tabular-nums">{record.daysOpen}</p>
        </div>
      </div>

      {showHistory && <HistoryList record={record} />}

      <DetailSection title="Identification">
        <Item label="Date">{formatDate(record.recordDate)}</Item>
        <Item label="Area / department">{text(record.areaName)}</Item>
        <Item label="Product">{text(record.product)}</Item>
        <Item label="Campaign">{text(record.campaign)}</Item>
        <Item label="Lot / batch">{text(record.lot)}</Item>
        <Item label="Location">{text(record.location)}</Item>
        <Item label="Process">{text(record.process)}</Item>
        <Item label="Equipment">{text(record.equipment)}</Item>
        <Item label="Customer / supplier">{text(record.counterparty)}</Item>
        <Item label="Description" wide>
          {record.description}
        </Item>
      </DetailSection>

      <DetailSection title="Classification">
        <Item label="COQ classification">
          <ClassLabel record={record} />
        </Item>
        <Item label="Category">{record.categoryLabel}</Item>
        <Item label="Quality cost group">{record.qualityGroup === "good" ? "Good COQ (prevention + appraisal)" : "Poor COQ / COPQ (failure)"}</Item>
      </DetailSection>

      <DetailSection title="Cost breakdown">
        {options.costComponents.map((component) => (
          <Item key={component.field} label={component.label}>
            {money(record[component.field])}
          </Item>
        ))}
        <Item label="Estimated total cost">{record.totalCost === null ? "No cost entered" : money(record.totalCost)}</Item>
      </DetailSection>

      <DetailSection title="Financial and operational status">
        <Item label="Financial status">
          <FinancialBadge record={record} />
        </Item>
        <Item label="Status">{record.statusLabel}</Item>
        <Item label="Owner">{text(record.owner)}</Item>
        <Item label="Due date">{record.dueDate ? formatDate(record.dueDate) : NOT_ENTERED}</Item>
        <Item label="Date closed">{record.dateClosed ? formatDate(record.dateClosed) : <span className="text-muted-foreground">Not closed</span>}</Item>
        <Item label="Days open">{record.daysOpen}</Item>
        <Item label="Action / resolution notes" wide>
          {text(record.resolutionNotes)}
        </Item>
      </DetailSection>

      <DetailSection title="Recovery and avoidance">
        <Item label="Recovered cost">{money(record.recoveredCost)}</Item>
        <Item label="Avoided cost">{money(record.avoidedCost)}</Item>
        <Item label="Net quality cost">{money(record.netCost)}</Item>
      </DetailSection>

      <DetailSection title="Related records and notes">
        <Item label="Related records" wide>
          {record.references.length === 0
            ? NOT_ENTERED
            : record.references.map((ref) => `${ref.typeLabel}: ${ref.key}${ref.label ? ` (${ref.label})` : ""}`).join("\n")}
        </Item>
        <LinkedCar recordId={record.id} />
        <Item label="Notes" wide>
          {text(record.notes)}
        </Item>
      </DetailSection>

      <DetailSection title="Audit">
        <Item label="Created">
          {formatTimestamp(record.createdAt)} by {record.createdByName}
        </Item>
        <Item label="Last updated">
          {formatTimestamp(record.updatedAt)} by {record.updatedByName}
        </Item>
        <Item label="Version">{record.version}</Item>
        <Item label="Source">{record.source === "legacy_import" ? "Imported from the COQ workbook" : "Entered in the platform"}</Item>
      </DetailSection>
    </div>
  );
}

function Figure({ label, value, muted }: { label: string; value: string | null; muted?: boolean }) {
  return (
    <div className={cn("rounded-lg border px-3 py-2", muted && "border-dashed")}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("text-lg font-semibold tabular-nums", muted && "text-muted-foreground")}>
        {value === null ? "—" : usd(value, 2)}
      </p>
    </div>
  );
}

function humanize(field: string) {
  const text = field.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function shown(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.map((item) => (item as { key?: string }).key ?? JSON.stringify(item)).join(", ") || "—";
  return String(value);
}

export function historyChanges(event: CostHistoryEvent): { field: string; from: string; to: string }[] {
  const before = event.oldValue ?? {};
  const after = event.newValue ?? {};
  return Object.keys(after)
    // A person's user ID changes together with their name, which is what is shown.
    .filter((field) => field !== "version" && !field.endsWith("_user_id"))
    .filter((field) => JSON.stringify(before[field]) !== JSON.stringify(after[field]))
    .filter((field) => event.action !== "create" || (after[field] !== null && !(Array.isArray(after[field]) && (after[field] as unknown[]).length === 0)))
    .map((field) => ({ field: humanize(field), from: shown(before[field]), to: shown(after[field]) }));
}

function HistoryList({ record }: { record: CostRecord }) {
  const history = useCostRecordHistory(record.id);
  return (
    <section className="rounded-lg border p-4" aria-label="History">
      <h3 className="mb-2 text-sm font-semibold">History</h3>
      {history.isError ? (
        <p className="text-sm text-destructive">{describeCostError(history.error)}</p>
      ) : !history.data ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <ol className="space-y-3">
          {history.data.events.map((event) => (
            <li key={`${event.changeSetId}-${event.occurredAt}`} className="text-sm">
              <p className="font-medium">
                {event.action === "create" ? "Created" : "Updated"} {formatTimestamp(event.occurredAt)} by {event.actorName}
              </p>
              <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                {historyChanges(event).map((change) => (
                  <li key={change.field}>
                    <span className="font-medium text-foreground">{change.field}:</span>{" "}
                    {event.action === "create" ? change.to : `${change.from} → ${change.to}`}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
