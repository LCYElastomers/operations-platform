"use client";

import { AlertTriangle, ArrowLeft, Ban, History, ListChecks, Pencil, Plus, Repeat2 } from "lucide-react";
import Link from "next/link";
import { useId, useMemo, useState } from "react";

import { StatusBadge, type StatusTone } from "@/components/common/status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

import { describeSafetyError } from "../api";
import {
  recordError,
  type EventType,
  type IncidentRecord,
  type MonthReconciliation,
  type RecordFields,
  type RecordOption,
  type RecordPermissions,
  type RecordStatus,
} from "./api";
import {
  describeReconciliation,
  EVENT_LABELS,
  formatRecordDate,
  historyChanges,
  monthDateRange,
  monthTitle,
  OTHER_EVENT,
  recordName,
  STATUS_LABELS,
  stateShort,
  stateTone,
} from "./record-data";
import {
  useCreateRecord,
  useReclassifyRecord,
  useRecordHistory,
  useRecordOptions,
  useRecords,
  useUpdateRecord,
  useVoidRecord,
} from "./use-records";

export type RecordDialogScope =
  | { kind: "month"; eventType: EventType; year: number; month: number; reconciliation?: MonthReconciliation }
  | { kind: "register" };

export type RecordPanel =
  | { kind: "list" }
  | { kind: "create"; eventType: EventType }
  | { kind: "edit" | "history" | "void" | "reclassify"; record: IncidentRecord };

type RecordDialogProps = {
  open: boolean;
  onClose: () => void;
  scope: RecordDialogScope;
  /** Month scope starts on the list; Register scope opens one action. */
  initialPanel?: RecordPanel;
  permissions: RecordPermissions;
  /** The Baytown date, ISO. */
  today: string;
};

const STATUS_TONES: Record<RecordStatus, StatusTone> = { active: "success", voided: "neutral", reclassified: "info" };
const STATE_TONES = { ok: "success", warning: "warning", neutral: "neutral" } as const;
const ALL_STATUSES: RecordStatus[] = ["active", "voided", "reclassified"];

const fieldClasses = cn(
  "w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none",
  "focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 disabled:opacity-60",
  "aria-invalid:border-destructive pointer-coarse:text-base",
);

export function RecordStatusBadge({ status }: { status: RecordStatus }) {
  return <StatusBadge tone={STATUS_TONES[status]}>{STATUS_LABELS[status]}</StatusBadge>;
}

/** Records of one month and event type, or a single Register action, in a modal dialog. */
export function RecordDialog({ open, onClose, scope, initialPanel, permissions, today }: RecordDialogProps) {
  const [panel, setPanel] = useState<RecordPanel>(initialPanel ?? { kind: "list" });
  const [notice, setNotice] = useState<string | null>(null);
  const options = useRecordOptions(open);

  // In the Register a finished action closes the dialog; in a month it returns to the list.
  const done = (message: string | null) => {
    setNotice(message);
    if (scope.kind === "register") onClose();
    else setPanel({ kind: "list" });
  };
  const back = () => done(null);

  const title =
    scope.kind === "month"
      ? monthTitle(scope.eventType, scope.year, scope.month)
      : panel.kind === "create"
        ? `Add ${EVENT_LABELS[panel.eventType].one}`
        : panel.kind === "list"
          ? "Records"
          : recordName(panel.record);

  const context =
    scope.kind === "month"
      ? { reportingYear: scope.year, reportingMonth: scope.month }
      : undefined;

  return (
    <Dialog open={open} onClose={onClose} title={title} description={panelDescription(panel)}>
      {scope.kind === "month" && panel.kind !== "list" && (
        <Button variant="ghost" size="sm" onClick={back} className="mb-3 -ml-2 pointer-coarse:h-11">
          <ArrowLeft />
          Back to {monthTitle(scope.eventType, scope.year, scope.month)}
        </Button>
      )}
      {panel.kind === "list" && scope.kind === "month" && (
        <MonthList scope={scope} permissions={permissions} today={today} notice={notice} onPanel={setPanel} />
      )}
      {(panel.kind === "create" || panel.kind === "edit") && (
        <RecordForm
          key={panel.kind === "edit" ? `${panel.record.id}:${panel.record.version}` : "create"}
          eventType={panel.kind === "create" ? panel.eventType : panel.record.eventType}
          record={panel.kind === "edit" ? panel.record : null}
          context={context}
          options={options.data}
          today={today}
          onCancel={back}
          onSaved={(record, created) =>
            done(`${created ? "Added" : "Saved"} ${recordName(record)}.`)
          }
          onReload={(record) => setPanel({ kind: "edit", record })}
        />
      )}
      {panel.kind === "void" && (
        <VoidForm
          key={panel.record.version}
          record={panel.record}
          onCancel={back}
          onDone={(record) => done(`Voided ${recordName(record)}. It stays on file with its history.`)}
          onReload={(record) => setPanel({ kind: "void", record })}
        />
      )}
      {panel.kind === "reclassify" && (
        <ReclassifyForm
          key={panel.record.version}
          record={panel.record}
          options={options.data}
          today={today}
          onCancel={back}
          onDone={(record, replacement) =>
            done(`Reclassified ${recordName(record)} as ${EVENT_LABELS[replacement.eventType].one} ${recordName(replacement)}.`)
          }
          onReload={(record) => setPanel({ kind: "reclassify", record })}
        />
      )}
      {panel.kind === "history" && <HistoryList record={panel.record} options={options.data} />}
    </Dialog>
  );
}

