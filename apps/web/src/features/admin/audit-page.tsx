"use client";

import { AlertTriangle, ScrollText } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { FilterBar, FilterSelect } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";

import { describeAdminError, type AuditEvent } from "./api";
import { formatDateTime } from "./admin-shared";
import { useAudit } from "./use-admin";

const PAGE_SIZE = 50;

const ENTITY_TYPES = [
  { value: "core.user", label: "Users" },
  { value: "core.role", label: "Roles" },
  { value: "quality.car", label: "Corrective Action Reports" },
  { value: "quality.car_action", label: "CAR actions" },
  { value: "quality.cost_record", label: "Quality cost items" },
  { value: "safety.incident_record", label: "Safety incident records" },
  { value: "safety.observation", label: "Safety observations" },
  { value: "safety.monthly_metric_value", label: "Safety monthly values" },
  { value: "safety.performance_hours", label: "Safety worked hours" },
];

function shown(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Fields that differ between the event's before and after values. */
export function auditChanges(event: AuditEvent): { field: string; from: string; to: string }[] {
  const before = event.oldValue ?? {};
  const after = event.newValue ?? {};
  const fields = [...new Set([...Object.keys(before), ...Object.keys(after)])];
  return fields
    .filter((field) => JSON.stringify(before[field]) !== JSON.stringify(after[field]))
    .map((field) => ({ field, from: shown(before[field]), to: shown(after[field]) }));
}

/** Who changed what, and when. Values are shown as the API returns them; nothing secret is stored in events. */
export function AuditPage({ title, description }: { title: string; description?: string }) {
  const [entityType, setEntityType] = useState("");
  const [offset, setOffset] = useState(0);
  const audit = useAudit({ entityType, offset, limit: PAGE_SIZE });
  const data = audit.data;

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="System" title={title} description={description} />
      <FilterBar
        actions={
          audit.isFetching &&
          !audit.isPending && (
            <StatusBadge tone="pending" pulse>
              Updating
            </StatusBadge>
          )
        }
      >
        <FilterSelect
          label="Record type"
          options={ENTITY_TYPES}
          value={entityType}
          onChange={(event) => {
            setEntityType(event.target.value);
            setOffset(0);
          }}
        />
      </FilterBar>
      {audit.isError ? (
        <EmptyState icon={AlertTriangle} title="The audit log could not be loaded" description={describeAdminError(audit.error)} />
      ) : !data ? (
        <p className="py-6 text-sm text-muted-foreground">Loading audit events…</p>
      ) : data.events.length === 0 ? (
        <EmptyState icon={ScrollText} title="No audit events" description={entityType ? "None for this record type." : undefined} />
      ) : (
        <>
          <ol className="divide-y rounded-lg border bg-card">
            {data.events.map((event) => (
              <li key={event.id} className="px-4 py-3 text-sm">
                <p className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-medium">{event.actorName ?? event.actorId}</span>
                  <span className="text-muted-foreground">{event.action.replace(/_/g, " ")}</span>
                  <span className="font-mono text-xs">
                    {event.entityType} {event.entityKey}
                  </span>
                  <span className="ml-auto text-xs text-muted-foreground tabular-nums">{formatDateTime(event.occurredAt)}</span>
                </p>
                <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                  {auditChanges(event)
                    .slice(0, 12)
                    .map((change) => (
                      <li key={change.field} className="break-words">
                        <span className="font-medium text-foreground">{change.field}:</span> {change.from} → {change.to}
                      </li>
                    ))}
                </ul>
              </li>
            ))}
          </ol>
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>
              {offset + 1}–{offset + data.events.length} of {data.total.toLocaleString("en-US")}
            </span>
            <span className="flex gap-2">
              <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                Newer
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={offset + data.events.length >= data.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Older
              </Button>
            </span>
          </div>
        </>
      )}
    </div>
  );
}
