"use client";

import { FileText, Plus } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

import type { EventType, MonthReconciliation, ReconciliationResponse } from "./api";
import { describeReconciliation, monthActionLabel, monthDateRange, stateTone } from "./record-data";
import { RecordDialog } from "./record-dialog";
import { useRecordReconciliation } from "./use-records";

const TONE_CLASSES = {
  ok: "border-success/40 text-success",
  warning: "border-warning/60 bg-warning/15 text-amber-700 dark:text-warning",
  neutral: "text-muted-foreground",
};

/**
 * One month's record button: "Add" when nothing is documented, otherwise the
 * documented count, coloured by its reconciliation with the monthly total.
 */
export function MonthRecordButton({
  month,
  year,
  canEdit,
  onOpen,
}: {
  month: MonthReconciliation;
  year: number;
  canEdit: boolean;
  onOpen: () => void;
}) {
  const label = monthActionLabel(month.eventType, month.documented, year, month.month);
  if (month.documented === 0 && !canEdit) return null;
  const tone = stateTone(month.state);
  const description = describeReconciliation(month);
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={canEdit || month.documented === 0 ? label : label.replace(/^Manage/, "View")}
      title={`${label}. ${description}`}
      className={cn(
        "inline-flex h-8 w-full items-center justify-end gap-1 rounded-sm border bg-card px-1.5 text-xs font-medium tabular-nums",
        "hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none pointer-coarse:h-11",
        month.documented === 0 ? "border-dashed text-muted-foreground" : TONE_CLASSES[tone],
      )}
    >
      {month.documented === 0 ? (
        <>
          <Plus aria-hidden className="size-3.5" />
          <span aria-hidden>Add</span>
        </>
      ) : (
        <>
          <FileText aria-hidden className="size-3.5" />
          <span aria-hidden>{month.documented}</span>
          {tone === "warning" && <span aria-hidden>!</span>}
        </>
      )}
    </button>
  );
}

type Opened = { eventType: EventType; month: number; adding: boolean } | null;

/**
 * Record buttons for the Incident and Near Miss rows of the monthly grid, and the
 * dialog they open. `null` sub-rows when the user cannot read records.
 */
export function useMonthRecords(year: number, today: string) {
  const reconciliation = useRecordReconciliation(year);
  const [opened, setOpened] = useState<Opened>(null);
  const data: ReconciliationResponse | undefined = reconciliation.data;

  const subRow = (eventType: EventType) => {
    if (!data) return undefined;
    const cells = Array.from({ length: 12 }, (_, index) => {
      const month = data.months.find((m) => m.eventType === eventType && m.month === index + 1);
      if (!month || monthDateRange(year, index + 1, today) === null) return null;
      return (
        <MonthRecordButton
          key={index}
          month={month}
          year={year}
          canEdit={data.canEdit}
          onOpen={() => setOpened({ eventType, month: index + 1, adding: month.documented === 0 && data.canEdit })}
        />
      );
    });
    return { label: "Records", cells };
  };

  const current = opened && data?.months.find((m) => m.eventType === opened.eventType && m.month === opened.month);
  const dialog = data && opened && (
    <RecordDialog
      key={`${opened.eventType}-${opened.month}`}
      open
      onClose={() => setOpened(null)}
      scope={{ kind: "month", eventType: opened.eventType, year, month: opened.month, reconciliation: current ?? undefined }}
      initialPanel={opened.adding ? { kind: "create", eventType: opened.eventType } : undefined}
      permissions={data}
      today={today}
    />
  );

  return { subRow, dialog };
}
