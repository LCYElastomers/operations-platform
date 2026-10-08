"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Calculator } from "lucide-react";
import { useId, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

import {
  costKeys,
  describeCostError,
  fetchEstimatorReference,
  requestEstimate,
  type Estimate,
  type EstimateRequest,
  type EstimatorReference,
  type PackageType,
} from "./api";
import { quantity, toNumber, usd } from "./format";

type Section = "downtime" | "lowerProduction" | "scrap" | "cGrade" | "rework" | "repack";

type Field = { key: string; label: string; unit: string; integer?: boolean };

const SECTIONS: { id: Section; label: string; hint: string; fields: Field[]; needsProduct?: boolean; package?: boolean }[] = [
  {
    id: "downtime",
    label: "Downtime",
    hint: "One or both finishing lines shut down.",
    needsProduct: true,
    fields: [{ key: "downtimeHours", label: "Total downtime", unit: "hours" }],
  },
  {
    id: "lowerProduction",
    label: "Lower production rate",
    hint: "Polymer rate reduced (SP-40121). Not for reductions caused by downtime or rework.",
    needsProduct: true,
    fields: [
      { key: "flowRateLbPerHour", label: "Reduced flow rate", unit: "lb/h" },
      { key: "hours", label: "Hours at the lower rate", unit: "hours" },
    ],
  },
  {
    id: "scrap",
    label: "More scrap",
    hint: "Scrap produced because of the incident.",
    fields: [{ key: "quantityLbs", label: "Scrap produced", unit: "lb" }],
  },
  {
    id: "cGrade",
    label: "More C-grade",
    hint: "Off-spec product that will be sold as C-grade.",
    fields: [{ key: "quantityLbs", label: "C-grade produced", unit: "lb" }],
  },
  {
    id: "rework",
    label: "Rework",
    hint: "Product reprocessed into prime.",
    needsProduct: true,
    package: true,
    fields: [
      { key: "productionRateReductionLbPerHour", label: "Production rate reduction", unit: "lb/h" },
      { key: "reworkingRateLbPerHour", label: "Reworking rate", unit: "lb/h" },
      { key: "quantityLbs", label: "Quantity to rework", unit: "lb" },
      { key: "packageLoadLbPerPiece", label: "Load per package", unit: "lb/piece" },
    ],
  },
  {
    id: "repack",
    label: "Repack",
    hint: "Product repacked without reprocessing.",
    package: true,
    fields: [
      { key: "quantityLbs", label: "Quantity to repack", unit: "lb" },
      { key: "packageLoadLbPerPiece", label: "Load per package", unit: "lb/piece" },
      { key: "extraPersons", label: "Extra persons", unit: "persons", integer: true },
      { key: "overtimeHoursPerPerson", label: "Overtime per person", unit: "hours" },
      { key: "payRateUsdPerHour", label: "Pay rate", unit: "USD/h" },
    ],
  },
];

type Draft = {
  product: string;
  selected: Record<Section, boolean>;
  values: Record<Section, Record<string, string>>;
  packageType: Record<"rework" | "repack", PackageType | "">;
};

const EMPTY_DRAFT: Draft = {
  product: "",
  selected: { downtime: false, lowerProduction: false, scrap: false, cGrade: false, rework: false, repack: false },
  values: { downtime: {}, lowerProduction: {}, scrap: {}, cGrade: {}, rework: {}, repack: {} },
  packageType: { rework: "", repack: "" },
};

const NUMBER = /^\d+(\.\d+)?$/;
const INTEGER = /^\d+$/;

/** The request for the selected sections, or the first problem found. */
export function buildEstimateRequest(draft: Draft): { request: EstimateRequest } | { problem: string } {
  const chosen = SECTIONS.filter((section) => draft.selected[section.id]);
  if (chosen.length === 0) return { problem: "Select at least one consequence of the incident." };
  if (chosen.some((section) => section.needsProduct) && !draft.product) {
    return { problem: "Select the product for downtime, lower production rate or rework." };
  }
  const request: Record<string, unknown> = {};
  if (draft.product) request.product = draft.product;
  for (const section of chosen) {
    const body: Record<string, string> = {};
    for (const field of section.fields) {
      const value = (draft.values[section.id][field.key] ?? "").trim();
      if (!(field.integer ? INTEGER : NUMBER).test(value)) {
        return { problem: `${section.label}: enter ${field.label.toLowerCase()} as a ${field.integer ? "whole " : ""}number.` };
      }
      body[field.key] = value;
    }
    if (section.package) {
      const packageType = draft.packageType[section.id as "rework" | "repack"];
      if (!packageType) return { problem: `${section.label}: select the package type.` };
      body.packageType = packageType;
    }
    request[section.id] = body;
  }
  return { request: request as EstimateRequest };
}

export function CostEstimator() {
  const reference = useQuery({
    queryKey: costKeys.estimator(),
    queryFn: ({ signal }) => fetchEstimatorReference(signal),
    retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    staleTime: Infinity,
  });
  if (reference.isError) {
    const accessDenied = reference.error instanceof ApiError && [401, 403].includes(reference.error.status);
    return (
      <div className="pt-4">
        <EmptyState
          icon={AlertTriangle}
          title={accessDenied ? "The estimator is not available to you" : "Could not load the estimator"}
          description={describeCostError(reference.error)}
          action={
            accessDenied ? undefined : (
              <Button variant="outline" size="sm" onClick={() => void reference.refetch()}>
                Retry
              </Button>
            )
          }
        />
      </div>
    );
  }
  if (!reference.data) {
    return <div className="mt-4 h-64 animate-pulse rounded-lg bg-muted/70" aria-busy />;
  }
  return <EstimatorForm reference={reference.data} />;
}

const INPUT =
  "h-9 w-full rounded-md border border-input bg-background px-3 text-sm tabular-nums shadow-xs pointer-coarse:h-11";

function EstimatorForm({ reference }: { reference: EstimatorReference }) {
  const id = useId();
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [problem, setProblem] = useState<string | null>(null);
  const estimate = useMutation({ mutationFn: requestEstimate });

  const update = (change: (current: Draft) => Draft) => {
    setDraft(change);
    setProblem(null);
    estimate.reset();
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const built = buildEstimateRequest(draft);
    if ("problem" in built) {
      setProblem(built.problem);
      return;
    }
    estimate.mutate(built.request);
  };

  return (
    <div className="space-y-5 pt-4">
      <p className="max-w-4xl text-sm text-muted-foreground">
        Estimates one incident&apos;s cost of poor quality with the method of the {reference.source} workbook. The
        estimate is calculated by the server and is not saved.
      </p>
      <ul className="max-w-4xl list-disc space-y-1 pl-5 text-sm">
        {reference.guidance.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>

      <form onSubmit={submit} noValidate className="space-y-4" aria-describedby={`${id}-problem`}>
        <label className="flex max-w-xs flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">Product (finishing line)</span>
          <select
            className={INPUT}
            value={draft.product}
            onChange={(event) => update((current) => ({ ...current, product: event.target.value }))}
          >
            <option value="">Select a product</option>
            {reference.products.map((product) => (
              <option key={product.code} value={product.code}>
                {product.code} ({quantity(product.standardRateMtPerDay)} MT/day)
              </option>
            ))}
          </select>
        </label>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {SECTIONS.map((section) => {
            const checked = draft.selected[section.id];
            return (
              <fieldset
                key={section.id}
                className={cn("rounded-lg border bg-card p-4", checked && "border-primary/50 ring-1 ring-primary/20")}
              >
                <legend className="sr-only">{section.label}</legend>
                <label className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    className="mt-0.5 size-4 pointer-coarse:size-5"
                    checked={checked}
                    onChange={(event) =>
                      update((current) => ({
                        ...current,
                        selected: { ...current.selected, [section.id]: event.target.checked },
                      }))
                    }
                  />
                  <span>
                    <span className="block text-sm font-medium">{section.label}</span>
                    <span className="block text-xs text-muted-foreground">{section.hint}</span>
                  </span>
                </label>
                {checked && (
                  <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {section.fields.map((field) => (
                      <label key={field.key} className="flex flex-col gap-1">
                        <span className="text-xs font-medium text-muted-foreground">
                          {field.label} ({field.unit})
                        </span>
                        <input
                          className={INPUT}
                          inputMode={field.integer ? "numeric" : "decimal"}
                          autoComplete="off"
                          value={draft.values[section.id][field.key] ?? ""}
                          onChange={(event) =>
                            update((current) => ({
                              ...current,
                              values: {
                                ...current.values,
                                [section.id]: { ...current.values[section.id], [field.key]: event.target.value },
                              },
                            }))
                          }
                        />
                      </label>
                    ))}
                    {section.package && (
                      <label className="flex flex-col gap-1">
                        <span className="text-xs font-medium text-muted-foreground">Package type</span>
                        <select
                          className={INPUT}
                          value={draft.packageType[section.id as "rework" | "repack"]}
                          onChange={(event) =>
                            update((current) => ({
                              ...current,
                              packageType: {
                                ...current.packageType,
                                [section.id]: event.target.value as PackageType | "",
                              },
                            }))
                          }
                        >
                          <option value="">Select</option>
                          {reference.packageTypes.map((type) => (
                            <option key={type} value={type}>
                              {type}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                  </div>
                )}
              </fieldset>
            );
          })}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={estimate.isPending} className="pointer-coarse:h-11">
            <Calculator />
            Calculate estimate
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => update(() => EMPTY_DRAFT)}
            className="pointer-coarse:h-11"
          >
            Clear
          </Button>
          <p id={`${id}-problem`} role="alert" className="text-sm text-destructive">
            {problem ?? (estimate.isError ? describeCostError(estimate.error) : null)}
          </p>
        </div>
      </form>

      {estimate.data && <EstimateResult estimate={estimate.data} />}

      <details className="rounded-lg border bg-card px-4 py-3 text-sm">
        <summary className="cursor-pointer font-semibold">Assumptions and notes</summary>
        <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1.5 sm:grid-cols-[max-content_1fr]">
          {reference.assumptions.map((item) => (
            <div key={item.label} className="contents">
              <dt className="font-medium">{item.label}</dt>
              <dd className="text-muted-foreground tabular-nums">
                {item.value} {item.unit}
              </dd>
            </div>
          ))}
        </dl>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-muted-foreground">
          {reference.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function kusd(value: string): string {
  const number = toNumber(value);
  return number === null ? "—" : `${number.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} kUSD`;
}

function step(value: string, unit: string): string {
  const number = toNumber(value);
  if (number === null) return "—";
  const digits = unit === "USD per lb" ? 4 : 2;
  return `${number.toLocaleString("en-US", { maximumFractionDigits: digits })} ${unit}`;
}

function EstimateResult({ estimate }: { estimate: Estimate }) {
  return (
    <section aria-labelledby="estimate-result" className="overflow-hidden rounded-lg border bg-card">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div>
          <h2 id="estimate-result" className="text-sm font-semibold">
            Estimated cost of poor quality
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">Calculated with the workbook method. Not saved.</p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-semibold tabular-nums">{usd(estimate.totalUsd)}</p>
          <p className="text-xs text-muted-foreground tabular-nums">{kusd(estimate.totalKusd)}</p>
        </div>
      </header>
      {estimate.warnings.length > 0 && (
        <ul className="space-y-1 border-b px-4 py-3 text-sm">
          {estimate.warnings.map((warning) => (
            <li key={warning} className="flex items-start gap-2">
              <StatusBadge tone="warning">Check</StatusBadge>
              {warning}
            </li>
          ))}
        </ul>
      )}
      <ul className="divide-y">
        {estimate.lines.map((line) => (
          <li key={line.code} className="px-4 py-3 text-sm">
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="font-medium">{line.label}</h3>
              <span className="font-semibold tabular-nums">{kusd(line.totalKusd)}</span>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">{line.formula}</p>
            <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
              {line.steps.map((item) => (
                <div key={item.label} className="flex justify-between gap-3">
                  <dt className="text-muted-foreground">{item.label}</dt>
                  <dd className="tabular-nums">{step(item.value, item.unit)}</dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ul>
    </section>
  );
}