function panelDescription(panel: RecordPanel): string | undefined {
  switch (panel.kind) {
    case "create":
      return "The monthly total is not changed by adding a record.";
    case "edit":
      return `Editing ${recordName(panel.record)}. The event type cannot be edited; reclassify instead.`;
    case "void":
      return `Void ${recordName(panel.record)}. Nothing is deleted.`;
    case "reclassify":
      return `Reclassify ${recordName(panel.record)} as a ${EVENT_LABELS[OTHER_EVENT[panel.record.eventType]].one}.`;
    case "history":
      return `Every change to ${recordName(panel.record)}, oldest first.`;
    default:
      return undefined;
  }
}

// Month list ------------------------------------------------------------------------

function MonthList({
  scope,
  permissions,
  today,
  notice,
  onPanel,
}: {
  scope: Extract<RecordDialogScope, { kind: "month" }>;
  permissions: RecordPermissions;
  today: string;
  notice: string | null;
  onPanel: (panel: RecordPanel) => void;
}) {
  const [showInactive, setShowInactive] = useState(false);
  const toggleId = useId();
  const records = useRecords({
    year: scope.year,
    month: scope.month,
    eventType: scope.eventType,
    statuses: showInactive ? ALL_STATUSES : ["active"],
  });
  const reconciliation = scope.reconciliation;
  const started = monthDateRange(scope.year, scope.month, today) !== null;
  const kind = EVENT_LABELS[scope.eventType];
  const register = `/safety/incidents/dashboard?view=register&year=${scope.year}&month=${scope.month}&eventType=${scope.eventType}`;

  return (
    <div className="space-y-4">
      {reconciliation && (
        <dl className="grid grid-cols-3 gap-2 rounded-lg border bg-card p-3 text-sm">
          <div>
            <dt className="text-xs text-muted-foreground">Reported total</dt>
            <dd className="text-lg font-semibold tabular-nums">
              {reconciliation.monthlyTotal ?? <span className="text-muted-foreground">Not reported</span>}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Documented records</dt>
            <dd className="text-lg font-semibold tabular-nums">{reconciliation.documented}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Status</dt>
            <dd className="pt-1">
              <StatusBadge tone={STATE_TONES[stateTone(reconciliation.state)]}>
                {stateShort(reconciliation.state)}
              </StatusBadge>
            </dd>
          </div>
          <p className="col-span-3 text-xs text-muted-foreground">
            {describeReconciliation(reconciliation)} The monthly total is authoritative; differences are warnings only.
          </p>
        </dl>
      )}

      {notice && (
        <p role="status" className="rounded-md border border-success/30 bg-success/10 px-3 py-2 text-sm text-success">
          {notice}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {permissions.canEdit && started && (
          <Button onClick={() => onPanel({ kind: "create", eventType: scope.eventType })} className="pointer-coarse:h-11">
            <Plus />
            Add record
          </Button>
        )}
        <Link href={register} className={cn(buttonVariants({ variant: "outline" }), "pointer-coarse:h-11")}>
          <ListChecks />
          Open Incident Register
        </Link>
        <label htmlFor={toggleId} className="ml-auto flex min-h-9 items-center gap-2 text-sm pointer-coarse:min-h-11">
          <input
            id={toggleId}
            type="checkbox"
            checked={showInactive}
            onChange={(event) => setShowInactive(event.target.checked)}
            className="size-4 accent-primary"
          />
          Show voided and reclassified
        </label>
      </div>

      {records.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {describeSafetyError(records.error)}
        </p>
      ) : !records.data ? (
        <p className="text-sm text-muted-foreground">Loading records…</p>
      ) : records.data.records.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
          No {showInactive ? "" : "active "}
          {kind.one} records for this month.
        </p>
      ) : (
        <ul className="space-y-3" aria-label={`${kind.one} records`}>
          {records.data.records.map((record) => (
            <li key={record.id}>
              <RecordCard record={record} permissions={records.data} onPanel={onPanel} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function RecordActions({
  record,
  permissions,
  onPanel,
  compact = false,
}: {
  record: IncidentRecord;
  permissions: RecordPermissions;
  onPanel: (panel: RecordPanel) => void;
  compact?: boolean;
}) {
  const name = recordName(record);
  const active = record.status === "active";
  const actions: [RecordPanel["kind"], string, React.ComponentType, boolean][] = [
    ["edit", "Edit", Pencil, permissions.canEdit && active],
    ["history", "View history", History, permissions.canViewHistory],
    ["void", "Void", Ban, permissions.canManage && active],
    ["reclassify", "Reclassify", Repeat2, permissions.canManage && active],
  ];
  return (
    <div className="flex flex-wrap gap-1.5">
      {actions
        .filter(([, , , allowed]) => allowed)
        .map(([kind, label, Icon]) => (
          <Button
            key={kind}
            variant="outline"
            size="sm"
            aria-label={`${label} ${name}`}
            onClick={() => onPanel({ kind, record } as RecordPanel)}
            className="pointer-coarse:h-11"
          >
            <Icon />
            <span className={cn(compact && "max-xl:sr-only")}>{label}</span>
          </Button>
        ))}
    </div>
  );
}

function RecordCard({
  record,
  permissions,
  onPanel,
}: {
  record: IncidentRecord;
  permissions: RecordPermissions;
  onPanel: (panel: RecordPanel) => void;
}) {
  return (
    <article className={cn("rounded-lg border bg-card p-3", record.status !== "active" && "bg-muted/40")}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h3 className="font-semibold tabular-nums">{record.incidentNumber ?? "No number"}</h3>
        <span className="text-sm text-muted-foreground">{formatRecordDate(record.incidentDate)}</span>
        <RecordStatusBadge status={record.status} />
        {record.source === "legacy_import" && <StatusBadge tone="info">Imported</StatusBadge>}
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        {record.areaName ?? "No area"} · {record.classificationName ?? "Unclassified"}
      </p>
      <p className="mt-2 text-sm whitespace-pre-line">{record.description}</p>
      {record.status !== "active" && (
        <p className="mt-2 text-xs text-muted-foreground">
          {STATUS_LABELS[record.status]}: {record.statusReason}
          {record.relatedIncidentNumber && ` · Replaced by ${record.relatedIncidentNumber}`}
        </p>
      )}
      <div className="mt-3">
        <RecordActions record={record} permissions={permissions} onPanel={onPanel} />
      </div>
    </article>
  );
}

// Forms -----------------------------------------------------------------------------

type Draft = {
  incidentNumber: string;
  incidentDate: string;
  description: string;
  areaId: string;
  classificationId: string;
};

function draftOf(record: IncidentRecord | null, fallbackDate: string): Draft {
  return {
    incidentNumber: record?.incidentNumber ?? "",
    incidentDate: record?.incidentDate ?? fallbackDate,
    description: record?.description ?? "",
    areaId: record?.areaId ? String(record.areaId) : "",
    classificationId: record?.classificationCategoryId ? String(record.classificationCategoryId) : "",
  };
}

function fieldsOf(draft: Draft): RecordFields {
  return {
    incidentNumber: draft.incidentNumber.trim() || null,
    incidentDate: draft.incidentDate,
    description: draft.description,
    areaId: draft.areaId ? Number(draft.areaId) : null,
    classificationCategoryId: draft.classificationId ? Number(draft.classificationId) : null,
  };
}

/** Problems the browser can see before asking the API; the API checks everything again. */
function draftProblems(draft: Draft, range: { min: string; max: string } | null): Partial<Record<keyof Draft, string>> {
  const problems: Partial<Record<keyof Draft, string>> = {};
  if (!draft.incidentDate) problems.incidentDate = "Enter the date of the event.";
  else if (range && (draft.incidentDate < range.min || draft.incidentDate > range.max))
    problems.incidentDate = `Enter a date from ${formatRecordDate(range.min)} to ${formatRecordDate(range.max)}.`;
  if (!draft.description.trim()) problems.description = "Describe what happened.";
  return problems;
}

/** Active options, plus the record's own inactive one so an unchanged value stays valid. */
function choices(options: RecordOption[] | undefined, current: number | null) {
  return (options ?? []).filter((option) => option.active || option.id === current);
}

type SaveProblem = { message: string; field: string | null; conflict: IncidentRecord | null };

function saveProblem(error: unknown): SaveProblem {
  const known = recordError(error);
  const current =
    known?.conflict && error && typeof error === "object" && "detail" in error
      ? ((error as { detail?: { current?: IncidentRecord } }).detail?.current ?? null)
      : null;
  return {
    message: known?.message ?? `Nothing was saved. ${describeSafetyError(error)}`,
    field: known?.field ?? null,
    conflict: current,
  };
}

function ProblemAlert({ problem, onReload }: { problem: SaveProblem; onReload: (record: IncidentRecord) => void }) {
  return (
    <div role="alert" className="flex flex-col gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive sm:flex-row sm:items-center">
      <p className="flex flex-1 items-start gap-2">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        {problem.message}
      </p>
      {problem.conflict && (
        <Button variant="outline" size="sm" onClick={() => onReload(problem.conflict!)} className="pointer-coarse:h-11">
          Load the latest version
        </Button>
      )}
    </div>
  );
}

function Field({
  label,
  hint,
  error,
  children,
  id,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
  id: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

function RecordFieldsEditor({
  draft,
  onChange,
  eventType,
  range,
  problems,
  options,
  record,
}: {
  draft: Draft;
  onChange: (draft: Draft) => void;
  eventType: EventType;
  range: { min: string; max: string } | null;
  problems: Partial<Record<keyof Draft | string, string>>;
  options: { areas: RecordOption[]; classifications: RecordOption[] } | undefined;
  record: IncidentRecord | null;
}) {
  const id = useId();
  const set = (key: keyof Draft) => (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    onChange({ ...draft, [key]: event.target.value });
  const described = (key: string, hint: boolean) =>
    problems[key] ? `${id}-${key}-error` : hint ? `${id}-${key}-hint` : undefined;
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div className="flex flex-col gap-1">
        <span className="text-sm font-medium">Event type</span>
        <p className="flex h-9 items-center rounded-md border bg-muted/50 px-3 text-sm" aria-readonly>
          {EVENT_LABELS[eventType].one}
        </p>
      </div>
      <Field id={`${id}-incidentNumber`} label="Number (optional)" hint="Saved in the form LCY-2026-037." error={problems.incidentNumber}>
        <input
          id={`${id}-incidentNumber`}
          value={draft.incidentNumber}
          onChange={set("incidentNumber")}
          maxLength={40}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={problems.incidentNumber ? true : undefined}
          aria-describedby={described("incidentNumber", true)}
          className={cn(fieldClasses, "h-9 pointer-coarse:h-11")}
        />
      </Field>
      <Field id={`${id}-incidentDate`} label="Date" error={problems.incidentDate}>
        <input
          id={`${id}-incidentDate`}
          type="date"
          required
          value={draft.incidentDate}
          min={range?.min}
          max={range?.max}
          onChange={set("incidentDate")}
          aria-invalid={problems.incidentDate ? true : undefined}
          aria-describedby={described("incidentDate", false)}
          className={cn(fieldClasses, "h-9 pointer-coarse:h-11")}
        />
      </Field>
      <Field id={`${id}-areaId`} label="Area (optional)" error={problems.areaId}>
        <select
          id={`${id}-areaId`}
          value={draft.areaId}
          onChange={set("areaId")}
          aria-invalid={problems.areaId ? true : undefined}
          aria-describedby={described("areaId", false)}
          className={cn(fieldClasses, "h-9 pointer-coarse:h-11")}
        >
          <option value="">Not recorded</option>
          {choices(options?.areas, record?.areaId ?? null).map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
              {option.active ? "" : " (inactive)"}
            </option>
          ))}
        </select>
      </Field>
      <Field
        id={`${id}-classificationCategoryId`}
        label="Classification (optional)"
        error={problems.classificationCategoryId}
      >
        <select
          id={`${id}-classificationCategoryId`}
          value={draft.classificationId}
          onChange={set("classificationId")}
          aria-invalid={problems.classificationCategoryId ? true : undefined}
          aria-describedby={described("classificationCategoryId", false)}
          className={cn(fieldClasses, "h-9 pointer-coarse:h-11")}
        >
          <option value="">Unclassified</option>
          {choices(options?.classifications, record?.classificationCategoryId ?? null).map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
              {option.active ? "" : " (inactive)"}
            </option>
          ))}
        </select>
      </Field>
      <div className="sm:col-span-2">
        <Field id={`${id}-description`} label="Description" error={problems.description}>
          <textarea
            id={`${id}-description`}
            required
            rows={5}
            maxLength={4000}
            value={draft.description}
            onChange={set("description")}
            aria-invalid={problems.description ? true : undefined}
            aria-describedby={described("description", false)}
            className={cn(fieldClasses, "py-2")}
          />
        </Field>
      </div>
    </div>
  );
}

function FormButtons({ saving, label, onCancel }: { saving: boolean; label: string; onCancel: () => void }) {
  return (
    <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
      <Button variant="outline" onClick={onCancel} disabled={saving} className="pointer-coarse:h-11">
        Cancel
      </Button>
      <Button type="submit" disabled={saving} className="pointer-coarse:h-11">
        {saving ? "Saving…" : label}
      </Button>
    </div>
  );
}

/** The record's own month for edits (records never move month); the dialog's month or open range for new ones. */
function dateRange(
  record: IncidentRecord | null,
  context: { reportingYear: number; reportingMonth: number } | undefined,
  today: string,
) {
  if (record) return monthDateRange(record.reportingYear, record.reportingMonth, today);
  if (context) return monthDateRange(context.reportingYear, context.reportingMonth, today);
  return { min: "2000-01-01", max: today };
}

function RecordForm({
  eventType,
  record,
  context,
  options,
  today,
  onCancel,
  onSaved,
  onReload,
}: {
  eventType: EventType;
  record: IncidentRecord | null;
  context: { reportingYear: number; reportingMonth: number } | undefined;
  options: { areas: RecordOption[]; classifications: RecordOption[] } | undefined;
  today: string;
  onCancel: () => void;
  onSaved: (record: IncidentRecord, created: boolean) => void;
  onReload: (record: IncidentRecord) => void;
}) {
  const range = dateRange(record, context, today);
  const defaultDate = range && context && !record ? (today < range.max ? today : range.max) : "";
  const [draft, setDraft] = useState(() => draftOf(record, defaultDate));
  const [submitted, setSubmitted] = useState(false);
  const create = useCreateRecord();
  const update = useUpdateRecord();
  const mutation = record ? update : create;
  const local = draftProblems(draft, range);
  const problem = mutation.error ? saveProblem(mutation.error) : null;
  const problems: Record<string, string | undefined> = {
    ...(submitted ? local : {}),
    ...(problem?.field ? { [problem.field]: problem.message } : {}),
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (Object.keys(local).length > 0) return;
    const fields = fieldsOf(draft);
    if (record) {
      update.mutate(
        {
          id: record.id,
          body: {
            ...fields,
            reportingYear: record.reportingYear,
            reportingMonth: record.reportingMonth,
            version: record.version,
          },
        },
        { onSuccess: (response) => onSaved(response.record, false) },
      );
    } else {
      create.mutate({ ...fields, eventType, ...context }, { onSuccess: (response) => onSaved(response.record, true) });
    }
  };

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      {problem && <ProblemAlert problem={problem} onReload={onReload} />}
      <RecordFieldsEditor
        draft={draft}
        onChange={setDraft}
        eventType={eventType}
        range={range}
        problems={problems}
        options={options}
        record={record}
      />
      <FormButtons saving={mutation.isPending} label={record ? "Save" : "Save record"} onCancel={onCancel} />
    </form>
  );
}

function ReasonField({ value, onChange, error }: { value: string; onChange: (value: string) => void; error?: string }) {
  const id = useId();
  return (
    <Field id={id} label="Reason" error={error}>
      <textarea
        id={id}
        required
        rows={3}
        maxLength={500}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className={cn(fieldClasses, "py-2")}
      />
    </Field>
  );
}

function VoidForm({
  record,
  onCancel,
  onDone,
  onReload,
}: {
  record: IncidentRecord;
  onCancel: () => void;
  onDone: (record: IncidentRecord) => void;
  onReload: (record: IncidentRecord) => void;
}) {
  const [reason, setReason] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const mutation = useVoidRecord();
  const problem = mutation.error ? saveProblem(mutation.error) : null;
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (!reason.trim()) return;
    mutation.mutate(
      { id: record.id, body: { version: record.version, reason: reason.trim() } },
      { onSuccess: (response) => onDone(response.record) },
    );
  };
  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <p className="text-sm text-muted-foreground">
        A voided record stays on file with its history and is no longer counted as documented. The monthly total is
        not changed.
      </p>
      {problem && <ProblemAlert problem={problem} onReload={onReload} />}
      <ReasonField value={reason} onChange={setReason} error={submitted && !reason.trim() ? "Give a reason." : undefined} />
      <FormButtons saving={mutation.isPending} label="Void record" onCancel={onCancel} />
    </form>
  );
}

function ReclassifyForm({
  record,
  options,
  today,
  onCancel,
  onDone,
  onReload,
}: {
  record: IncidentRecord;
  options: { areas: RecordOption[]; classifications: RecordOption[] } | undefined;
  today: string;
  onCancel: () => void;
  onDone: (record: IncidentRecord, replacement: IncidentRecord) => void;
  onReload: (record: IncidentRecord) => void;
}) {
  const other = OTHER_EVENT[record.eventType];
  const [reason, setReason] = useState("");
  const [mode, setMode] = useState<"new" | "existing">("new");
  const [replacementId, setReplacementId] = useState("");
  const [draft, setDraft] = useState<Draft>(() => ({ ...draftOf(record, record.incidentDate), incidentNumber: "", classificationId: "" }));
  const [submitted, setSubmitted] = useState(false);
  const mutation = useReclassifyRecord();
  const candidates = useRecords(
    { year: record.reportingYear, month: record.reportingMonth, eventType: other },
    mode === "existing",
  );
  const range = monthDateRange(record.reportingYear, record.reportingMonth, today);
  const local = mode === "new" ? draftProblems(draft, range) : {};
  const problem = mutation.error ? saveProblem(mutation.error) : null;
  const radioName = useId();
  const otherLabel = EVENT_LABELS[other].one;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (!reason.trim() || Object.keys(local).length > 0 || (mode === "existing" && !replacementId)) return;
    const base = { version: record.version, reason: reason.trim() };
    mutation.mutate(
      {
        id: record.id,
        body: mode === "new" ? { ...base, replacement: fieldsOf(draft) } : { ...base, replacementId: Number(replacementId) },
      },
      { onSuccess: (response) => onDone(response.record, response.replacement) },
    );
  };

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <p className="text-sm text-muted-foreground">
        The {EVENT_LABELS[record.eventType].one} record is kept, marked reclassified and linked to its {otherLabel}{" "}
        replacement. Monthly totals are not changed.
      </p>
      {problem && <ProblemAlert problem={problem} onReload={onReload} />}
      <ReasonField value={reason} onChange={setReason} error={submitted && !reason.trim() ? "Give a reason." : undefined} />
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Replacement</legend>
        {(
          [
            ["new", `Create a new ${otherLabel} record`],
            ["existing", `Link an existing ${otherLabel} record`],
          ] as const
        ).map(([value, label]) => (
          <label key={value} className="flex min-h-9 items-center gap-2 text-sm pointer-coarse:min-h-11">
            <input
              type="radio"
              name={radioName}
              value={value}
              checked={mode === value}
              onChange={() => setMode(value)}
              className="size-4 accent-primary"
            />
            {label}
          </label>
        ))}
      </fieldset>
      {mode === "new" ? (
        <RecordFieldsEditor
          draft={draft}
          onChange={setDraft}
          eventType={other}
          range={range}
          problems={{ ...(submitted ? local : {}), ...(problem?.field ? { [problem.field]: problem.message } : {}) }}
          options={options}
          record={null}
        />
      ) : (
        <Field
          id={`${radioName}-existing`}
          label={`${otherLabel} record`}
          error={submitted && !replacementId ? `Choose a ${otherLabel} record.` : undefined}
        >
          <select
            id={`${radioName}-existing`}
            value={replacementId}
            onChange={(event) => setReplacementId(event.target.value)}
            className={cn(fieldClasses, "h-9 pointer-coarse:h-11")}
          >
            <option value="">
              {candidates.data?.records.length === 0 ? `No active ${otherLabel} records this month` : "Choose…"}
            </option>
            {candidates.data?.records.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {recordName(candidate)} · {formatRecordDate(candidate.incidentDate)}
              </option>
            ))}
          </select>
        </Field>
      )}
      <FormButtons saving={mutation.isPending} label="Reclassify" onCancel={onCancel} />
    </form>
  );
}

