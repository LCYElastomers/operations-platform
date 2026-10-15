"use client";

import { useDirectory } from "@/features/admin/use-admin";
import { Field, fieldClasses, inputClasses } from "@/features/quality/cost/record-form";
import { cn } from "@/lib/utils";

import type { Action, Assignment, Option } from "./api";

/** The form state of an assignment: strings, so "not chosen" stays distinct from a value. */
export type AssignmentDraft = {
  departmentId: string;
  ownerKind: "none" | "user" | "external";
  ownerUserId: string;
  ownerName: string;
  ownerEmail: string;
  dueDate: string;
  task: string;
};

export const EMPTY_ASSIGNMENT: AssignmentDraft = {
  departmentId: "",
  ownerKind: "none",
  ownerUserId: "",
  ownerName: "",
  ownerEmail: "",
  dueDate: "",
  task: "",
};

export function assignmentOf(action: Action): AssignmentDraft {
  return {
    departmentId: action.departmentId ? String(action.departmentId) : "",
    ownerKind: action.ownerUserId ? "user" : action.ownerName ? "external" : "none",
    ownerUserId: action.ownerUserId ?? "",
    ownerName: action.ownerUserId ? "" : (action.ownerName ?? ""),
    ownerEmail: action.ownerUserId ? "" : (action.ownerEmail ?? ""),
    dueDate: action.dueDate ?? "",
    task: action.description ?? "",
  };
}

/** The request fields; blanks are sent as null (not chosen), never as empty values. */
export function assignmentBody(draft: AssignmentDraft): Assignment {
  return {
    departmentId: draft.departmentId ? Number(draft.departmentId) : null,
    ownerUserId: draft.ownerKind === "user" && draft.ownerUserId ? draft.ownerUserId : null,
    ownerName: draft.ownerKind === "external" ? draft.ownerName.trim() || null : null,
    ownerEmail: draft.ownerKind === "external" ? draft.ownerEmail.trim() || null : null,
    dueDate: draft.dueDate || null,
    task: draft.task.trim() || null,
  };
}

export function assignmentProblem(draft: AssignmentDraft): string | null {
  if (draft.ownerKind === "user" && !draft.ownerUserId) return "Choose the user who owns the action.";
  if (draft.ownerKind === "external" && !draft.ownerName.trim()) return "Enter the owner's name.";
  if (draft.ownerKind === "external" && draft.ownerEmail.trim() && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(draft.ownerEmail.trim()))
    return "Enter a valid email address, or leave it blank.";
  return null;
}

export function AssignmentFields({
  id,
  draft,
  departments,
  onChange,
}: {
  id: string;
  draft: AssignmentDraft;
  departments: Option[];
  onChange: (draft: AssignmentDraft) => void;
}) {
  const directory = useDirectory(false);
  const set = (patch: Partial<AssignmentDraft>) => onChange({ ...draft, ...patch });
  const active = departments.filter((d) => d.active || String(d.id) === draft.departmentId);
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <Field id={`${id}-department`} label="Department">
        <select id={`${id}-department`} value={draft.departmentId} onChange={(e) => set({ departmentId: e.target.value })} className={inputClasses}>
          <option value="">Not assigned</option>
          {active.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </Field>
      <Field id={`${id}-due`} label="Due date">
        <input id={`${id}-due`} type="date" value={draft.dueDate} onChange={(e) => set({ dueDate: e.target.value })} className={inputClasses} />
      </Field>
      <fieldset className="flex flex-col gap-2 sm:col-span-2">
        <legend className="text-sm font-medium">
          Owner <span className="font-normal text-muted-foreground">(optional)</span>
        </legend>
        <div className="flex flex-wrap gap-4 text-sm">
          {(
            [
              ["none", "Not assigned"],
              ["user", "Platform user"],
              ["external", "Person without an account"],
            ] as const
          ).map(([kind, label]) => (
            <label key={kind} className="flex items-center gap-2">
              <input type="radio" name={`${id}-owner-kind`} checked={draft.ownerKind === kind} onChange={() => set({ ownerKind: kind })} />
              {label}
            </label>
          ))}
        </div>
        {draft.ownerKind === "user" && (
          <select
            aria-label="Owner"
            value={draft.ownerUserId}
            onChange={(e) => set({ ownerUserId: e.target.value })}
            className={inputClasses}
          >
            <option value="">Choose a user</option>
            {(directory.data ?? []).map((user) => (
              <option key={user.id} value={user.id}>
                {user.name}
              </option>
            ))}
          </select>
        )}
        {draft.ownerKind === "external" && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <input
              aria-label="Owner name"
              placeholder="Name"
              value={draft.ownerName}
              maxLength={200}
              onChange={(e) => set({ ownerName: e.target.value })}
              className={inputClasses}
            />
            <input
              aria-label="Owner email"
              type="email"
              placeholder="Email (for notifications)"
              value={draft.ownerEmail}
              maxLength={254}
              onChange={(e) => set({ ownerEmail: e.target.value })}
              className={inputClasses}
            />
          </div>
        )}
      </fieldset>
      <Field id={`${id}-task`} label="Task" hint="What the owner is to do, if more specific than the recommendation." className="sm:col-span-2">
        <textarea
          id={`${id}-task`}
          rows={3}
          value={draft.task}
          maxLength={8000}
          onChange={(e) => set({ task: e.target.value })}
          className={cn(fieldClasses, "py-2")}
        />
      </Field>
    </div>
  );
}
