"use client";

import { ChevronDown, LoaderCircle, Pencil, Trash2 } from "lucide-react";
import { useEffect, useId, useRef } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { Contact, Supervisor } from "./api";
import { EARLIEST_DATE, formatDate } from "./contact-data";

export const actionClasses = "h-11 min-w-24 px-4";

export const fieldClasses = cn(
  "h-11 w-full rounded-md border border-input bg-background px-3 text-base shadow-xs sm:text-sm",
  "outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40",
  "aria-invalid:border-destructive disabled:cursor-not-allowed disabled:opacity-60",
);

type DeleteConfirmationProps = {
  prompt: string;
  deleting: boolean;
  onCancel?: () => void;
  onConfirm?: () => void;
  cancelRef: React.Ref<HTMLButtonElement>;
};

export function DeleteConfirmation({ prompt, deleting, onCancel, onConfirm, cancelRef }: DeleteConfirmationProps) {
  const promptId = useId();
  return (
    <div
      role="alertdialog"
      aria-label="Confirm delete"
      aria-describedby={promptId}
      onKeyDown={(event) => {
        if (event.key === "Escape" && !deleting) {
          event.stopPropagation();
          onCancel?.();
        }
      }}
      className="flex w-full flex-col gap-3 rounded-md border border-destructive/30 bg-destructive/5 p-3 sm:flex-row sm:items-center sm:justify-between"
    >
      <p id={promptId} className="text-sm">
        {prompt}
      </p>
      <div className="flex gap-2">
        <Button ref={cancelRef} variant="outline" className={actionClasses} onClick={onCancel} disabled={deleting}>
          Cancel
        </Button>
        <Button
          className={cn(actionClasses, "bg-destructive text-white hover:bg-destructive/90")}
          onClick={onConfirm}
          disabled={deleting}
        >
          {deleting && <LoaderCircle className="animate-spin" aria-hidden />}
          Delete
        </Button>
      </div>
    </div>
  );
}

/** Focuses Cancel when a confirmation opens and returns focus to Delete when it is cancelled. */
export function useConfirmFocus(confirming: boolean) {
  const deleteRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const wasConfirming = useRef(confirming);
  useEffect(() => {
    if (confirming && !wasConfirming.current) cancelRef.current?.focus();
    if (!confirming && wasConfirming.current) deleteRef.current?.focus();
    wasConfirming.current = confirming;
  }, [confirming]);
  return { deleteRef, cancelRef };
}

type ContactRowProps = {
  contact: Contact;
  canEdit: boolean;
  /** Just added on this device. */
  highlighted?: boolean;
  confirmingDelete?: boolean;
  deleting?: boolean;
  onEdit?: () => void;
  onRequestDelete?: () => void;
  onConfirmDelete?: () => void;
  onCancelDelete?: () => void;
};

export function ContactRow({
  contact,
  canEdit,
  highlighted = false,
  confirmingDelete = false,
  deleting = false,
  onEdit,
  onRequestDelete,
  onConfirmDelete,
  onCancelDelete,
}: ContactRowProps) {
  const date = formatDate(contact.contactDate);
  const { deleteRef, cancelRef } = useConfirmFocus(confirmingDelete);

  return (
    <article
      aria-label={`${contact.supervisorName}, ${date}`}
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card p-3 sm:px-4",
        highlighted && "border-primary/50 ring-2 ring-primary/20",
      )}
    >
      <div className="min-w-0">
        <p className="flex flex-wrap items-baseline gap-x-2 font-semibold break-words">
          {contact.supervisorName}
          {highlighted && <span className="text-xs font-medium text-primary">Just added</span>}
        </p>
        <p className="text-xs text-muted-foreground">
          <time dateTime={contact.contactDate}>{date}</time>
        </p>
      </div>
      {canEdit && !confirmingDelete && (
        <div className="flex gap-2">
          <Button variant="outline" className={actionClasses} onClick={onEdit}>
            <Pencil aria-hidden />
            Edit
          </Button>
          <Button ref={deleteRef} variant="outline" className={actionClasses} onClick={onRequestDelete}>
            <Trash2 aria-hidden />
            Delete
          </Button>
        </div>
      )}
      {canEdit && confirmingDelete && (
        <DeleteConfirmation
          prompt="Delete this contact? This cannot be undone."
          deleting={deleting}
          onCancel={onCancelDelete}
          onConfirm={onConfirmDelete}
          cancelRef={cancelRef}
        />
      )}
    </article>
  );
}

export type ContactEdit = { contactDate: string; supervisorId: number };

type ContactEditorProps = {
  value: ContactEdit;
  onChange: (value: ContactEdit) => void;
  onSubmit: () => void;
  onCancel: () => void;
  supervisors: Supervisor[];
  today: string;
  dateError: string | null;
  pending?: boolean;
  saveError?: string | null;
};

/** Change a contact's date or supervisor. */
export function ContactEditor({
  value,
  onChange,
  onSubmit,
  onCancel,
  supervisors,
  today,
  dateError,
  pending = false,
  saveError = null,
}: ContactEditorProps) {
  const id = useId();
  const dateRef = useRef<HTMLInputElement>(null);
  useEffect(() => dateRef.current?.focus(), []);
  return (
    <form
      aria-label="Edit contact"
      className="space-y-3 rounded-lg border border-primary/50 bg-card p-3 ring-2 ring-primary/20 sm:p-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      aria-busy={pending || undefined}
    >
      <h3 className="text-sm font-semibold">Edit contact</h3>
      <div className="grid gap-3 sm:grid-cols-2">
        <label htmlFor={`${id}-date`} className="flex min-w-0 flex-col gap-1">
          <span className="text-sm font-medium">Contact date</span>
          <input
            id={`${id}-date`}
            ref={dateRef}
            type="date"
            required
            min={EARLIEST_DATE}
            max={today}
            value={value.contactDate}
            onChange={(event) => onChange({ ...value, contactDate: event.target.value })}
            aria-invalid={dateError ? true : undefined}
            aria-describedby={dateError ? `${id}-date-error` : undefined}
            disabled={pending}
            className={fieldClasses}
          />
          {dateError && (
            <span id={`${id}-date-error`} className="text-xs font-medium text-destructive">
              {dateError}
            </span>
          )}
        </label>
        <label htmlFor={`${id}-supervisor`} className="flex min-w-0 flex-col gap-1">
          <span className="text-sm font-medium">Supervisor</span>
          <span className="relative">
            <select
              id={`${id}-supervisor`}
              value={String(value.supervisorId)}
              onChange={(event) => onChange({ ...value, supervisorId: Number(event.target.value) })}
              disabled={pending}
              className={cn(fieldClasses, "appearance-none pr-9")}
            >
              {supervisors.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.active ? s.displayName : `${s.displayName} (inactive)`}
                </option>
              ))}
            </select>
            <ChevronDown
              aria-hidden
              className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground"
            />
          </span>
        </label>
      </div>
      {saveError && (
        <p role="alert" className="text-sm font-medium text-destructive">
          {saveError}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="outline" className={actionClasses} onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
        <Button type="submit" className={actionClasses} disabled={pending || dateError !== null}>
          {pending && <LoaderCircle className="animate-spin" aria-hidden />}
          Save Changes
        </Button>
      </div>
    </form>
  );
}
