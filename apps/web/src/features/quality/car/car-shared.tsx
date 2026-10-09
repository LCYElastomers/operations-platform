"use client";

import { AlertTriangle, ClipboardCheck } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";

import { describeCarError, type CarSummary, type Choice } from "./api";

export function CarError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const accessDenied = error instanceof ApiError && (error.status === 401 || error.status === 403);
  return (
    <EmptyState
      icon={AlertTriangle}
      title={
        accessDenied
          ? "Corrective Action Reports are not available to you"
          : "Could not load Corrective Action Reports"
      }
      description={describeCarError(error)}
      action={
        accessDenied ? undefined : (
          <Button variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        )
      }
    />
  );
}

export function NoCars({ filtered, action }: { filtered: boolean; action?: React.ReactNode }) {
  return (
    <EmptyState
      icon={ClipboardCheck}
      title={filtered ? "No CARs match these filters" : "No Corrective Action Reports yet"}
      description={
        filtered
          ? "Change or clear the filters to see more CARs."
          : "CARs appear here once they are entered or imported from the reviewed CAR workbook mapping. Nothing is shown until then."
      }
      action={action}
    />
  );
}

/** The options of a controlled list: active values, plus a current older-form value so it still shows. */
export function choiceOptions(choices: Choice[] | undefined, current?: string | string[] | null) {
  const kept = new Set(Array.isArray(current) ? current : current ? [current] : []);
  return (choices ?? [])
    .filter((choice) => choice.active || kept.has(choice.code))
    .map((choice) => ({ value: choice.code, label: choice.active ? choice.label : `${choice.label} (older form)` }));
}

/** Filter options of a controlled list, with every older-form value and "Not recorded". */
export function filterOptions(choices: { code: string; label: string }[] | undefined) {
  return [...(choices ?? []).map((choice) => ({ value: choice.code, label: choice.label })), NOT_RECORDED_OPTION];
}

export const NOT_RECORDED_OPTION = { value: "not_recorded", label: "Not recorded" };

export function CarStatusBadge({ car }: { car: Pick<CarSummary, "status" | "statusLabel"> }) {
  const tone = car.status === "closed" ? "success" : car.status === "open" ? "info" : "neutral";
  return <StatusBadge tone={tone}>{car.statusLabel}</StatusBadge>;
}

/** Past due or due soon; nothing for closed CARs or ones without a due date. */
export function DueBadge({ car }: { car: Pick<CarSummary, "pastDue" | "dueSoon"> }) {
  if (car.pastDue) return <StatusBadge tone="danger">Past due</StatusBadge>;
  if (car.dueSoon) return <StatusBadge tone="warning">Due soon</StatusBadge>;
  return null;
}

export function EffectivenessBadge({
  car,
}: {
  car: Pick<CarSummary, "effectivenessResult" | "effectivenessLabel" | "awaitingEffectiveness">;
}) {
  if (car.effectivenessResult === "effective") return <StatusBadge tone="success">{car.effectivenessLabel}</StatusBadge>;
  if (car.effectivenessResult === "not_effective") return <StatusBadge tone="danger">{car.effectivenessLabel}</StatusBadge>;
  if (car.awaitingEffectiveness) return <StatusBadge tone="warning">Awaiting review</StatusBadge>;
  return <span className="text-xs text-muted-foreground">Not reviewed</span>;
}

/** Complete / total actions; the CAR status alone never implies its actions are done. */
export function ActionProgressLabel({ car }: { car: Pick<CarSummary, "actions"> }) {
  const { total, complete, overdue } = car.actions;
  if (total === 0) return <span className="text-xs text-muted-foreground">No actions</span>;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span className="tabular-nums">
        {complete}/{total} complete
      </span>
      {overdue > 0 && <StatusBadge tone="danger">{overdue} overdue</StatusBadge>}
    </span>
  );
}
