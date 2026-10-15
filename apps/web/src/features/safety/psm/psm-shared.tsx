"use client";

import { AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, ShieldAlert, X } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { StatusBadge, type StatusTone } from "@/components/common/status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, fieldClasses } from "@/features/quality/cost/record-form";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

import {
  ACTION_STATUS_LABELS,
  ATTENTION_LABELS,
  describePsmError,
  DISPOSITION_LABELS,
  DUE_STATE_LABELS,
  PAGE_SIZE,
  RISK_LABELS,
} from "./api";

export const EYEBROW = "Safety · Process Safety Management";

const RISK_TONES: Record<string, StatusTone> = { high: "danger", medium: "warning", low: "success" };

/** A risk rating: the color always comes with its label, never alone. */
export function RiskBadge({ risk, className }: { risk: string | null; className?: string }) {
  if (!risk) return <span className="text-xs text-muted-foreground">Not rated</span>;
  return (
    <StatusBadge tone={RISK_TONES[risk] ?? "neutral"} className={className}>
      {RISK_LABELS[risk] ?? risk}
    </StatusBadge>
  );
}

export function DispositionBadge({ disposition }: { disposition: string }) {
  const tone: StatusTone = disposition === "accepted" ? "info" : disposition === "rejected" ? "neutral" : "pending";
  return <StatusBadge tone={tone}>{DISPOSITION_LABELS[disposition] ?? disposition}</StatusBadge>;
}

const STATUS_TONES: Record<string, StatusTone> = {
  not_started: "neutral",
  in_progress: "info",
  pending_verification: "warning",
  closed: "success",
};

export function ActionStatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="text-xs text-muted-foreground">No action</span>;
  return <StatusBadge tone={STATUS_TONES[status] ?? "neutral"}>{ACTION_STATUS_LABELS[status] ?? status}</StatusBadge>;
}

/** Overdue or due soon; nothing for later or closed actions. */
export function DueStateBadge({ state }: { state: string | null }) {
  if (state === "overdue") return <StatusBadge tone="danger">{DUE_STATE_LABELS.overdue}</StatusBadge>;
  if (state === "due_7") return <StatusBadge tone="warning">{DUE_STATE_LABELS.due_7}</StatusBadge>;
  if (state === "no_due_date") return <StatusBadge tone="neutral">{DUE_STATE_LABELS.no_due_date}</StatusBadge>;
  return null;
}

export function AttentionBadges({ reasons }: { reasons: string[] }) {
  if (reasons.length === 0) return null;
  return (
    <span className="flex flex-wrap gap-1">
      {reasons.map((reason) => (
        <StatusBadge key={reason} tone={reason === "overdue" || reason === "notification_failed" ? "danger" : "warning"}>
          {ATTENTION_LABELS[reason] ?? reason}
        </StatusBadge>
      ))}
    </span>
  );
}

export function PsmError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const denied = error instanceof ApiError && (error.status === 401 || error.status === 403);
  return (
    <EmptyState
      icon={AlertTriangle}
      title={denied ? "Process Safety Management is not available to you" : "Could not load Process Safety Management data"}
      description={describePsmError(error)}
      action={
        denied || !onRetry ? undefined : (
          <Button variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        )
      }
    />
  );
}

export function NoPsmData({ filtered, action }: { filtered: boolean; action?: React.ReactNode }) {
  return (
    <EmptyState
      icon={ShieldAlert}
      title={filtered ? "Nothing matches these filters." : "No PHA recommendations yet"}
      description={
        filtered
          ? "Change or clear the filters to see more."
          : "Recommendations appear here once a PHA study is entered or its reviewed workbook is imported. Nothing is shown until then."
      }
      action={action}
    />
  );
}

/** A labelled value in a detail list; blank values say so instead of showing zero. */
export function Detail({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0", className)}>
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm break-words">
        {children === null || children === undefined || children === "" ? (
          <span className="text-muted-foreground">Not recorded</span>
        ) : (
          children
        )}
      </dd>
    </div>
  );
}

/**
 * The selected item of a dashboard or list: what it is, and an explicit button
 * to open it. Selecting never navigates; only the View button does. Render it
 * after the content it belongs to: it stays pinned to the bottom of the
 * viewport, so it is visible wherever the selection was made.
 */
