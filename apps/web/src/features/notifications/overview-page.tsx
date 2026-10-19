"use client";

import { AlertTriangle, Mail } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";

import { describeNotificationsError } from "./api";
import { formatDateTime, Notice, Section } from "./notifications-shared";
import { useOverview } from "./use-notifications";

export function OverviewPage({ title, description }: { title: string; description?: string }) {
  const overview = useOverview(7);

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Administration" title={title} description={description} />

      {overview.isError ? (
        <EmptyState
          icon={AlertTriangle}
          title="Overview could not be loaded"
          description={describeNotificationsError(overview.error)}
        />
      ) : overview.isPending ? (
        <p className="py-6 text-sm text-muted-foreground">Loading email overview…</p>
      ) : (
        <>
          {overview.data.warnings.length > 0 && (
            <div className="space-y-2">
              {overview.data.warnings.map((warning) => (
                <Notice key={warning} tone="warning">
                  {warning}
                </Notice>
              ))}
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Provider" value={overview.data.provider || "none"} />
            <Stat label="API key" value={overview.data.apiKeyConfigured ? "Configured" : "Missing"} />
            <Stat label="Delivery mode" value={overview.data.deliveryMode} />
            <Stat label="Email enabled" value={overview.data.emailEnabled ? "Yes" : "No"} />
            <Stat label="Emergency pause" value={overview.data.emergencyPause ? "On" : "Off"} />
            <Stat label="Pending outbox" value={String(overview.data.pendingOutbox)} />
            <Stat label="Accepted (7d)" value={String(overview.data.acceptedCount)} />
            <Stat label="Failed (7d)" value={String(overview.data.failedCount)} />
          </div>

          <Section title="Recent deliveries" description="Latest emails queued in the last 7 days.">
            {overview.data.recentDeliveries.length === 0 ? (
              <EmptyState
                icon={Mail}
                title="No deliveries yet"
                description="When workflows send email, recent activity appears here."
              />
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
                    <th className="px-2 py-2 font-semibold">Subject</th>
                    <th className="px-2 py-2 font-semibold">Status</th>
                    <th className="px-2 py-2 font-semibold">Queued</th>
                    <th className="px-2 py-2 font-semibold">Workflow</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.data.recentDeliveries.map((row) => (
                    <tr key={row.id} className="border-b last:border-0">
                      <td className="px-2 py-2">
                        {row.renderedSubject}
                        {row.isTest && (
                          <StatusBadge tone="warning" className="ml-2">
                            TEST
                          </StatusBadge>
                        )}
                      </td>
                      <td className="px-2 py-2">
                        <StatusBadge tone={statusTone(row.status)}>{row.status}</StatusBadge>
                      </td>
                      <td className="px-2 py-2 text-muted-foreground">{formatDateTime(row.queuedAt)}</td>
                      <td className="px-2 py-2 font-mono text-xs">{row.workflowCode ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border p-3">
      <p className="text-xs tracking-wide text-muted-foreground uppercase">{label}</p>
      <p className="mt-1 text-sm font-semibold">{value}</p>
    </div>
  );
}

function statusTone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (status === "accepted" || status === "delivered") return "success";
  if (status === "failed" || status === "bounced") return "danger";
  if (status === "queued" || status === "sending") return "warning";
  return "neutral";
}
