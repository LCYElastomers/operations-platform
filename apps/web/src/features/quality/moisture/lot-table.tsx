"use client";

import { ChevronRight } from "lucide-react";
import { Fragment, useId, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { cn } from "@/lib/utils";

import type { MoistureLotDetail, MoistureRecord } from "./api";
import {
  formatDateRange,
  formatMeasurement,
  formatSourceDate,
  MEASUREMENT_PRECISION,
  MISSING,
  type Measurement,
} from "./format";

const HEADER_CELL =
  "h-10 px-4 text-left text-xs font-semibold tracking-wide whitespace-nowrap text-muted-foreground uppercase";
const BODY_CELL = "h-11 px-4 whitespace-nowrap tabular-nums";
const LOADING_ROWS = 5;

const MASTER_HEADERS = [
  "Date",
  "Product",
  "Lot",
  "Campaign",
  "Records",
  "Avg Moisture",
  "Avg Color",
  "Avg Combined BD",
];
// The expand toggle occupies its own leading column.
const MASTER_COLUMN_COUNT = MASTER_HEADERS.length + 1;

const MEASUREMENTS: Measurement[] = ["avgMoisture", "avgColor", "avgCombinedBd"];

function Missing({ title }: { title: string }) {
  return (
    <span className="text-muted-foreground/60" title={title}>
      {MISSING}
    </span>
  );
}

function MeasurementCell({ value, precision }: { value: number | null; precision: number }) {
  if (value === null) return <Missing title="No value in source" />;
  // Full source precision on hover; rounded for readability.
  return <span title={String(value)}>{formatMeasurement(value, precision)}</span>;
}

function TextCell({ value, missingTitle }: { value: string | null; missingTitle: string }) {
  if (value === null) return <Missing title={missingTitle} />;
  // Source text shown as-is, including case and spacing.
  return <span className="whitespace-pre">{value}</span>;
}

function lotKey(lot: MoistureLotDetail, index: number): string {
  // Lot-less rows are never merged by the API, so only position identifies them.
  return lot.lot === null ? `no-lot:${index}` : JSON.stringify([lot.product, lot.lot]);
}

function lotLabel(lot: MoistureLotDetail): string {
  return `${lot.product ?? "no product"} lot ${lot.lot ?? "(no lot)"}`;
}

/** Location-level records behind one Product + Lot master row. */
export function LotLocationRecords({ records }: { records: MoistureRecord[] }) {
  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b">
          {["Date", "Location", "Moisture", "Color", "Combined BD"].map((header) => (
            <th key={header} scope="col" className={cn(HEADER_CELL, "h-8")}>
              {header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {records.map((record, index) => (
          <tr key={index} className="border-b last:border-b-0">
            <td className={cn(BODY_CELL, "h-9")}>{formatSourceDate(record.date)}</td>
            <td className={cn(BODY_CELL, "h-9")}>
              <TextCell value={record.location} missingTitle="No location in source" />
            </td>
            {MEASUREMENTS.map((key) => (
              <td key={key} className={cn(BODY_CELL, "h-9")}>
                <MeasurementCell value={record[key]} precision={MEASUREMENT_PRECISION[key]} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

type LotTableProps = {
  lots: MoistureLotDetail[];
  loading: boolean;
  emptyState: React.ReactNode;
};

/** Product + Lot master rows, each expandable to the location records it was built from. */
export function LotTable({ lots, loading, emptyState }: LotTableProps) {
  const idPrefix = useId();
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());

  const toggle = (key: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <caption className="sr-only">
            Product and lot averages, most recently measured first. Expand a lot to see its
            location records.
          </caption>
          <thead className="bg-muted/60">
            <tr className="border-b">
              <th scope="col" className="w-10 px-2">
                <span className="sr-only">Location records</span>
              </th>
              {MASTER_HEADERS.map((header) => (
                <th key={header} scope="col" className={HEADER_CELL}>
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody aria-busy={loading || undefined}>
            {loading ? (
              Array.from({ length: LOADING_ROWS }, (_, index) => (
                <tr key={index} className="border-b last:border-b-0">
                  {Array.from({ length: MASTER_COLUMN_COUNT }, (_, cell) => (
                    <td key={cell} className="h-11 px-4">
                      <div className="h-3 w-full max-w-24 animate-pulse rounded bg-muted" />
                    </td>
                  ))}
                </tr>
              ))
            ) : lots.length === 0 ? (
              <tr>
                <td colSpan={MASTER_COLUMN_COUNT} className="p-0">
                  {emptyState ?? <EmptyState variant="plain" title="No records" />}
                </td>
              </tr>
            ) : (
              lots.map((lot, index) => {
                const key = lotKey(lot, index);
                const open = expanded.has(key);
                const detailId = `${idPrefix}-lot-${index}`;
                return (
                  <Fragment key={key}>
                    <tr
                      className={cn(
                        "border-b last:border-b-0 hover:bg-muted/40",
                        open && "bg-muted/30",
                      )}
                    >
                      <td className="w-10 px-2">
                        <button
                          type="button"
                          aria-expanded={open}
                          aria-controls={open ? detailId : undefined}
                          aria-label={`${open ? "Hide" : "Show"} location records for ${lotLabel(lot)}`}
                          onClick={() => toggle(key)}
                          className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                        >
                          <ChevronRight
                            aria-hidden
                            className={cn("size-4 transition-transform", open && "rotate-90")}
                          />
                        </button>
                      </td>
                      <td className={BODY_CELL}>{formatDateRange(lot.firstDate, lot.lastDate)}</td>
                      <td className={cn(BODY_CELL, "font-medium")}>
                        <TextCell value={lot.product} missingTitle="No product in source" />
                      </td>
                      <td className={cn(BODY_CELL, "font-medium")}>
                        <TextCell value={lot.lot} missingTitle="No lot in source" />
                      </td>
                      <td className={BODY_CELL}>
                        {lot.campaignNos.length > 0 ? (
                          lot.campaignNos.join(", ")
                        ) : (
                          <Missing title="No campaign in source" />
                        )}
                      </td>
                      <td className={BODY_CELL}>
                        <span title={lot.locations.join(", ") || undefined}>
                          {lot.recordCount.toLocaleString()}
                        </span>
                      </td>
                      {MEASUREMENTS.map((measurement) => (
                        <td key={measurement} className={cn(BODY_CELL, "font-medium")}>
                          <MeasurementCell
                            value={lot[measurement]}
                            precision={MEASUREMENT_PRECISION[measurement]}
                          />
                        </td>
                      ))}
                    </tr>
                    {open && (
                      <tr id={detailId} className="border-b bg-muted/20 last:border-b-0">
                        <td colSpan={MASTER_COLUMN_COUNT} className="py-2 pr-4 pl-12">
                          <LotLocationRecords records={lot.records} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
