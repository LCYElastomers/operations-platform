"use client";

import { CircleDollarSign, Percent, ShieldCheck, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { BarChart } from "@/components/common/bar-chart";
import { FilterSelect } from "@/components/common/filter-bar";
import { MetricCard } from "@/components/common/metric-card";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";

import type { CoqClass, CoqClassValue, CostSummary } from "./api";
import { CostError, CostFilters, CostLineRegister, DataChecks, Definitions, NoFigures, useCostSummary } from "./cost-shared";
import { COQ_CLASS_COLORS, COQ_CLASS_LABELS, MONTH_LABELS, percent, periodLabel, reportedLabel, toNumber, usd } from "./format";

const QUADRANT_TEXT: Record<CoqClass, string> = {
  prevention: "Costs to stop defects happening: planning, training, process control.",
  appraisal: "Costs to find defects: inspection, testing, audits.",
  internal_failure: "Defects found before shipment: scrap and off-spec losses.",
  external_failure: "Defects found by customers: complaint, freight, credit and rework costs.",
};

const CLASS_OPTIONS = (Object.keys(COQ_CLASS_LABELS) as CoqClass[]).map((code) => ({
  value: code,
  label: COQ_CLASS_LABELS[code],
}));

export function CoqMatrixPage({ title, description }: { title: string; description?: string }) {
  const state = useCostSummary();
  const { summary } = state;
  const data = summary.data;
  const [coqClass, setCoqClass] = useState<CoqClass | null>(null);
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Quality · Cost of Quality" title={title} description={description} />
      <p className="-mt-2 max-w-4xl text-sm text-muted-foreground">
        Cost of Quality = good quality costs (prevention + appraisal) + poor quality costs (internal + external failure).
        Classes the source does not record are shown as not recorded, never as $0, and totals that need them are not
        calculated.
      </p>
      <CostFilters state={state}>
        <FilterSelect
          label="COQ class"
          options={CLASS_OPTIONS}
          value={coqClass ?? ""}
          onChange={(event) => setCoqClass((event.target.value || null) as CoqClass | null)}
          className="pointer-coarse:h-11"
        />
      </CostFilters>
      {summary.isError ? (
        <CostError summary={summary} />
      ) : data && data.year === null ? (
        <NoFigures />
      ) : (
        <>
          <Kpis data={data} loading={summary.isPending} />
          {data && (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <Quadrants data={data} selected={coqClass} />
              <div className="space-y-4">
                <Mix data={data} />
                <Trend data={data} />
              </div>
            </div>
          )}
          {data && (
            <CostLineRegister
              data={data}
              coqClass={coqClass}
              title={coqClass ? `${COQ_CLASS_LABELS[coqClass]} cost lines` : "Cost lines by COQ class"}
            />
          )}
          {data && <DataChecks data={data} />}
          {data && <Definitions data={data} />}
        </>
      )}
    </div>
  );
}

function Kpis({ data, loading }: { data: CostSummary | undefined; loading: boolean }) {
  const matrix = data?.matrix;
  const label = data ? `${periodLabel(data.year, data.period)} · ${reportedLabel(data.period)}` : undefined;
  const unavailable = "Not calculable: prevention and appraisal are not recorded.";
  return (
    <section aria-label="Cost of Quality" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard
        label="Total COQ"
        value={matrix?.total ? usd(matrix.total) : null}
        caption={matrix?.total ? label : unavailable}
        icon={CircleDollarSign}
        emphasis
        loading={loading}
      />
      <MetricCard
        label="Good COQ (P + A)"
        value={matrix?.good ? usd(matrix.good) : null}
        caption={matrix?.good ? label : "Not recorded in the source."}
        icon={ShieldCheck}
        emphasis
        loading={loading}
      />
      <MetricCard
        label="Poor COQ (IF + EF)"
        value={matrix?.poor ? usd(matrix.poor) : null}
        caption={label}
        icon={TriangleAlert}
        emphasis
        loading={loading}
      />
      <MetricCard
        label="Poor COQ % of total"
        value={matrix?.poorPct ? percent(matrix.poorPct) : null}
        caption={matrix?.poorPct ? label : unavailable}
        icon={Percent}
        emphasis
        loading={loading}
      />
    </section>
  );
}

