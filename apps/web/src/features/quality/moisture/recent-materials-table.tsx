"use client";

import { DataTable, type DataTableColumn } from "@/components/common/data-table";

import type { MoistureRecord } from "./api";
import { formatMeasurement, formatSourceDate, MEASUREMENT_PRECISION, MISSING, type Measurement } from "./format";

function MeasurementCell({ value, precision }: { value: number | null; precision: number }) {
  if (value === null) {
    return (
      <span className="text-muted-foreground/60" title="No value in source">
        {MISSING}
      </span>
    );
  }
  // Full source precision on hover; rounded for readability.
  return <span title={String(value)}>{formatMeasurement(value, precision)}</span>;
}

function measurementColumn(key: Measurement, header: string): DataTableColumn<MoistureRecord> {
  return {
    accessorKey: key,
    header,
    cell: ({ row }) => (
      <MeasurementCell value={row.original[key]} precision={MEASUREMENT_PRECISION[key]} />
    ),
  };
}

export const recentMaterialsColumns: DataTableColumn<MoistureRecord>[] = [
  {
    accessorKey: "date",
    header: "Date",
    cell: ({ row }) => formatSourceDate(row.original.date),
  },
  { accessorKey: "campaignNo", header: "Campaign" },
  { accessorKey: "product", header: "Product" },
  { accessorKey: "lot", header: "Lot" },
  {
    accessorKey: "location",
    header: "Location",
    // Source text shown as-is, including case and spacing.
    cell: ({ row }) =>
      row.original.location === null ? (
        <span className="text-muted-foreground/60">{MISSING}</span>
      ) : (
        <span className="whitespace-pre">{row.original.location}</span>
      ),
  },
  measurementColumn("avgMoisture", "Avg Moisture"),
  measurementColumn("avgColor", "Avg Color"),
  measurementColumn("avgCombinedBd", "Avg Combined BD"),
];

type RecentMaterialsTableProps = {
  records: MoistureRecord[];
  loading: boolean;
  emptyState: React.ReactNode;
};

export function RecentMaterialsTable({ records, loading, emptyState }: RecentMaterialsTableProps) {
  return (
    <DataTable
      caption="Recent materials, newest first"
      columns={recentMaterialsColumns}
      data={records}
      loading={loading}
      emptyState={emptyState}
      enableSorting={false}
    />
  );
}
