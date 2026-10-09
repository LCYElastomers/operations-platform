"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Inbox } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { describeAdminError } from "@/features/admin/api";
import { carHref } from "@/features/quality/car/api";
import { CostRecordDialog, type CostDialogTarget } from "@/features/quality/cost/record-dialog";
import { formatDate } from "@/features/quality/cost/format";
import { apiGet } from "@/lib/api-client";

export type Assignment = {
  kind: "car" | "car_action" | "quality_cost";
  id: number;
  /** The CAR an action belongs to. */
  carId: number | null;
  reference: string;
  title: string;
  status: string | null;
  dueDate: string | null;
  overdue: boolean;
};

const KIND_LABELS: Record<Assignment["kind"], string> = {
  car: "Corrective Action Report",
  car_action: "CAR action",
  quality_cost: "Quality cost item",
};

function statusLabel(status: string | null): string {
  if (status === null) return "No status";
  const text = status.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Open work assigned to the signed-in user. The API decides who "me" is from the session. */
export function AssignmentsPage({ title, description }: { title: string; description?: string }) {
  const assignments = useQuery({
    queryKey: ["assignments", "mine"],
    queryFn: ({ signal }) => apiGet<{ assignments: Assignment[] }>("/api/v1/assignments/mine", { signal }),
  });
  const [costTarget, setCostTarget] = useState<CostDialogTarget | null>(null);
  const items = assignments.data?.assignments ?? [];

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Work" title={title} description={description} />
      {assignments.isError ? (
        <EmptyState icon={AlertTriangle} title="Assignments could not be loaded" description={describeAdminError(assignments.error)} />
      ) : assignments.isPending ? (
        <p className="py-6 text-sm text-muted-foreground">Loading assignments…</p>
      ) : items.length === 0 ? (
        <EmptyState icon={Inbox} title="Nothing assigned to you" description="Open CARs, CAR actions and quality cost items assigned to you appear here." />
      ) : (
        <ul className="divide-y rounded-lg border bg-card">
          {items.map((item) => {
            const body = (
              <>
                <span className="min-w-0 flex-1">
                  <span className="block text-xs font-medium text-muted-foreground">
                    {KIND_LABELS[item.kind]} · {item.reference}
                  </span>
                  <span className="block truncate font-medium text-primary">{item.title}</span>
                </span>
                <span className="flex shrink-0 flex-wrap items-center justify-end gap-2 text-sm">
                  <StatusBadge tone={item.overdue ? "warning" : "info"}>
                    {statusLabel(item.status)}
                    {item.overdue ? " · overdue" : ""}
                  </StatusBadge>
                  <span className="w-28 text-right text-muted-foreground tabular-nums">
                    {item.dueDate ? `Due ${formatDate(item.dueDate)}` : "No due date"}
                  </span>
                </span>
              </>
            );
            const rowClass =
              "flex w-full items-center gap-4 px-4 py-3 text-left hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none";
            return (
              <li key={`${item.kind}:${item.id}`}>
                {item.kind === "quality_cost" ? (
                  <button type="button" className={rowClass} onClick={() => setCostTarget({ kind: "view", id: item.id })}>
                    {body}
                  </button>
                ) : (
                  <Link href={carHref(item.carId ?? item.id)} className={rowClass}>
                    {body}
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <CostRecordDialog target={costTarget} onClose={() => setCostTarget(null)} />
    </div>
  );
}
