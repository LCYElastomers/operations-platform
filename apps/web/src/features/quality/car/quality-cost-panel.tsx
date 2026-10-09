"use client";

import { Link2, Plus, Unlink } from "lucide-react";
import { useDeferredValue, useId, useState } from "react";

import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";

import { NO_DIMENSIONS, type CoqClass, type CostRecordQuery, type FinancialStatus } from "../cost/api";
import { categoryChoices, classChoices } from "../cost/cost-shared";
import { formatDate, usd } from "../cost/format";
import { CostRecordDialog, type CostDialogTarget } from "../cost/record-dialog";
import { Field, inputClasses } from "../cost/record-form";
import { useCostRecordOptions, useCostRecords } from "../cost/use-cost";

import { carSaveError, describeCarError, type Car } from "./api";
import { useCreateQualityCost, useLinkQualityCost } from "./use-car";

/**
 * The CAR's link to a Quality Cost record. A new record is created through the
 * Quality Cost record rules from the CAR's cost lines; its totals are
 * calculated there, not here.
 */
export function QualityCostPanel({
  car,
  canEdit,
  canEditCost,
  dirty,
}: {
  car: Car | null;
  canEdit: boolean;
  canEditCost: boolean;
  /** Unsaved CAR edits: saved first, so the link change cannot conflict with them. */
  dirty: boolean;
}) {
  const [dialog, setDialog] = useState<"create" | "link" | null>(null);
  const [view, setView] = useState<CostDialogTarget | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const link = useLinkQualityCost();

  if (car === null) {
    return (
      <p className="rounded-md border border-dashed px-4 py-3 text-sm text-muted-foreground">
        Save the CAR first to create or link a Quality Cost record.
      </p>
    );
  }
  const linked = car.qualityCost;
  const unlink = () => {
    setProblem(null);
    link.mutate(
      { carId: car.id, body: { version: car.version, recordId: null } },
      { onError: (error) => setProblem(carSaveError(error)?.message ?? describeCarError(error)) },
    );
  };

  return (
    <div className="space-y-3 rounded-md border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">Quality Cost record</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Optional. Puts this CAR&apos;s cost into the Cost of Quality figures (COPQ and the COQ Matrix).
          </p>
        </div>
        {canEdit && !linked && (
          <div className="flex flex-wrap gap-2">
            {canEditCost && (
              <Button
                variant="outline"
                size="sm"
                disabled={dirty}
                title={dirty ? "Save the CAR first" : undefined}
                onClick={() => setDialog("create")}
              >
                <Plus />
                Create from this CAR
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              disabled={dirty}
              title={dirty ? "Save the CAR first" : undefined}
              onClick={() => setDialog("link")}
            >
              <Link2 />
              Link existing
            </Button>
          </div>
        )}
      </div>
      {linked ? (
        <div className="flex flex-col gap-2 rounded-md bg-muted/40 px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0 text-sm">
            <button
              type="button"
              onClick={() => setView({ kind: "view", id: linked.id })}
              className="font-medium text-primary underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
            >
              {linked.recordNumber}
            </button>{" "}
            <span className="text-muted-foreground">{linked.title}</span>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>{linked.coqClassLabel}</span>
              <span>Total {linked.totalCost === null ? "not entered" : usd(linked.totalCost, 2)}</span>
              <StatusBadge tone="neutral">{linked.financialStatusLabel}</StatusBadge>
              <StatusBadge tone="neutral">{linked.statusLabel}</StatusBadge>
            </p>
          </div>
          {canEdit && (
            <Button
              variant="ghost"
              size="sm"
              onClick={unlink}
              disabled={link.isPending || dirty}
              title={dirty ? "Save the CAR first" : undefined}
            >
              <Unlink />
              Remove link
            </Button>
          )}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Not linked to a Quality Cost record.</p>
      )}
      {dirty && canEdit && (
        <p className="text-xs text-muted-foreground">Save the CAR before changing its Quality Cost link.</p>
      )}
      {problem && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
      <Dialog
        open={dialog === "create"}
        onClose={() => setDialog(null)}
        title="Create a Quality Cost record"
        description={`From ${car.carNumber}: material loss, production time loss and other costs become its material, production and other cost lines.`}
      >
        {dialog === "create" && <CreateCostForm car={car} onDone={() => setDialog(null)} />}
      </Dialog>
      <Dialog
        open={dialog === "link"}
        onClose={() => setDialog(null)}
        title="Link a Quality Cost record"
        description={`Choose the Quality Cost Register item that records ${car.carNumber}'s cost.`}
      >
        {dialog === "link" && <LinkCostForm car={car} onDone={() => setDialog(null)} />}
      </Dialog>
      <CostRecordDialog target={view} onClose={() => setView(null)} />
    </div>
  );
}

function CreateCostForm({ car, onDone }: { car: Car; onDone: () => void }) {
  const id = useId();
  const options = useCostRecordOptions();
  const create = useCreateQualityCost();
  const [areaId, setAreaId] = useState("");
  const [coqClass, setCoqClass] = useState<CoqClass | "">("");
  const [category, setCategory] = useState("");
  const [financialStatus, setFinancialStatus] = useState<FinancialStatus>("potential");
  const [touched, setTouched] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const missing = {
    areaId: areaId ? undefined : "Choose an area.",
    coqClass: coqClass ? undefined : "Choose a COQ classification.",
    category: category ? undefined : "Choose a category.",
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (!areaId || !coqClass || !category) return;
    create.mutate(
      {
        carId: car.id,
        body: { version: car.version, areaId: Number(areaId), coqClass, categoryCode: category, financialStatus },
      },
      {
        onSuccess: onDone,
        onError: (error) => setProblem(carSaveError(error)?.message ?? describeCarError(error)),
      },
    );
  };

  const select = (
    name: string,
    label: string,
    value: string,
    onChange: (value: string) => void,
    items: { value: string; label: string }[],
    error?: string,
  ) => (
    <Field id={`${id}-${name}`} label={label} required error={touched ? error : undefined}>
      <select
        id={`${id}-${name}`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={touched && error ? true : undefined}
        className={inputClasses}
      >
        <option value="">Choose…</option>
        {items.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
    </Field>
  );

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 rounded-md bg-muted/40 px-3 py-2 text-sm">
        <dt className="text-muted-foreground">Date</dt>
        <dd>{formatDate(car.requestDate)}</dd>
        <dt className="text-muted-foreground">Material loss</dt>
        <dd>{car.materialLoss === null ? "Not entered" : usd(car.materialLoss, 2)}</dd>
        <dt className="text-muted-foreground">Production time loss</dt>
        <dd>{car.productionTimeLoss === null ? "Not entered" : usd(car.productionTimeLoss, 2)}</dd>
        <dt className="text-muted-foreground">Other costs</dt>
        <dd>{car.otherCosts === null ? "Not entered" : usd(car.otherCosts, 2)}</dd>
      </dl>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {select(
          "area",
          "Area",
          areaId,
          setAreaId,
          (options.data?.areas ?? []).filter((a) => a.active).map((a) => ({ value: String(a.id), label: a.name })),
          missing.areaId,
        )}
        {select(
          "class",
          "COQ classification",
          coqClass,
          (value) => {
            setCoqClass(value as CoqClass | "");
            setCategory("");
          },
          classChoices(options.data),
          missing.coqClass,
        )}
        {select(
          "category",
          "Category",
          category,
          setCategory,
          coqClass ? categoryChoices(options.data, coqClass) : [],
          missing.category,
        )}
        {select(
          "financial",
          "Financial status",
          financialStatus,
          (value) => setFinancialStatus((value || "potential") as FinancialStatus),
          (options.data?.financialStatuses ?? []).map((s) => ({ value: s.code, label: s.label })),
        )}
      </div>
      {problem && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onDone} disabled={create.isPending}>
          Cancel
        </Button>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? "Creating…" : "Create and link"}
        </Button>
      </div>
    </form>
  );
}

function LinkCostForm({ car, onDone }: { car: Car; onDone: () => void }) {
  const id = useId();
  const [search, setSearch] = useState(car.carNumber);
  const deferred = useDeferredValue(search);
  const query: CostRecordQuery = {
    ...NO_DIMENSIONS,
    from: "",
    to: "",
    status: null,
    open: false,
    classes: [],
    search: deferred,
  };
  const records = useCostRecords(query, deferred.trim().length > 0);
  const link = useLinkQualityCost();
  const [problem, setProblem] = useState<string | null>(null);
  const choose = (recordId: number) => {
    setProblem(null);
    link.mutate(
      { carId: car.id, body: { version: car.version, recordId } },
      { onSuccess: onDone, onError: (error) => setProblem(carSaveError(error)?.message ?? describeCarError(error)) },
    );
  };
  const found = records.data?.records.slice(0, 20) ?? [];
  return (
    <div className="space-y-3">
      <Field id={`${id}-search`} label="Search the Quality Cost Register" required>
        <input
          id={`${id}-search`}
          type="search"
          value={search}
          maxLength={200}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Record ID, title, lot…"
          className={inputClasses}
        />
      </Field>
      {records.isError ? (
        <p role="alert" className="text-sm text-destructive">
          Could not search the Quality Cost Register.
        </p>
      ) : !deferred.trim() ? (
        <p className="text-sm text-muted-foreground">Type to search.</p>
      ) : records.isPending ? (
        <p className="text-sm text-muted-foreground">Searching…</p>
      ) : found.length === 0 ? (
        <p className="text-sm text-muted-foreground">No Quality Cost items match.</p>
      ) : (
        <ul className="divide-y rounded-md border">
          {found.map((record) => (
            <li key={record.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <span className="min-w-0">
                <span className="font-medium">{record.recordNumber}</span>{" "}
                <span className="text-muted-foreground">{record.title}</span>
                <span className="block text-xs text-muted-foreground">
                  {formatDate(record.recordDate)} · {record.coqClassLabel} ·{" "}
                  {record.totalCost === null ? "no cost entered" : usd(record.totalCost, 2)}
                </span>
              </span>
              <Button variant="outline" size="sm" onClick={() => choose(record.id)} disabled={link.isPending}>
                Link
              </Button>
            </li>
          ))}
        </ul>
      )}
      {problem && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
    </div>
  );
}
