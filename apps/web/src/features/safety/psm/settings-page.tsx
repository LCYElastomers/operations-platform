"use client";

import { FileSpreadsheet, Send } from "lucide-react";
import Link from "next/link";
import { useId, useRef, useState } from "react";

import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";
import { TableSection } from "@/features/quality/cost/cost-shared";
import { Field, inputClasses } from "@/features/quality/cost/record-form";

import {
  importWorkbook,
  MAX_FILE_BYTES,
  psmApi,
  RISK_LABELS,
  RISKS,
  studyHref,
  type ImportSummary,
  type NotificationSettings,
  type Option,
  type PsmOptions,
} from "./api";
import { EYEBROW, FormError, PsmError } from "./psm-shared";
import { useNotificationSettings, usePsmMutation, usePsmOptions } from "./use-psm";

/** PSM administration: reference lists, email notifications and the PHA workbook import. */
export function PsmSettingsPage({ title, description }: { title: string; description?: string }) {
  const options = usePsmOptions();
  if (options.isError) return <PsmError error={options.error} onRetry={() => void options.refetch()} />;
  if (!options.data) return <p className="py-6 text-sm text-muted-foreground">Loading…</p>;
  const a = options.data.abilities;
  return (
    <div className="space-y-5">
      <PageHeader eyebrow={EYEBROW} title={title} description={description} />
      {a.admin && (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
          <ReferenceList kind="departments" title="Departments" items={options.data.departments} />
          <ReferenceList kind="process-nodes" title="Process nodes" items={options.data.processNodes} />
        </div>
      )}
      {a.admin && <NotificationsPanel />}
      {a.importData && <ImportPanel options={options.data} />}
      {!a.admin && !a.importData && <p className="text-sm text-muted-foreground">You do not have permission to change PSM settings.</p>}
    </div>
  );
}