function Quadrant({ item, highlighted }: { item: CoqClassValue; highlighted: boolean }) {
  const color = COQ_CLASS_COLORS[item.code];
  return (
    <div
      className="flex min-h-36 flex-col rounded-lg border-2 p-4"
      style={{ borderColor: highlighted ? color : `${color}55`, backgroundColor: `${color}0d` }}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold" style={{ color }}>
          {item.label}
        </h3>
        {!item.recorded && <StatusBadge tone="neutral">Not recorded</StatusBadge>}
      </div>
      <p className="mt-2 text-2xl font-semibold tabular-nums">
        {item.value === null ? (
          <span className="text-muted-foreground/70">
            <span aria-hidden>—</span>
            <span className="sr-only">{item.recorded ? "Not reported" : "Not recorded"}</span>
          </span>
        ) : (
          usd(item.value)
        )}
      </p>
      <p className="text-xs text-muted-foreground">
        {item.shareOfRecorded ? `${percent(item.shareOfRecorded, 1)} of recorded costs` : item.recorded ? "\u00a0" : "No source data"}
      </p>
      <p className="mt-auto pt-2 text-xs text-muted-foreground">{QUADRANT_TEXT[item.code]}</p>
    </div>
  );
}

function Quadrants({ data, selected }: { data: CostSummary; selected: CoqClass | null }) {
  const byCode = Object.fromEntries(data.matrix.classes.map((item) => [item.code, item])) as Record<CoqClass, CoqClassValue>;
  return (
    <section aria-labelledby="coq-matrix" className="rounded-lg border bg-card">
      <header className="border-b px-4 py-3">
        <h2 id="coq-matrix" className="text-sm font-semibold">
          Cost of Quality matrix
        </h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {periodLabel(data.year, data.period)}. Top row: good quality costs. Bottom row: poor quality costs.
        </p>
      </header>
      <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2">
        {(["prevention", "appraisal", "internal_failure", "external_failure"] as const).map((code) => (
          <Quadrant key={code} item={byCode[code]} highlighted={selected === code} />
        ))}
      </div>
      {data.matrix.unavailableReason && (
        <p className="border-t px-4 py-2 text-xs text-muted-foreground">{data.matrix.unavailableReason}</p>
      )}
    </section>
  );
}

function Mix({ data }: { data: CostSummary }) {
  const shares = data.matrix.classes
    .map((item) => ({ item, share: toNumber(item.shareOfRecorded) }))
    .filter((entry): entry is { item: CoqClassValue; share: number } => entry.share !== null && entry.share > 0);
  const unrecorded = data.matrix.classes.filter((item) => !item.recorded);
  return (
    <section aria-labelledby="coq-mix" className="rounded-lg border bg-card px-4 py-3">
      <h2 id="coq-mix" className="text-sm font-semibold">
        COQ mix
      </h2>
      <p className="mt-0.5 text-xs text-muted-foreground">
        Share of recorded costs ({usd(data.matrix.recordedTotal)}).
        {unrecorded.length > 0 &&
          ` ${unrecorded.map((item) => item.label).join(" and ")} are not recorded, so this is the failure-cost mix only.`}
      </p>
      {shares.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">No costs recorded in this period.</p>
      ) : (
        <>
          <div className="mt-3 flex h-4 w-full overflow-hidden rounded-full bg-muted" role="img" aria-label="COQ mix">
            {shares.map(({ item, share }) => (
              <div key={item.code} style={{ width: `${share * 100}%`, backgroundColor: COQ_CLASS_COLORS[item.code] }} />
            ))}
          </div>
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {data.matrix.classes.map((item) => (
              <li key={item.code} className="flex items-center gap-1.5">
                <span aria-hidden className="size-2.5 rounded-sm" style={{ backgroundColor: COQ_CLASS_COLORS[item.code] }} />
                <span>{item.label}</span>
                <span className="text-muted-foreground tabular-nums">
                  {item.recorded ? percent(item.shareOfRecorded, 1) : "not recorded"}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function Trend({ data }: { data: CostSummary }) {
  const { fromMonth, throughMonth } = data.period;
  const months = data.months.filter(
    (month) => fromMonth !== null && throughMonth !== null && month.month >= fromMonth && month.month <= throughMonth,
  );
  const dollars = (value: string | null) => {
    const number = toNumber(value);
    return number === null ? null : Math.round(number);
  };
  return (
    <BarChart
      title="COQ by class and month"
      description="Recorded classes only. Prevention and appraisal have no source data and are not drawn."
      categories={months.map((month) => MONTH_LABELS[month.month - 1])}
      series={[
        {
          name: COQ_CLASS_LABELS.internal_failure,
          values: months.map((month) => dollars(month.internalFailure)),
          color: COQ_CLASS_COLORS.internal_failure,
          stack: "coq",
        },
        {
          name: COQ_CLASS_LABELS.external_failure,
          values: months.map((month) => dollars(month.externalFailure)),
          color: COQ_CLASS_COLORS.external_failure,
          stack: "coq",
        },
      ]}
      height={220}
    />
  );
}
