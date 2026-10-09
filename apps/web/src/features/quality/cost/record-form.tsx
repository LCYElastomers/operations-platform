"use client";

import { AlertTriangle } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { siteToday } from "@/features/safety/site-calendar";
import { cn } from "@/lib/utils";

import {
  COST_FIELDS,
  costRecordError,
  describeCostError,
  type CoqClass,
  type CostField,
  type CostRecord,
  type CostRecordFields,
  type CostRecordOptions,
  type FinancialStatus,
  type OperationalStatus,
} from "./api";
import { COQ_CLASS_COLORS, usd } from "./format";
import { useCreateCostRecord, useUpdateCostRecord } from "./use-cost";

/** The form as typed: every value a string; "" is not entered. */
export type CostDraft = {
  recordDate: string;
  title: string;
  areaId: string;
  coqClass: CoqClass | "";
  categoryCode: string;
  description: string;
  product: string;
  campaign: string;
  lot: string;
  location: string;
  process: string;
  equipment: string;
  counterparty: string;
  owner: string;
  notes: string;
  financialStatus: FinancialStatus;
  status: OperationalStatus;
  dueDate: string;
  dateClosed: string;
  resolutionNotes: string;
  recoveredCost: string;
  avoidedCost: string;
  reference: string;
} & Record<CostField, string>;

const OPTIONAL_TEXT = [
  "product",
  "campaign",
  "lot",
  "location",
  "process",
  "equipment",
  "counterparty",
  "owner",
  "notes",
  "resolutionNotes",
] as const;

export const MONEY = /^\d{1,14}(\.\d{1,4})?$/;
export const MONEY_MESSAGE = "Enter an amount such as 1250 or 1250.75 (no negatives).";

export function emptyDraft(today: string, coqClass: CoqClass | "" = ""): CostDraft {
  return {
    recordDate: today,
    title: "",
    areaId: "",
    coqClass,
    categoryCode: "",
    description: "",
    product: "",
    campaign: "",
    lot: "",
    location: "",
    process: "",
    equipment: "",
    counterparty: "",
    owner: "",
    notes: "",
    financialStatus: "potential",
    status: "open",
    dueDate: "",
    dateClosed: "",
    resolutionNotes: "",
    recoveredCost: "",
    avoidedCost: "",
    reference: "",
    ...(Object.fromEntries(COST_FIELDS.map((field) => [field, ""])) as Record<CostField, string>),
  };
}

export function draftOf(record: CostRecord): CostDraft {
  const text = (value: string | null) => value ?? "";
  return {
    recordDate: record.recordDate,
    title: record.title,
    areaId: record.areaId === null ? "" : String(record.areaId),
    coqClass: record.coqClass,
    categoryCode: record.categoryCode,
    description: record.description,
    ...(Object.fromEntries(OPTIONAL_TEXT.map((field) => [field, text(record[field])])) as Record<
      (typeof OPTIONAL_TEXT)[number],
      string
    >),
    financialStatus: record.financialStatus,
    status: record.status,
    dueDate: text(record.dueDate),
    dateClosed: text(record.dateClosed),
    recoveredCost: text(record.recoveredCost),
    avoidedCost: text(record.avoidedCost),
    reference: record.references.find((ref) => ref.type === "reference")?.key ?? "",
    ...(Object.fromEntries(COST_FIELDS.map((field) => [field, text(record[field])])) as Record<CostField, string>),
  };
}

/** The request body. Other reference types on the record are kept as they are. */
export function fieldsOf(draft: CostDraft, record: CostRecord | null = null): CostRecordFields {
  const optional = (value: string) => value.trim() || null;
  const others = (record?.references ?? [])
    .filter((ref) => ref.type !== "reference")
    .map(({ type, key, label }) => ({ type, key, label }));
  return {
    recordDate: draft.recordDate,
    title: draft.title,
    areaId: draft.areaId ? Number(draft.areaId) : null,
    coqClass: draft.coqClass as CoqClass,
    categoryCode: draft.categoryCode,
    description: draft.description,
    ...(Object.fromEntries(OPTIONAL_TEXT.map((field) => [field, optional(draft[field])])) as Record<
      (typeof OPTIONAL_TEXT)[number],
      string | null
    >),
    financialStatus: draft.financialStatus,
    status: draft.status,
    dueDate: draft.dueDate || null,
    dateClosed: draft.status === "closed" ? draft.dateClosed || null : null,
    recoveredCost: optional(draft.recoveredCost),
    avoidedCost: optional(draft.avoidedCost),
    references: [
      ...(draft.reference.trim() ? [{ type: "reference", key: draft.reference.trim(), label: null }] : []),
      ...others,
    ],
    ...(Object.fromEntries(COST_FIELDS.map((field) => [field, optional(draft[field])])) as Record<
      CostField,
      string | null
    >),
  };
}

