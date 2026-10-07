"use client";

import { Check, LoaderCircle } from "lucide-react";
import { useId } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { Kind, ObservationCategory, Outcome } from "./api";
import {
  EARLIEST_OBSERVED_ON,
  KIND_LABELS,
  MAX_AREA_LOCATION_LENGTH,
  MAX_NOTE_LENGTH,
  OUTCOME_LABELS,
  type DraftErrors,
  type ObservationDraft,
} from "./observation-data";

const fieldClasses = cn(
  "w-full rounded-md border border-input bg-background px-3 text-base shadow-xs sm:text-sm",
  "outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40",
  "aria-invalid:border-destructive disabled:cursor-not-allowed disabled:opacity-60",
);

// Native radios keep keyboard and screen reader behaviour; the tile is the touch target.
const tileClasses = cn(
  "flex min-h-12 cursor-pointer items-center justify-center gap-2 rounded-md border bg-card px-3 py-2 text-center text-sm font-medium",
  "transition-colors select-none active:bg-muted",
  "has-checked:border-primary has-checked:bg-primary/10 has-checked:text-primary has-checked:font-semibold",
  "has-focus-visible:ring-2 has-focus-visible:ring-ring/50",
  "has-disabled:cursor-not-allowed has-disabled:opacity-60",
);

function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} className="text-xs font-medium text-destructive">
      {message}
    </p>
  );
}

type ChoiceOption<T extends string | number> = { value: T; label: string };

type ChoiceGroupProps<T extends string | number> = {
  legend: string;
  name: string;
  options: ChoiceOption<T>[];
  value: T | null;
  onChange: (value: T) => void;
  error?: string;
  disabled?: boolean;
  /** Grid classes for the tiles. */
  columns?: string;
};

/** A single required choice shown as large tiles. */
export function ChoiceGroup<T extends string | number>({
  legend,
  name,
  options,
  value,
  onChange,
  error,
  disabled,
  columns = "grid-cols-2",
}: ChoiceGroupProps<T>) {
  const errorId = `${name}-error`;
  return (
    <fieldset
      className="@container min-w-0 space-y-2"
      aria-invalid={error ? true : undefined}
      aria-describedby={error ? errorId : undefined}
    >
      <legend className="mb-2 text-sm font-medium">
        {legend} <span className="text-destructive" aria-hidden>*</span>
      </legend>
      <div className={cn("grid gap-2", columns)}>
        {options.map((option) => {
          const checked = option.value === value;
          return (
            <label key={option.value} className={tileClasses}>
              <input
                type="radio"
                name={name}
                value={String(option.value)}
                checked={checked}
                onChange={() => onChange(option.value)}
                disabled={disabled}
                required
                className="sr-only"
              />
              {checked && <Check aria-hidden className="size-4 shrink-0" />}
              <span className="min-w-0 leading-tight">{option.label}</span>
            </label>
          );
        })}
      </div>
      <FieldError id={errorId} message={error} />
    </fieldset>
  );
}

const OUTCOME_OPTIONS: ChoiceOption<Outcome>[] = [
  { value: "safe", label: OUTCOME_LABELS.safe },
  { value: "unsafe", label: OUTCOME_LABELS.unsafe },
];
const KIND_OPTIONS: ChoiceOption<Kind>[] = [
  { value: "act", label: KIND_LABELS.act },
  { value: "condition", label: KIND_LABELS.condition },
];

type ObservationFormProps = {
  draft: ObservationDraft;
  onChange: (draft: ObservationDraft) => void;
  onSubmit: () => void;
  onCancel?: () => void;
  categories: ObservationCategory[];
  /** Validation messages; shown only after a save was attempted. */
  errors: DraftErrors;
  showErrors: boolean;
  /** YYYY-MM-DD; later dates are refused. */
  today: string;
  submitLabel: string;
  pending?: boolean;
  /** A failed save, explained in plain language. */
  saveError?: string | null;
};