export function ContextPanel({
  title,
  description,
  details,
  viewHref,
  viewLabel = "View",
  onClear,
}: {
  title: string;
  description?: React.ReactNode;
  details?: { label: string; value: React.ReactNode }[];
  viewHref: string;
  viewLabel?: string;
  onClear: () => void;
}) {
  return (
    <aside
      aria-label="Selection"
      aria-live="polite"
      className="sticky bottom-4 z-20 flex flex-col gap-3 rounded-lg border border-primary/40 bg-card p-4 shadow-lg sm:flex-row sm:items-start sm:justify-between"
    >
      <div className="min-w-0 space-y-1">
        <p className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">Selected</p>
        <p className="text-sm font-semibold">{title}</p>
        {description && <div className="text-sm text-muted-foreground">{description}</div>}
        {details && details.length > 0 && (
          <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-4">
            {details.map((item) => (
              <Detail key={item.label} label={item.label}>
                {item.value}
              </Detail>
            ))}
          </dl>
        )}
      </div>
      <div className="flex shrink-0 gap-2">
        <Link href={viewHref} className={buttonVariants({ size: "sm", className: "pointer-coarse:h-11" })}>
          {viewLabel}
        </Link>
        <Button variant="ghost" size="sm" onClick={onClear} aria-label="Clear selection" className="pointer-coarse:h-11">
          <X />
        </Button>
      </div>
    </aside>
  );
}

export function SortHeader({
  label,
  column,
  sort,
  desc,
  onSort,
  className,
}: {
  label: string;
  column: string;
  sort: string;
  desc: boolean;
  onSort: (column: string, desc: boolean) => void;
  className?: string;
}) {
  const active = sort === column;
  const Icon = !active ? ArrowUpDown : desc ? ArrowDown : ArrowUp;
  return (
    <th scope="col" aria-sort={active ? (desc ? "descending" : "ascending") : undefined} className={className}>
      <button
        type="button"
        onClick={() => onSort(column, active ? !desc : false)}
        className="inline-flex items-center gap-1 rounded-sm hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
      >
        {label}
        <Icon aria-hidden className={cn("size-3.5", !active && "opacity-40")} />
      </button>
    </th>
  );
}

export function Pagination({
  page,
  total,
  shown,
  noun,
  onPage,
}: {
  page: number;
  total: number;
  shown: number;
  noun: [string, string];
  onPage: (page: number) => void;
}) {
  if (total <= PAGE_SIZE) return null;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const firstShown = (page - 1) * PAGE_SIZE + 1;
  return (
    <nav aria-label="Pages" className="flex flex-wrap items-center justify-between gap-2 border-t px-4 py-3 text-sm">
      <p className="text-muted-foreground" aria-live="polite">
        {firstShown}–{firstShown + shown - 1} of {total} {total === 1 ? noun[0] : noun[1]} · Page {page} of {pages}
      </p>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)} className="pointer-coarse:h-11">
          Previous
        </Button>
        <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)} className="pointer-coarse:h-11">
          Next
        </Button>
      </div>
    </nav>
  );
}

export function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
      {describePsmError(error)}
    </p>
  );
}

/**
 * Asks for a written reason before a change that needs one (return, reopen,
 * archive…). Nothing is sent until the reason is long enough.
 */
export function ReasonDialog({
  open,
  title,
  description,
  label = "Reason",
  minLength = 10,
  confirmLabel,
  pending,
  error,
  onConfirm,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  description?: React.ReactNode;
  label?: string;
  minLength?: number;
  confirmLabel: string;
  pending: boolean;
  error: unknown;
  onConfirm: (reason: string) => void;
  onClose: () => void;
  children?: React.ReactNode;
}) {
  const id = useId();
  const [reason, setReason] = useState("");
  const short = reason.trim().length < minLength;
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={short || pending} onClick={() => onConfirm(reason.trim())}>
            {pending ? "Saving…" : confirmLabel}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        {children}
        <Field id={`${id}-reason`} label={label} required hint={`At least ${minLength} characters.`}>
          <textarea
            id={`${id}-reason`}
            rows={4}
            value={reason}
            maxLength={8000}
            onChange={(event) => setReason(event.target.value)}
            className={cn(fieldClasses, "py-2")}
          />
        </Field>
        <FormError error={error} />
      </div>
    </Dialog>
  );
}

export const SELECT_ROW =
  "cursor-pointer border-b border-border/60 last:border-b-0 hover:bg-muted/40 aria-selected:bg-primary/10";