function ReferenceList({ kind, title, items }: { kind: "departments" | "process-nodes"; title: string; items: Option[] }) {
  const id = useId();
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<Option | null>(null);
  const [editName, setEditName] = useState("");
  const save = usePsmMutation(({ body, itemId }: { body: { name: string; active: boolean }; itemId?: number }) =>
    psmApi.saveReference(kind, body, itemId),
  );
  return (
    <TableSection id={`${id}-list`} title={title} description="Inactive entries stay on existing records but are no longer offered.">
      <ul className="divide-y">
        {items.length === 0 && <li className="px-4 py-3 text-sm text-muted-foreground">None yet.</li>}
        {items.map((item) => (
          <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-sm">
            {editing?.id === item.id ? (
              <input
                aria-label={`Rename ${item.name}`}
                value={editName}
                maxLength={1000}
                onChange={(e) => setEditName(e.target.value)}
                className={`${inputClasses} max-w-md flex-1`}
              />
            ) : (
              <span className="min-w-0 break-words">
                {item.name} {!item.active && <StatusBadge tone="neutral">Inactive</StatusBadge>}
              </span>
            )}
            <span className="flex gap-1">
              {editing?.id === item.id ? (
                <>
                  <Button
                    size="sm"
                    disabled={!editName.trim() || save.isPending}
                    onClick={() =>
                      save.mutate({ body: { name: editName.trim(), active: item.active }, itemId: item.id }, { onSuccess: () => setEditing(null) })
                    }
                  >
                    Save
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>
                    Cancel
                  </Button>
                </>
              ) : (
                <>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setEditing(item);
                      setEditName(item.name);
                    }}
                  >
                    Rename
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={save.isPending}
                    onClick={() => save.mutate({ body: { name: item.name, active: !item.active }, itemId: item.id })}
                  >
                    {item.active ? "Deactivate" : "Activate"}
                  </Button>
                </>
              )}
            </span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-end gap-2 border-t p-4">
        <Field id={`${id}-new`} label={`Add to ${title.toLowerCase()}`} className="flex-1">
          <input id={`${id}-new`} value={name} maxLength={1000} onChange={(e) => setName(e.target.value)} className={inputClasses} />
        </Field>
        <Button disabled={!name.trim() || save.isPending} onClick={() => save.mutate({ body: { name: name.trim(), active: true } }, { onSuccess: () => setName("") })}>
          Add
        </Button>
      </div>
      {save.error ? (
        <div className="px-4 pb-4">
          <FormError error={save.error} />
        </div>
      ) : null}
    </TableSection>
  );
}

const TOGGLES: [keyof NotificationSettings, string][] = [
  ["notifyOnAssignment", "When an action is assigned to someone"],
  ["notifyOnDueDateChange", "When an action's due date changes"],
  ["notifyOnStatusChange", "When an action's status changes (closure requested, returned, closed, reopened)"],
  ["notifyOnComment", "When a comment is added"],
  ["dueSoonReminders", "Reminders before the due date"],
  ["overdueReminders", "Reminders for overdue actions"],
];

function NotificationsPanel() {
  const settings = useNotificationSettings(true);
  if (settings.isError) return <PsmError error={settings.error} onRetry={() => void settings.refetch()} />;
  if (!settings.data) return <p className="text-sm text-muted-foreground">Loading notification settings…</p>;
  return <NotificationsForm initial={settings.data} />;
}

function NotificationsForm({ initial }: { initial: NotificationSettings }) {
  const id = useId();
  const [draft, setDraft] = useState(initial);
  const save = usePsmMutation((body: NotificationSettings) => psmApi.saveNotificationSettings(body));
  const deliver = usePsmMutation(() => psmApi.deliverNow());
  const daysValid = Number.isInteger(draft.dueSoonDays) && draft.dueSoonDays >= 1 && draft.dueSoonDays <= 60;
  return (
    <section className="space-y-4 rounded-lg border bg-card p-4 sm:p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Email notifications</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Notices are queued with each change and delivered separately; a delivery failure never undoes the change. The mail server is configured on the
            server, not here.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={deliver.isPending}
          onClick={() =>
            deliver.mutate(undefined, {
              onSuccess: (result) =>
                result.mailEnabled
                  ? toast("success", "Delivery attempted", `${result.sent} sent, ${result.failed} failed, ${result.queued} still queued.`)
                  : toast("info", "Email is not configured", "Nothing was sent. Queued notices stay queued."),
            })
          }
        >
          <Send />
          Send queued now
        </Button>
      </header>
      <fieldset className="space-y-2 text-sm">
        <legend className="sr-only">Notification events</legend>
        {TOGGLES.map(([key, label]) => (
          <label key={key} className="flex items-center gap-2">
            <input type="checkbox" checked={Boolean(draft[key])} onChange={(e) => setDraft({ ...draft, [key]: e.target.checked })} />
            {label}
          </label>
        ))}
      </fieldset>
      <Field id={`${id}-days`} label="Due-soon reminder window (days)" className="max-w-xs">
        <input
          id={`${id}-days`}
          type="number"
          min={1}
          max={60}
          value={Number.isNaN(draft.dueSoonDays) ? "" : draft.dueSoonDays}
          onChange={(e) => setDraft({ ...draft, dueSoonDays: e.target.valueAsNumber })}
          className={inputClasses}
        />
      </Field>
      <FormError error={save.error ?? deliver.error} />
      <div className="flex justify-end">
        <Button disabled={!daysValid || save.isPending} onClick={() => save.mutate(draft, { onSuccess: () => toast("success", "Notification settings saved") })}>
          {save.isPending ? "Saving…" : "Save notification settings"}
        </Button>
      </div>
    </section>
  );
}

function ImportPanel({ options }: { options: PsmOptions }) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [plan, setPlan] = useState<ImportSummary | null>(null);
  const [applied, setApplied] = useState<ImportSummary | null>(null);
  const planning = usePsmMutation((f: File) => importWorkbook("plan", f));
  const applying = usePsmMutation((f: File) => importWorkbook("apply", f));
  const tooLarge = file !== null && file.size > MAX_FILE_BYTES;
  const blocked = plan !== null && plan.plan.conflicts.length > 0;
  const nothingNew = plan !== null && plan.plan.newRecommendations === 0 && plan.plan.newScenarios === 0 && plan.plan.studyExists;

  return (
    <section id="import" className="scroll-mt-20 space-y-4 rounded-lg border bg-card p-4 sm:p-5">
      <header>
        <h2 className="flex items-center gap-2 text-base font-semibold">
          <FileSpreadsheet aria-hidden className="size-4" />
          Import the reviewed PHA workbook
        </h2>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Only the sheet “2026 PHA - 300,400,600” is read. First review what would be imported; nothing is saved until you apply. Importing again adds only
          what is missing and never overwrites stored records. New recommendations start in Pending Review with no action.
        </p>
      </header>
      <div className="flex flex-wrap items-end gap-3">
        <Field id={`${id}-file`} label="Workbook (.xlsx)">
          <input
            ref={input}
            id={`${id}-file`}
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setPlan(null);
              setApplied(null);
              planning.reset();
              applying.reset();
            }}
            className="text-sm file:mr-3 file:rounded-md file:border file:bg-card file:px-3 file:py-1.5 file:text-sm"
          />
        </Field>
        <Button variant="outline" disabled={!file || tooLarge || planning.isPending} onClick={() => file && planning.mutate(file, { onSuccess: setPlan })}>
          {planning.isPending ? "Reviewing…" : "Review import"}
        </Button>
      </div>
      {tooLarge && <p className="text-sm text-destructive">This file is larger than 10 MB.</p>}
      <FormError error={planning.error} />
      {plan && !applied && (
        <div className="space-y-3 rounded-md border p-4 text-sm">
          <p className="font-medium">
            {plan.study.title} ({plan.study.studyCode}) · {plan.source.sheetName}
          </p>
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <li>Recommendations in sheet: {plan.recommendations}</li>
            <li>Scenarios in sheet: {plan.scenarios}</li>
            {RISKS.map((risk) => (
              <li key={risk}>
                {RISK_LABELS[risk]} scenarios: {plan.risks[risk] ?? 0}
              </li>
            ))}
          </ul>
          <ul className="space-y-1">
            <li>{plan.plan.studyExists ? "The study already exists." : "The study will be created."}</li>
            <li>New recommendations: {plan.plan.newRecommendations}</li>
            <li>Already stored, left unchanged: {plan.plan.unchangedRecommendations}</li>
            <li>New scenarios: {plan.plan.newScenarios}</li>
            {plan.plan.newProcessNodes.length > 0 && <li>New process nodes: {plan.plan.newProcessNodes.length}</li>}
          </ul>
          {plan.plan.differences.length > 0 && (
            <div>
              <p className="font-medium">Stored records differ from the workbook (stored values are kept):</p>
              <ul className="list-disc pl-5 text-muted-foreground">
                {plan.plan.differences.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            </div>
          )}
          {blocked && (
            <div className="text-destructive">
              <p className="font-medium">The import cannot be applied:</p>
              <ul className="list-disc pl-5">
                {plan.plan.conflicts.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </div>
          )}
          <FormError error={applying.error} />
          <div className="flex justify-end">
            <Button
              disabled={!file || blocked || nothingNew || applying.isPending}
              onClick={() =>
                file &&
                applying.mutate(file, {
                  onSuccess: (result) => {
                    setApplied(result);
                    toast("success", "Workbook imported", `${result.created?.recommendations ?? 0} recommendations added.`);
                    if (input.current) input.current.value = "";
                  },
                })
              }
            >
              {nothingNew ? "Nothing new to import" : applying.isPending ? "Importing…" : "Apply import"}
            </Button>
          </div>
        </div>
      )}
      {applied && (
        <div className="space-y-1 rounded-md border border-success/30 bg-success/10 p-4 text-sm">
          <p className="font-medium">Imported.</p>
          <p>
            Added {applied.created?.recommendations ?? 0} recommendations, {applied.created?.scenarios ?? 0} scenarios and{" "}
            {applied.created?.processNodes ?? 0} process nodes.
          </p>
          {applied.studyId !== undefined && (
            <Link href={studyHref(applied.studyId)} className="text-primary hover:underline">
              View the study
            </Link>
          )}
        </div>
      )}
      {options.studies.length > 0 && !plan && (
        <p className="text-xs text-muted-foreground">{options.studies.length} {options.studies.length === 1 ? "study is" : "studies are"} already stored.</p>
      )}
    </section>
  );
}
