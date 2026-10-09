"use client";

import { createContext, useContext } from "react";

import { PersonSelect } from "@/features/users/person-select";
import { cn } from "@/lib/utils";

import { Field, fieldClasses, inputClasses } from "../cost/record-form";

import { PERSON_FIELDS, type CarDraft, type PersonField, type Problems, type TextField, type YesNo, type YesNoField } from "./car-draft";

type DraftContextValue = {
  id: string;
  draft: CarDraft;
  /** The draft of the saved CAR (or an empty one), e.g. to keep recorded names selectable. */
  baseline: CarDraft;
  update: (patch: Partial<CarDraft>) => void;
  problems: Problems;
  readOnly: boolean;
};

export const DraftContext = createContext<DraftContextValue | null>(null);

export function useDraft() {
  const value = useContext(DraftContext);
  if (!value) throw new Error("CAR fields must be inside a DraftContext");
  return value;
}

/** The API's length limits, so typing stops where it would refuse the save. */
const SHORT = 200;
const LONG = 8000;

type TextProps = {
  name: TextField | "subject" | "requestDate";
  label: string;
  required?: boolean;
  hint?: string;
  type?: "text" | "date" | "time";
  /** Suggestions, e.g. names already used on CARs. */
  suggestions?: string[];
  className?: string;
};

export function TextInput({ name, label, required, hint, type = "text", suggestions, className }: TextProps) {
  const { id, draft, update, problems } = useDraft();
  const fieldId = `${id}-${name}`;
  const error = problems[name];
  return (
    <Field id={fieldId} label={label} required={required} hint={hint} error={error} className={className}>
      <input
        id={fieldId}
        type={type}
        value={draft[name]}
        maxLength={type === "text" ? SHORT : undefined}
        list={suggestions?.length ? `${fieldId}-list` : undefined}
        onChange={(event) => update({ [name]: event.target.value })}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined}
        className={inputClasses}
      />
      {suggestions && suggestions.length > 0 && (
        <datalist id={`${fieldId}-list`}>
          {suggestions.map((value) => (
            <option key={value} value={value} />
          ))}
        </datalist>
      )}
    </Field>
  );
}

/** A person on the CAR, chosen from platform users. */
export function PersonInput({ name, label, hint }: { name: PersonField; label: string; hint?: string }) {
  const { id, draft, baseline, update, problems } = useDraft();
  const fieldId = `${id}-${name}`;
  const error = problems[name] ?? problems[PERSON_FIELDS[name]];
  return (
    <Field id={fieldId} label={label} hint={hint} error={error}>
      <PersonSelect
        id={fieldId}
        value={draft.people[name]}
        recorded={baseline.people[name]}
        onChange={(person) => update({ people: { ...draft.people, [name]: person } })}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined}
        className={inputClasses}
      />
    </Field>
  );
}

export function TextArea({
  name,
  label,
  hint,
  rows = 3,
  className,
}: {
  name: TextField;
  label: string;
  hint?: string;
  rows?: number;
  className?: string;
}) {
  const { id, draft, update, problems } = useDraft();
  const fieldId = `${id}-${name}`;
  const error = problems[name];
  return (
    <Field id={fieldId} label={label} hint={hint} error={error} className={cn("sm:col-span-2", className)}>
      <textarea
        id={fieldId}
        rows={rows}
        value={draft[name]}
        maxLength={LONG}
        onChange={(event) => update({ [name]: event.target.value })}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined}
        className={cn(fieldClasses, "py-2")}
      />
    </Field>
  );
}

export function SelectInput({
  name,
  label,
  options,
  required,
  placeholder = "Not recorded",
  hint,
}: {
  name: TextField | YesNoField | "effectivenessResult" | "status";
  label: string;
  options: { value: string; label: string }[];
  required?: boolean;
  placeholder?: string | false;
  hint?: string;
}) {
  const { id, draft, update, problems } = useDraft();
  const fieldId = `${id}-${name}`;
  const error = problems[name];
  return (
    <Field id={fieldId} label={label} required={required} hint={hint} error={error}>
      <select
        id={fieldId}
        value={draft[name]}
        onChange={(event) => update({ [name]: event.target.value })}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined}
        className={inputClasses}
      >
        {placeholder !== false && <option value="">{placeholder}</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </Field>
  );
}

const YES_NO_OPTIONS: { value: YesNo; label: string }[] = [
  { value: "yes", label: "Yes" },
  { value: "no", label: "No" },
];

/** Yes / No with "Not recorded" kept distinct from No. */
export function YesNoInput({ name, label, hint }: { name: YesNoField; label: string; hint?: string }) {
  return <SelectInput name={name} label={label} options={YES_NO_OPTIONS} hint={hint} />;
}

export function FieldGrid({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3", className)}>{children}</div>;
}

export function StepSection({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4 rounded-lg border bg-card p-4 sm:p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold">{title}</h2>
          {description && <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>}
        </div>
        {actions}
      </header>
      {children}
    </section>
  );
}

export function SubHeading({ children }: { children: React.ReactNode }) {
  return <h3 className="border-t pt-4 text-sm font-semibold">{children}</h3>;
}
