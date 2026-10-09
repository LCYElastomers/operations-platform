"use client";

import { CheckCircle2, Pencil, Plus } from "lucide-react";
import { useId, useState } from "react";

import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { siteToday } from "@/features/safety/site-calendar";
import { cn } from "@/lib/utils";

import { NotEntered } from "../cost/cost-shared";
import { formatDate } from "../cost/format";
import { Field, fieldClasses, inputClasses } from "../cost/record-form";

import { carSaveError, describeCarError, type Car, type CarAction, type CarOptions } from "./api";
import { actionDraftOf, actionFieldsOf, actionProblems, emptyActionDraft, type ActionDraft, type Problems } from "./car-draft";
import { useAddAction, useCompleteAction, useUpdateAction } from "./use-car";

const STATUS_TONES = { open: "info", in_progress: "info", complete: "success", on_hold: "warning" } as const;

function ActionStatusBadge({ action }: { action: CarAction }) {
  if (action.status === null) return <StatusBadge tone="neutral">{action.statusLabel}</StatusBadge>;
  return <StatusBadge tone={STATUS_TONES[action.status]}>{action.statusLabel}</StatusBadge>;
}

type Editing = { kind: "add" } | { kind: "edit"; action: CarAction } | { kind: "complete"; action: CarAction };

/**
 * The CAR's corrective actions. Each is added, edited and completed on its
 * own; the CAR cannot be closed while any is outstanding, and its status never
 * stands in for theirs.
 */
