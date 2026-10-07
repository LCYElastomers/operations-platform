"use client";

import { LoaderCircle, Pencil, Trash2 } from "lucide-react";
import { useEffect, useId, useRef } from "react";

import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { Supervisor } from "./api";
import {
  EARLIEST_DATE,
  formatDate,
  MAX_DISPLAY_NAME_LENGTH,
  type SupervisorDraft,
  type SupervisorDraftErrors,
} from "./contact-data";
import { actionClasses, DeleteConfirmation, fieldClasses, useConfirmFocus } from "./recent-contacts";

const checkClasses = cn(
  "flex min-h-11 cursor-pointer items-center gap-3 rounded-md border bg-background px-3 py-2 text-sm",
  "has-checked:border-primary/60 has-focus-visible:ring-2 has-focus-visible:ring-ring/50",
  "has-disabled:cursor-not-allowed has-disabled:opacity-60",
);

function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <span id={id} className="text-xs font-medium text-destructive">
      {message}
    </span>
  );
}

type SupervisorFormProps = {
  draft: SupervisorDraft;
  onChange: (draft: SupervisorDraft) => void;
  onSubmit: () => void;
  onCancel?: () => void;
  errors: SupervisorDraftErrors;
  /** Validation messages are shown only after a save was attempted. */
  showErrors: boolean;
  submitLabel: string;
  pending?: boolean;
  saveError?: string | null;
};