// History ---------------------------------------------------------------------------

function HistoryList({
  record,
  options,
}: {
  record: IncidentRecord;
  options: { areas: RecordOption[]; classifications: RecordOption[] } | undefined;
}) {
  const history = useRecordHistory(record.id);
  const names = useMemo(
    () => ({
      areas: new Map((options?.areas ?? []).map((option) => [option.id, option.name])),
      classifications: new Map((options?.classifications ?? []).map((option) => [option.id, option.name])),
    }),
    [options],
  );
  if (history.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {describeSafetyError(history.error)}
      </p>
    );
  }
  if (!history.data) return <p className="text-sm text-muted-foreground">Loading history…</p>;
  return (
    <ol className="space-y-3">
      {history.data.events.map((event) => {
        const changes = historyChanges(event.oldValue, event.newValue, names);
        const verb = event.oldValue === null ? "Created" : event.newValue?.status !== event.oldValue.status ? `Marked ${STATUS_LABELS[event.newValue?.status as RecordStatus]?.toLowerCase() ?? "changed"}` : "Edited";
        return (
          <li key={`${event.changeSetId}-${event.occurredAt}`} className="rounded-lg border bg-card p-3 text-sm">
            <p className="font-medium">
              {verb} by {event.actorId}
            </p>
            <p className="text-xs text-muted-foreground">
              <time dateTime={event.occurredAt}>{new Date(event.occurredAt).toLocaleString()}</time>
            </p>
            {changes.length > 0 && (
              <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1">
                {changes.map((change) => (
                  <div key={change.label} className="contents">
                    <dt className="text-muted-foreground">{change.label}</dt>
                    <dd className="break-words">
                      {change.from && (
                        <>
                          <del className="text-muted-foreground">{change.from}</del>
                          {" → "}
                        </>
                      )}
                      {change.to}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </li>
        );
      })}
    </ol>
  );
}