export function ObservationForm({
  draft,
  onChange,
  onSubmit,
  onCancel,
  categories,
  errors,
  showErrors,
  today,
  submitLabel,
  pending = false,
  saveError,
}: ObservationFormProps) {
  const id = useId();
  const shown = showErrors ? errors : {};
  const set = <K extends keyof ObservationDraft>(key: K, value: ObservationDraft[K]) =>
    onChange({ ...draft, [key]: value });

  return (
    <form
      noValidate
      aria-busy={pending || undefined}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      className="space-y-5"
    >
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${id}-date`} className="text-sm font-medium">
          Date <span className="text-destructive" aria-hidden>*</span>
        </label>
        <input
          id={`${id}-date`}
          type="date"
          required
          min={EARLIEST_OBSERVED_ON}
          max={today}
          value={draft.observedOn}
          onChange={(event) => set("observedOn", event.target.value)}
          disabled={pending}
          aria-invalid={shown.observedOn ? true : undefined}
          aria-describedby={shown.observedOn ? `${id}-date-error` : undefined}
          className={cn(fieldClasses, "h-12 sm:w-56")}
        />
        <FieldError id={`${id}-date-error`} message={shown.observedOn} />
      </div>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        <ChoiceGroup
          legend="Safe or Unsafe"
          name={`${id}-outcome`}
          options={OUTCOME_OPTIONS}
          value={draft.outcome}
          onChange={(value) => set("outcome", value)}
          error={shown.outcome}
          disabled={pending}
        />
        <ChoiceGroup
          legend="Act or Condition"
          name={`${id}-kind`}
          options={KIND_OPTIONS}
          value={draft.kind}
          onChange={(value) => set("kind", value)}
          error={shown.kind}
          disabled={pending}
        />
      </div>

      <ChoiceGroup
        legend="Category"
        name={`${id}-category`}
        options={categories.map((category) => ({ value: category.id, label: category.name }))}
        value={draft.categoryId}
        onChange={(value) => set("categoryId", value)}
        error={shown.categoryId}
        disabled={pending}
        columns="grid-cols-2 @sm:grid-cols-3 @2xl:grid-cols-4"
      />

      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${id}-area`} className="text-sm font-medium">
          Area / Location <span className="font-normal text-muted-foreground">(optional)</span>
        </label>
        <input
          id={`${id}-area`}
          type="text"
          maxLength={MAX_AREA_LOCATION_LENGTH}
          value={draft.areaLocation}
          onChange={(event) => set("areaLocation", event.target.value)}
          disabled={pending}
          autoComplete="off"
          aria-invalid={shown.areaLocation ? true : undefined}
          className={cn(fieldClasses, "h-12")}
        />
        <FieldError id={`${id}-area-error`} message={shown.areaLocation} />
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${id}-description`} className="text-sm font-medium">
          Description <span className="font-normal text-muted-foreground">(optional)</span>
        </label>
        <textarea
          id={`${id}-description`}
          rows={3}
          maxLength={MAX_NOTE_LENGTH}
          value={draft.description}
          onChange={(event) => set("description", event.target.value)}
          disabled={pending}
          aria-invalid={shown.description ? true : undefined}
          className={cn(fieldClasses, "py-2.5")}
        />
        <FieldError id={`${id}-description-error`} message={shown.description} />
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${id}-corrective`} className="text-sm font-medium">
          Corrective Action <span className="font-normal text-muted-foreground">(optional)</span>
        </label>
        <textarea
          id={`${id}-corrective`}
          rows={2}
          maxLength={MAX_NOTE_LENGTH}
          value={draft.correctiveAction}
          onChange={(event) => set("correctiveAction", event.target.value)}
          disabled={pending}
          aria-invalid={shown.correctiveAction ? true : undefined}
          className={cn(fieldClasses, "py-2.5")}
        />
        <FieldError id={`${id}-corrective-error`} message={shown.correctiveAction} />
      </div>

      {saveError && (
        <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {saveError}
        </p>
      )}
      {showErrors && Object.keys(errors).length > 0 && (
        <p role="alert" className="text-sm font-medium text-destructive">
          Complete the highlighted fields to save.
        </p>
      )}

      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        {onCancel && (
          <Button
            variant="outline"
            onClick={onCancel}
            disabled={pending}
            className="h-12 px-6 text-base sm:text-sm"
          >
            Cancel
          </Button>
        )}
        <Button type="submit" disabled={pending} className="h-12 px-6 text-base sm:text-sm">
          {pending && <LoaderCircle className="animate-spin" aria-hidden />}
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