export function SupervisorForm({
  draft,
  onChange,
  onSubmit,
  onCancel,
  errors,
  showErrors,
  submitLabel,
  pending = false,
  saveError = null,
}: SupervisorFormProps) {
  const id = useId();
  const nameRef = useRef<HTMLInputElement>(null);
  useEffect(() => nameRef.current?.focus(), []);
  const shown = showErrors ? errors : {};
  const field = (name: keyof SupervisorDraft) => ({
    id: `${id}-${name}`,
    "aria-invalid": shown[name] ? true : undefined,
    "aria-describedby": shown[name] ? `${id}-${name}-error` : undefined,
    disabled: pending,
  });

  return (
    <form
      noValidate
      aria-busy={pending || undefined}
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <label htmlFor={`${id}-displayName`} className="flex flex-col gap-1">
        <span className="text-sm font-medium">
          Name <span className="text-destructive" aria-hidden>*</span>
        </span>
        <input
          {...field("displayName")}
          ref={nameRef}
          type="text"
          autoComplete="off"
          maxLength={MAX_DISPLAY_NAME_LENGTH + 20}
          value={draft.displayName}
          onChange={(event) => onChange({ ...draft, displayName: event.target.value })}
          className={fieldClasses}
        />
        <FieldError id={`${id}-displayName-error`} message={shown.displayName} />
      </label>

      <div className="grid gap-2 sm:grid-cols-2">
        <label className={checkClasses}>
          <input
            type="checkbox"
            checked={draft.active}
            onChange={(event) => onChange({ ...draft, active: event.target.checked })}
            disabled={pending}
            className="size-5 accent-primary"
          />
          <span>
            <span className="font-medium">Active</span>
            <span className="block text-xs text-muted-foreground">Shown on the tally board</span>
          </span>
        </label>
        <label className={checkClasses}>
          <input
            type="checkbox"
            checked={draft.participationEligible}
            onChange={(event) => onChange({ ...draft, participationEligible: event.target.checked })}
            disabled={pending}
            className="size-5 accent-primary"
          />
          <span>
            <span className="font-medium">Eligible for participation</span>
            <span className="block text-xs text-muted-foreground">Counted in monthly participation</span>
          </span>
        </label>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <label htmlFor={`${id}-effectiveFrom`} className="flex min-w-0 flex-col gap-1">
          <span className="text-sm font-medium">
            Effective from <span className="text-destructive" aria-hidden>*</span>
          </span>
          <input
            {...field("effectiveFrom")}
            type="date"
            min={EARLIEST_DATE}
            value={draft.effectiveFrom}
            onChange={(event) => onChange({ ...draft, effectiveFrom: event.target.value })}
            className={fieldClasses}
          />
          <FieldError id={`${id}-effectiveFrom-error`} message={shown.effectiveFrom} />
        </label>
        <label htmlFor={`${id}-effectiveTo`} className="flex min-w-0 flex-col gap-1">
          <span className="text-sm font-medium">
            Effective to{" "}
            <span className="font-normal text-muted-foreground">
              {draft.active ? "(optional)" : "(required when inactive)"}
            </span>
          </span>
          <input
            {...field("effectiveTo")}
            type="date"
            min={draft.effectiveFrom || EARLIEST_DATE}
            value={draft.effectiveTo}
            onChange={(event) => onChange({ ...draft, effectiveTo: event.target.value })}
            className={fieldClasses}
          />
          <FieldError id={`${id}-effectiveTo-error`} message={shown.effectiveTo} />
        </label>
      </div>
      <p className="text-xs text-muted-foreground">
        A supervisor counts toward a month&apos;s participation when they are eligible and their effective
        dates overlap the month.
      </p>

      {saveError && (
        <p role="alert" className="text-sm font-medium text-destructive">
          {saveError}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="outline" className={actionClasses} onClick={onCancel} disabled={pending}>
            Cancel
          </Button>
        )}
        <Button type="submit" className={actionClasses} disabled={pending}>
          {pending && <LoaderCircle className="animate-spin" aria-hidden />}
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}

export function effectivePeriod(supervisor: Supervisor): string {
  const from = formatDate(supervisor.effectiveFrom);
  return supervisor.effectiveTo ? `${from} – ${formatDate(supervisor.effectiveTo)}` : `From ${from}`;
}

type SupervisorRowProps = {
  supervisor: Supervisor;
  confirmingDelete?: boolean;
  deleting?: boolean;
  onEdit?: () => void;
  onRequestDelete?: () => void;
  onConfirmDelete?: () => void;
  onCancelDelete?: () => void;
};

/** One supervisor on the program list. Delete is offered only while no contacts reference them. */
export function SupervisorRow({
  supervisor,
  confirmingDelete = false,
  deleting = false,
  onEdit,
  onRequestDelete,
  onConfirmDelete,
  onCancelDelete,
}: SupervisorRowProps) {
  const { deleteRef, cancelRef } = useConfirmFocus(confirmingDelete);
  return (
    <article
      aria-label={supervisor.displayName}
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card p-3 sm:px-4"
    >
      <div className="min-w-0 space-y-1">
        <p className="font-semibold break-words">{supervisor.displayName}</p>
        <div className="flex flex-wrap gap-1.5">
          <StatusBadge>{supervisor.active ? "Active" : "Inactive"}</StatusBadge>
          <StatusBadge>
            {supervisor.participationEligible ? "Eligible for participation" : "Not eligible for participation"}
          </StatusBadge>
        </div>
        <p className="text-xs text-muted-foreground">{effectivePeriod(supervisor)}</p>
      </div>
      {!confirmingDelete && (
        <div className="flex gap-2">
          <Button variant="outline" className={actionClasses} onClick={onEdit}>
            <Pencil aria-hidden />
            Edit
          </Button>
          {!supervisor.hasContacts && (
            <Button ref={deleteRef} variant="outline" className={actionClasses} onClick={onRequestDelete}>
              <Trash2 aria-hidden />
              Delete
            </Button>
          )}
        </div>
      )}
      {confirmingDelete && (
        <DeleteConfirmation
          prompt="Delete this supervisor? Use this only for a supervisor added by mistake."
          deleting={deleting}
          onCancel={onCancelDelete}
          onConfirm={onConfirmDelete}
          cancelRef={cancelRef}
        />
      )}
    </article>
  );
}