export function ActionsPanel({ car, canEdit, options }: { car: Car | null; canEdit: boolean; options: CarOptions }) {
  const [editing, setEditing] = useState<Editing | null>(null);
  if (car === null) {
    return (
      <p className="rounded-md border border-dashed px-4 py-3 text-sm text-muted-foreground">
        Save the CAR first, then add its corrective actions here.
      </p>
    );
  }
  const closed = car.status === "closed";
  const writable = canEdit && !closed;
  const { total, complete, outstanding, overdue } = car.actions;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm" aria-live="polite">
          {total === 0 ? (
            <span className="text-muted-foreground">No corrective actions recorded yet.</span>
          ) : (
            <>
              <span className="font-medium tabular-nums">
                {complete} of {total}
              </span>{" "}
              complete
              {outstanding > 0 && <span className="text-muted-foreground"> · {outstanding} outstanding</span>}
              {overdue > 0 && <span className="text-destructive"> · {overdue} overdue</span>}
            </>
          )}
        </p>
        {writable && (
          <Button variant="outline" size="sm" onClick={() => setEditing({ kind: "add" })}>
            <Plus />
            Add action
          </Button>
        )}
      </div>
      {closed && canEdit && (
        <p className="text-xs text-muted-foreground">This CAR is closed. Set its status to Open to change its actions.</p>
      )}
      {car.actionItems.length > 0 && (
        <ol className="divide-y rounded-md border">
          {car.actionItems.map((action) => (
            <li key={action.id} className="flex flex-col gap-2 px-3 py-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0 space-y-1">
                <p className="text-sm font-medium whitespace-pre-line">
                  <span className="mr-1.5 text-muted-foreground tabular-nums">{action.position}.</span>
                  {action.action}
                </p>
                <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <ActionStatusBadge action={action} />
                  {action.overdue && <StatusBadge tone="danger">Overdue</StatusBadge>}
                  <span>Owner: {action.owner ?? <NotEntered label="not recorded" />}</span>
                  <span>Target: {action.targetDate ? formatDate(action.targetDate) : <NotEntered label="not recorded" />}</span>
                  {action.status === "complete" && (
                    <span>
                      Completed: {action.completedOn ? formatDate(action.completedOn) : <NotEntered label="date not recorded" />}
                    </span>
                  )}
                </p>
                {(action.proceduresRevised || action.supportingDocuments || action.trainingCompleted !== null) && (
                  <dl className="grid grid-cols-1 gap-x-4 text-xs sm:grid-cols-[max-content_1fr]">
                    {action.proceduresRevised && (
                      <>
                        <dt className="text-muted-foreground">Procedures revised</dt>
                        <dd className="whitespace-pre-line">{action.proceduresRevised}</dd>
                      </>
                    )}
                    {action.trainingCompleted !== null && (
                      <>
                        <dt className="text-muted-foreground">Training completed</dt>
                        <dd>{action.trainingCompleted ? "Yes" : "No"}</dd>
                      </>
                    )}
                    {action.supportingDocuments && (
                      <>
                        <dt className="text-muted-foreground">Supporting documents</dt>
                        <dd className="whitespace-pre-line">{action.supportingDocuments}</dd>
                      </>
                    )}
                  </dl>
                )}
              </div>
              {writable && (
                <div className="flex shrink-0 gap-2">
                  <Button variant="ghost" size="sm" onClick={() => setEditing({ kind: "edit", action })}>
                    <Pencil />
                    Edit
                  </Button>
                  {action.status !== "complete" && (
                    <Button variant="outline" size="sm" onClick={() => setEditing({ kind: "complete", action })}>
                      <CheckCircle2 />
                      Complete
                    </Button>
                  )}
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
      {editing?.kind === "complete" ? (
        <CompleteActionDialog car={car} action={editing.action} onClose={() => setEditing(null)} />
      ) : (
        <ActionDialog
          car={car}
          action={editing?.kind === "edit" ? editing.action : null}
          open={editing !== null}
          options={options}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

function ActionDialog({
  car,
  action,
  open,
  options,
  onClose,
}: {
  car: Car;
  action: CarAction | null;
  open: boolean;
  options: CarOptions;
  onClose: () => void;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={action ? `Edit action ${action.position}` : "Add corrective action"}
      description={`${car.carNumber}: ${car.subject}`}
    >
      {open && (
        <ActionForm key={action?.id ?? "new"} car={car} action={action} options={options} onDone={onClose} />
      )}
    </Dialog>
  );
}

function ActionForm({
  car,
  action,
  options,
  onDone,
}: {
  car: Car;
  action: CarAction | null;
  options: CarOptions;
  onDone: () => void;
}) {
  const id = useId();
  const [today] = useState(siteToday);
  const [draft, setDraft] = useState<ActionDraft>(() => (action ? actionDraftOf(action) : emptyActionDraft()));
  const [touched, setTouched] = useState(false);
  const [serverProblem, setServerProblem] = useState<{ message: string; field: string | null } | null>(null);
  const add = useAddAction();
  const update = useUpdateAction();
  const pending = add.isPending || update.isPending;
  const problems: Problems = touched ? actionProblems(draft, today, action) : {};
  if (serverProblem?.field && !problems[serverProblem.field]) problems[serverProblem.field] = serverProblem.message;

  const set = (patch: Partial<ActionDraft>) => {
    setDraft({ ...draft, ...patch });
    setServerProblem(null);
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (Object.keys(actionProblems(draft, today, action)).length > 0) return;
    const onError = (error: unknown) => {
      const problem = carSaveError(error);
      setServerProblem(problem ?? { message: describeCarError(error), field: null });
    };
    const body = actionFieldsOf(draft);
    if (action) {
      update.mutate(
        { carId: car.id, actionId: action.id, body: { ...body, version: action.version } },
        { onSuccess: onDone, onError },
      );
    } else {
      add.mutate({ carId: car.id, body }, { onSuccess: onDone, onError });
    }
  };

  const fieldId = (name: string) => `${id}-${name}`;
  const statusOptions = options.actionStatuses;
  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <Field id={fieldId("action")} label="Action" required error={problems.action}>
        <textarea
          id={fieldId("action")}
          rows={3}
          maxLength={8000}
          value={draft.action}
          onChange={(event) => set({ action: event.target.value })}
          aria-invalid={problems.action ? true : undefined}
          className={cn(fieldClasses, "py-2")}
        />
      </Field>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field id={fieldId("owner")} label="Responsible">
          <input
            id={fieldId("owner")}
            maxLength={200}
            list={`${fieldId("owner")}-list`}
            value={draft.owner}
            onChange={(event) => set({ owner: event.target.value })}
            className={inputClasses}
          />
          <datalist id={`${fieldId("owner")}-list`}>
            {options.people.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        </Field>
        <Field id={fieldId("targetDate")} label="Target date">
          <input
            id={fieldId("targetDate")}
            type="date"
            value={draft.targetDate}
            onChange={(event) => set({ targetDate: event.target.value })}
            className={inputClasses}
          />
        </Field>
        <Field id={fieldId("status")} label="Status" required error={problems.status}>
          <select
            id={fieldId("status")}
            value={draft.status}
            onChange={(event) => set({ status: event.target.value as ActionDraft["status"] })}
            aria-invalid={problems.status ? true : undefined}
            className={inputClasses}
          >
            {draft.status === "" && <option value="">Not recorded</option>}
            {statusOptions.map((option) => (
              <option key={option.code} value={option.code}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
        {draft.status === "complete" && (
          <Field
            id={fieldId("completedOn")}
            label="Completed on"
            required={!(action?.status === "complete" && action.completedOn === null)}
            error={problems.completedOn}
          >
            <input
              id={fieldId("completedOn")}
              type="date"
              max={today}
              value={draft.completedOn}
              onChange={(event) => set({ completedOn: event.target.value })}
              aria-invalid={problems.completedOn ? true : undefined}
              className={inputClasses}
            />
          </Field>
        )}
        <Field id={fieldId("training")} label="Training completed">
          <select
            id={fieldId("training")}
            value={draft.trainingCompleted}
            onChange={(event) => set({ trainingCompleted: event.target.value as ActionDraft["trainingCompleted"] })}
            className={inputClasses}
          >
            <option value="">Not recorded</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </Field>
      </div>
      <Field id={fieldId("procedures")} label="Procedures revised">
        <textarea
          id={fieldId("procedures")}
          rows={2}
          maxLength={8000}
          value={draft.proceduresRevised}
          onChange={(event) => set({ proceduresRevised: event.target.value })}
          className={cn(fieldClasses, "py-2")}
        />
      </Field>
      <Field id={fieldId("documents")} label="Supporting documents">
        <textarea
          id={fieldId("documents")}
          rows={2}
          maxLength={8000}
          value={draft.supportingDocuments}
          onChange={(event) => set({ supportingDocuments: event.target.value })}
          className={cn(fieldClasses, "py-2")}
        />
      </Field>
      {serverProblem && !serverProblem.field && (
        <p role="alert" className="text-sm text-destructive">
          {serverProblem.message}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onDone} disabled={pending}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending}>
          {pending ? "Saving…" : action ? "Save action" : "Add action"}
        </Button>
      </div>
    </form>
  );
}

function CompleteActionDialog({ car, action, onClose }: { car: Car; action: CarAction; onClose: () => void }) {
  const id = useId();
  const [today] = useState(siteToday);
  const [completedOn, setCompletedOn] = useState(today);
  const [problem, setProblem] = useState<string | null>(null);
  const complete = useCompleteAction();
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!completedOn) return setProblem("Enter the date the action was completed.");
    if (completedOn > today) return setProblem("The completion date cannot be in the future.");
    complete.mutate(
      { carId: car.id, actionId: action.id, body: { version: action.version, completedOn } },
      {
        onSuccess: onClose,
        onError: (error) => setProblem(carSaveError(error)?.message ?? describeCarError(error)),
      },
    );
  };
  return (
    <Dialog open onClose={onClose} title={`Complete action ${action.position}`} description={action.action}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <Field id={`${id}-completed`} label="Completed on" required error={problem ?? undefined}>
          <input
            id={`${id}-completed`}
            type="date"
            max={today}
            value={completedOn}
            onChange={(event) => {
              setCompletedOn(event.target.value);
              setProblem(null);
            }}
            aria-invalid={problem ? true : undefined}
            className={inputClasses}
          />
        </Field>
        <p className="text-xs text-muted-foreground">
          Completing an action does not record the CAR&apos;s effectiveness review. That is a separate step (6 Verify).
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={complete.isPending}>
            Cancel
          </Button>
          <Button type="submit" disabled={complete.isPending}>
            {complete.isPending ? "Saving…" : "Mark complete"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