/**
 * The entered components added up, for display while typing. The saved total
 * is calculated by the API. Amounts are summed in ten-thousandths of a dollar
 * so decimals add exactly; null when nothing valid is entered.
 */
export function previewTotal(values: string[]): number | null {
  const entered = values.map((value) => value.trim()).filter((value) => MONEY.test(value));
  if (entered.length === 0) return null;
  const units = entered.reduce((sum, value) => {
    const [whole, fraction = ""] = value.split(".");
    return sum + Number(whole) * 10_000 + Number(fraction.padEnd(4, "0"));
  }, 0);
  return units / 10_000;
}

type Problems = Partial<Record<string, string>>;

/** Problems the browser can see before asking the API; the API checks everything again. */
export function draftProblems(draft: CostDraft, today: string, requireArea: boolean): Problems {
  const problems: Problems = {};
  if (!draft.recordDate) problems.recordDate = "Enter the date.";
  else if (draft.recordDate > today) problems.recordDate = "The date cannot be in the future.";
  if (!draft.title.trim()) problems.title = "Enter a short title.";
  if (requireArea && !draft.areaId) problems.areaId = "Choose an area.";
  if (!draft.coqClass) problems.coqClass = "Choose a COQ classification.";
  if (!draft.categoryCode) problems.categoryCode = "Choose a category.";
  if (!draft.description.trim()) problems.description = "Describe what happened.";
  for (const field of [...COST_FIELDS, "recoveredCost", "avoidedCost"] as const) {
    const value = draft[field].trim();
    if (value && !MONEY.test(value)) problems[field] = MONEY_MESSAGE;
  }
  if (draft.dueDate && draft.recordDate && draft.dueDate < draft.recordDate)
    problems.dueDate = "The due date cannot be before the date.";
  if (draft.status === "closed") {
    if (!draft.dateClosed) problems.dateClosed = "Enter the date closed.";
    else if (draft.recordDate && draft.dateClosed < draft.recordDate)
      problems.dateClosed = "The date closed cannot be before the date.";
    else if (draft.dateClosed > today) problems.dateClosed = "The date closed cannot be in the future.";
  }
  return problems;
}

export const fieldClasses = cn(
  "w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none",
  "focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 disabled:opacity-60",
  "aria-invalid:border-destructive pointer-coarse:text-base",
);
export const inputClasses = cn(fieldClasses, "h-9 pointer-coarse:h-11");

export function Field({
  id,
  label,
  required,
  hint,
  error,
  className,
  children,
}: {
  id: string;
  label: string;
  required?: boolean;
  hint?: string;
  error?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <label htmlFor={id} className="text-sm font-medium">
        {label}
        {required ? (
          <span className="text-destructive" aria-hidden>
            {" "}
            *
          </span>
        ) : (
          <span className="font-normal text-muted-foreground"> (optional)</span>
        )}
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

function Section({ step, title, description, children }: { step: number; title: string; description?: string; children: React.ReactNode }) {
  return (
    <fieldset className="space-y-3 rounded-lg border p-4">
      <legend className="px-1 text-sm font-semibold">
        <span className="mr-2 inline-grid size-5 place-items-center rounded-full bg-muted text-xs tabular-nums">{step}</span>
        {title}
      </legend>
      {description && <p className="-mt-1 text-xs text-muted-foreground">{description}</p>}
      {children}
    </fieldset>
  );
}

type SaveProblem = { message: string; current: CostRecord | null };

/**
 * The one Quality Cost entry form: used to add an item from the Register, COPQ
 * and the COQ Matrix, and to edit one. Sections follow the order a user thinks
 * it through: what happened, where, which class, what it cost, whether the cost
 * is confirmed, who owns it, and whether it is resolved.
 */
export function CostRecordForm({
  record,
  defaultClass,
  options,
  onCancel,
  onSaved,
  onReload,
}: {
  record: CostRecord | null;
  defaultClass?: CoqClass;
  options: CostRecordOptions;
  onCancel: () => void;
  onSaved: (record: CostRecord, created: boolean) => void;
  onReload: (record: CostRecord) => void;
}) {
  const id = useId();
  const [today] = useState(siteToday);
  const [draft, setDraft] = useState<CostDraft>(() => (record ? draftOf(record) : emptyDraft(today, defaultClass ?? "")));
  const [touched, setTouched] = useState(false);
  const [problem, setProblem] = useState<SaveProblem | null>(null);
  const [serverProblems, setServerProblems] = useState<Problems>({});
  const create = useCreateCostRecord();
  const update = useUpdateCostRecord();
  const saving = create.isPending || update.isPending;

  const requireArea = !(record?.source === "legacy_import" && record.areaId === null);
  const problems = touched ? { ...draftProblems(draft, today, requireArea), ...serverProblems } : serverProblems;
  const set = <K extends keyof CostDraft>(key: K, value: CostDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setServerProblems((current) => {
      if (!(key in current)) return current;
      const rest = { ...current };
      delete rest[key];
      return rest;
    });
  };
  const input = (key: keyof CostDraft) => ({
    id: `${id}-${key}`,
    value: draft[key],
    onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
      set(key, event.target.value as CostDraft[typeof key]),
    "aria-invalid": problems[key] ? true : undefined,
    "aria-describedby": problems[key] ? `${id}-${key}-error` : undefined,
  });

  const classOption = options.classes.find((item) => item.code === draft.coqClass);
  const areas = options.areas.filter((area) => area.active || String(area.id) === draft.areaId);
  const total = previewTotal(COST_FIELDS.map((field) => draft[field]));
  const recovered = previewTotal([draft.recoveredCost]);
  const confirmed = options.financialStatuses.find((s) => s.code === draft.financialStatus)?.confirmed ?? false;

  function chooseClass(code: CoqClass) {
    setDraft((current) => ({
      ...current,
      coqClass: code,
      categoryCode: current.coqClass === code ? current.categoryCode : "",
    }));
    setServerProblems({});
  }

  function chooseStatus(status: OperationalStatus) {
    setDraft((current) => ({
      ...current,
      status,
      // Date closed belongs to a closed record only; closing defaults it to today.
      dateClosed: status === "closed" ? current.dateClosed || today : "",
    }));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setTouched(true);
    setProblem(null);
    if (Object.keys(draftProblems(draft, today, requireArea)).length > 0) return;
    const body = fieldsOf(draft, record);
    try {
      const saved = record
        ? await update.mutateAsync({ id: record.id, body: { ...body, version: record.version } })
        : await create.mutateAsync(body);
      onSaved(saved.record, record === null);
    } catch (error) {
      const known = costRecordError(error);
      if (known?.field) setServerProblems({ [known.field]: known.message });
      setProblem({
        message: known?.message ?? `Nothing was saved. ${describeCostError(error)}`,
        current: known?.current ?? null,
      });
    }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4" aria-label={record ? "Edit quality cost item" : "Add quality cost item"}>
      {record?.source === "legacy_import" && (
        <p className="rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          Imported from the COQ workbook as a monthly total. The cost lines and date are re-checked by the import; add the
          area, product, owner and actions here.
        </p>
      )}

      <Section step={1} title="What happened">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-[10rem_1fr]">
          <Field id={`${id}-recordDate`} label="Date" required error={problems.recordDate}>
            <input type="date" max={today} required className={inputClasses} {...input("recordDate")} />
          </Field>
          <Field id={`${id}-title`} label="Title / short description" required error={problems.title}>
            <input maxLength={200} required autoComplete="off" className={inputClasses} {...input("title")} />
          </Field>
        </div>
        <Field id={`${id}-description`} label="Description" required error={problems.description}>
          <textarea rows={3} maxLength={4000} required className={cn(fieldClasses, "py-2")} {...input("description")} />
        </Field>
      </Section>

      <Section step={2} title="Where" description="Product, campaign, lot and location use the production identifiers.">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field id={`${id}-areaId`} label="Area / department" required={requireArea} error={problems.areaId}>
            <select className={inputClasses} {...input("areaId")}>
              <option value="">{requireArea ? "Choose an area" : "Not recorded"}</option>
              {areas.map((area) => (
                <option key={area.id} value={area.id}>
                  {area.name}
                  {area.active ? "" : " (inactive)"}
                </option>
              ))}
            </select>
          </Field>
          <Field id={`${id}-product`} label="Product" error={problems.product}>
            <input maxLength={200} list={`${id}-products`} autoComplete="off" className={inputClasses} {...input("product")} />
            <datalist id={`${id}-products`}>
              {options.products.map((value) => (
                <option key={value} value={value} />
              ))}
            </datalist>
          </Field>
          <Field id={`${id}-lot`} label="Lot / batch" error={problems.lot}>
            <input maxLength={200} autoComplete="off" className={inputClasses} {...input("lot")} />
          </Field>
        </div>
        <details className="group" open={Boolean(draft.campaign || draft.location || draft.process || draft.equipment || draft.counterparty)}>
          <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground">
            Campaign, location, process, equipment, customer / supplier
          </summary>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            {(
              [
                ["campaign", "Campaign"],
                ["location", "Location"],
                ["process", "Process"],
                ["equipment", "Equipment"],
                ["counterparty", "Customer / supplier"],
              ] as const
            ).map(([key, label]) => (
              <Field key={key} id={`${id}-${key}`} label={label} error={problems[key]}>
                <input maxLength={200} autoComplete="off" className={inputClasses} {...input(key)} />
              </Field>
            ))}
          </div>
        </details>
      </Section>

      <Section step={3} title="COQ classification" description="Prevention and appraisal are good quality cost; internal and external failure are poor quality cost (COPQ).">
        <div role="radiogroup" aria-label="COQ classification" aria-describedby={problems.coqClass ? `${id}-coqClass-error` : undefined} className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          {options.classes.map((item) => {
            const selected = draft.coqClass === item.code;
            const color = COQ_CLASS_COLORS[item.code];
            return (
              <button
                key={item.code}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => chooseClass(item.code)}
                className={cn(
                  "flex min-h-16 flex-col items-start rounded-lg border-2 px-3 py-2 text-left transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none",
                  selected ? "shadow-sm" : "border-border hover:bg-muted/50",
                )}
                style={selected ? { borderColor: color, backgroundColor: `${color}12` } : undefined}
              >
                <span className="text-sm font-semibold" style={{ color: selected ? color : undefined }}>
                  {item.label}
                </span>
                <span className="text-xs text-muted-foreground">
                  {item.qualityGroup === "good" ? "Good COQ" : "Poor COQ · COPQ"}
                </span>
              </button>
            );
          })}
        </div>
        {problems.coqClass && (
          <p id={`${id}-coqClass-error`} className="text-xs text-destructive">
            {problems.coqClass}
          </p>
        )}
        <Field id={`${id}-categoryCode`} label="Category" required error={problems.categoryCode} hint={classOption ? undefined : "Choose a classification first."}>
          <select disabled={!classOption} className={inputClasses} {...input("categoryCode")}>
            <option value="">Choose a category</option>
            {classOption?.categories.map((category) => (
              <option key={category.code} value={category.code}>
                {category.label}
              </option>
            ))}
          </select>
        </Field>
      </Section>

      <Section step={4} title="Cost breakdown" description="US dollars. Leave a component blank when it does not apply or is not known yet; 0 means no cost.">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {options.costComponents.map((component) => (
            <Field key={component.field} id={`${id}-${component.field}`} label={component.label} error={problems[component.field]}>
              <input inputMode="decimal" autoComplete="off" placeholder="—" className={cn(inputClasses, "text-right tabular-nums")} {...input(component.field)} />
            </Field>
          ))}
        </div>
        <p className="flex items-baseline justify-between rounded-md bg-muted/50 px-3 py-2 text-sm" aria-live="polite">
          <span className="font-medium">Estimated total cost</span>
          <span className="font-semibold tabular-nums">{total === null ? "No cost entered" : usd(String(total), 2)}</span>
        </p>
      </Section>

      <Section step={5} title="Financial status" description="Is the cost confirmed? Potential and Validating costs are reported as potential exposure, never as confirmed cost.">
        <div role="radiogroup" aria-label="Financial status" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {options.financialStatuses.map((item) => (
            <button
              key={item.code}
              type="button"
              role="radio"
              aria-checked={draft.financialStatus === item.code}
              onClick={() => set("financialStatus", item.code)}
              className={cn(
                "h-10 rounded-md border px-3 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none pointer-coarse:h-11",
                draft.financialStatus === item.code ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          {confirmed ? "Counted in confirmed cost." : "Counted as potential exposure until confirmed."}
        </p>
      </Section>

      <Section step={6} title="Ownership and status">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field id={`${id}-status`} label="Status" required>
            <select
              id={`${id}-status`}
              value={draft.status}
              onChange={(event) => chooseStatus(event.target.value as OperationalStatus)}
              className={inputClasses}
            >
              {options.operationalStatuses.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.label}
                </option>
              ))}
            </select>
          </Field>
          <Field id={`${id}-owner`} label="Owner" error={problems.owner}>
            <input maxLength={200} list={`${id}-owners`} autoComplete="off" className={inputClasses} {...input("owner")} />
            <datalist id={`${id}-owners`}>
              {options.owners.map((value) => (
                <option key={value} value={value} />
              ))}
            </datalist>
          </Field>
          <Field id={`${id}-dueDate`} label="Due date" error={problems.dueDate}>
            <input type="date" className={inputClasses} {...input("dueDate")} />
          </Field>
          {draft.status === "closed" && (
            <Field id={`${id}-dateClosed`} label="Date closed" required error={problems.dateClosed}>
              <input type="date" max={today} className={inputClasses} {...input("dateClosed")} />
            </Field>
          )}
        </div>
        <Field id={`${id}-resolutionNotes`} label="Action / resolution notes" error={problems.resolutionNotes}>
          <textarea rows={2} maxLength={4000} className={cn(fieldClasses, "py-2")} {...input("resolutionNotes")} />
        </Field>
      </Section>

      <Section step={7} title="Recovery and avoidance" description="Recovered cost reduces the net quality cost. Avoided cost is reported on its own and never subtracted.">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field id={`${id}-recoveredCost`} label="Recovered cost" error={problems.recoveredCost}>
            <input inputMode="decimal" autoComplete="off" placeholder="—" className={cn(inputClasses, "text-right tabular-nums")} {...input("recoveredCost")} />
          </Field>
          <Field id={`${id}-avoidedCost`} label="Avoided cost" error={problems.avoidedCost}>
            <input inputMode="decimal" autoComplete="off" placeholder="—" className={cn(inputClasses, "text-right tabular-nums")} {...input("avoidedCost")} />
          </Field>
          <div className="flex flex-col gap-1">
            <span className="text-sm font-medium">Net quality cost</span>
            <p className="flex h-9 items-center justify-end rounded-md bg-muted/50 px-3 text-sm font-semibold tabular-nums">
              {total === null ? "—" : usd(String(total - (recovered ?? 0)), 2)}
            </p>
          </div>
        </div>
      </Section>

      <Section step={8} title="Related records and notes">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-[16rem_1fr]">
          <Field id={`${id}-reference`} label="Related record / reference" hint="A complaint, NCR or document number." error={problems.references}>
            <input maxLength={200} autoComplete="off" className={inputClasses} {...input("reference")} />
          </Field>
          <Field id={`${id}-notes`} label="Notes" error={problems.notes}>
            <textarea rows={2} maxLength={4000} className={cn(fieldClasses, "py-2")} {...input("notes")} />
          </Field>
        </div>
      </Section>

      {problem && (
        <div role="alert" className="flex flex-col gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive sm:flex-row sm:items-center">
          <p className="flex flex-1 items-start gap-2">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            {problem.message}
          </p>
          {problem.current && (
            <Button variant="outline" size="sm" type="button" onClick={() => onReload(problem.current!)} className="pointer-coarse:h-11">
              Load the latest version
            </Button>
          )}
        </div>
      )}
      {touched && !problem && Object.keys(problems).length > 0 && (
        <p role="alert" className="text-sm text-destructive">
          Check the highlighted fields. Nothing was saved.
        </p>
      )}

      <div className="sticky bottom-0 -mx-4 flex flex-col-reverse gap-2 border-t bg-background px-4 pt-3 pb-1 sm:-mx-5 sm:flex-row sm:justify-end sm:px-5">
        <Button variant="outline" type="button" onClick={onCancel} disabled={saving} className="pointer-coarse:h-11">
          Cancel
        </Button>
        <Button type="submit" disabled={saving} className="pointer-coarse:h-11">
          {saving ? "Saving…" : record ? "Save changes" : "Add quality cost item"}
        </Button>
      </div>
    </form>
  );
}
