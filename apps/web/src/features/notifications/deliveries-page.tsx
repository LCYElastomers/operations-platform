"use client";

import { AlertTriangle, Inbox } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { FilterBar, FilterInput, FilterSelect } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { usePermissions } from "@/features/auth/use-session";

import { describeNotificationsError, retryDelivery } from "./api";
import { Notice, Section, formatDateTime } from "./notifications-shared";
import { useDeliveries, useDelivery, useNotificationsMutation } from "./use-notifications";

export function DeliveriesPage({ title, description }: { title: string; description?: string }) {
  const { has } = usePermissions();
  const canRetry = has("notifications.delivery.retry");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  const query = {
    status: status || undefined,
    search: search.trim() || undefined,
    limit: 50,
    offset: 0,
  };
  const deliveries = useDeliveries(query);

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Administration" title={title} description={description} />

      <FilterBar>
        <FilterInput
          label="Search"
          type="search"
          placeholder="Subject or reference"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <FilterSelect
          label="Status"
          options={[
            { value: "queued", label: "Queued" },
            { value: "sending", label: "Sending" },
            { value: "accepted", label: "Accepted" },
            { value: "failed", label: "Failed" },
            { value: "cancelled", label: "Cancelled" },
          ]}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        />
      </FilterBar>

      {deliveries.isError ? (
        <EmptyState
          icon={AlertTriangle}
          title="Deliveries could not be loaded"
          description={describeNotificationsError(deliveries.error)}
        />
      ) : deliveries.isPending ? (
        <p className="py-6 text-sm text-muted-foreground">Loading deliveries…</p>
      ) : (deliveries.data?.deliveries.length ?? 0) === 0 ? (
        <EmptyState icon={Inbox} title="No deliveries match" description="Queued and accepted emails appear here." />
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs tracking-wide text-muted-foreground uppercase">
              <th className="h-10 px-3 font-semibold">Subject</th>
              <th className="h-10 px-3 font-semibold">Status</th>
              <th className="h-10 px-3 font-semibold">Mode</th>
              <th className="h-10 px-3 font-semibold">Event</th>
              <th className="h-10 px-3 font-semibold">Queued</th>
            </tr>
          </thead>
          <tbody>
            {deliveries.data!.deliveries.map((row) => (
              <tr
                key={row.id}
                className="cursor-pointer border-b last:border-0 hover:bg-muted/40"
                onClick={() => setOpenId(row.id)}
              >
                <td className="px-3 py-2.5">
                  {row.renderedSubject}
                  {row.isTest && (
                    <StatusBadge tone="warning" className="ml-2">
                      TEST
                    </StatusBadge>
                  )}
                </td>
                <td className="px-3 py-2.5">
                  <StatusBadge tone={statusTone(row.status)}>{row.status}</StatusBadge>
                </td>
                <td className="px-3 py-2.5 font-mono text-xs">{row.deliveryMode}</td>
                <td className="px-3 py-2.5 font-mono text-xs">{row.eventTypeCode ?? "—"}</td>
                <td className="px-3 py-2.5 text-muted-foreground">{formatDateTime(row.queuedAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <DeliveryDialog deliveryId={openId} canRetry={canRetry} onClose={() => setOpenId(null)} />
    </div>
  );
}

function DeliveryDialog({
  deliveryId,
  canRetry,
  onClose,
}: {
  deliveryId: string | null;
  canRetry: boolean;
  onClose: () => void;
}) {
  const detail = useDelivery(deliveryId);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const retry = useNotificationsMutation(() => retryDelivery(deliveryId!));

  return (
    <Dialog open={deliveryId !== null} onClose={onClose} title="Delivery detail" className="max-w-3xl">
      {detail.isPending && <p className="text-sm text-muted-foreground">Loading…</p>}
      {detail.isError && <Notice tone="error">{describeNotificationsError(detail.error)}</Notice>}
      {detail.data && (
        <div className="space-y-4">
          {message && <Notice tone={message.tone}>{message.text}</Notice>}
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone={statusTone(detail.data.status)}>{detail.data.status}</StatusBadge>
            <span className="font-mono text-xs text-muted-foreground">{detail.data.id}</span>
            {detail.data.isTest && <StatusBadge tone="warning">TEST</StatusBadge>}
            {canRetry && (detail.data.status === "failed" || detail.data.status === "queued") && (
              <Button
                size="sm"
                disabled={retry.isPending}
                onClick={() =>
                  retry.mutate(undefined, {
                    onSuccess: () => setMessage({ tone: "success", text: "Retry queued." }),
                    onError: (error) => setMessage({ tone: "error", text: describeNotificationsError(error) }),
                  })
                }
              >
                Retry
              </Button>
            )}
          </div>

          <dl className="grid gap-2 text-sm sm:grid-cols-2">
            <Field label="Subject" value={detail.data.renderedSubject} />
            <Field label="Mode" value={detail.data.deliveryMode} />
            <Field label="Event" value={detail.data.eventTypeCode ?? "—"} />
            <Field label="Workflow" value={detail.data.workflowCode ?? "—"} />
            <Field label="Entity" value={detail.data.entityReference ?? detail.data.entityId ?? "—"} />
            <Field label="Provider message" value={detail.data.providerMessageId ?? "—"} />
            <Field label="Intended TO" value={formatAddrs(detail.data.intendedToJson)} />
            <Field label="Actual TO" value={formatAddrs(detail.data.actualToJson)} />
          </dl>

          <Section title="Rendered HTML">
            <iframe
              title="Rendered email"
              className="h-56 w-full rounded-md border bg-white"
              sandbox=""
              srcDoc={detail.data.renderedHtml}
            />
          </Section>

          <Section title="Attempt history">
            {detail.data.attempts.length === 0 ? (
              <p className="text-sm text-muted-foreground">No attempts recorded.</p>
            ) : (
              <ul className="space-y-2 text-sm">
                {detail.data.attempts.map((attempt) => (
                  <li key={attempt.attemptNumber} className="rounded-md border px-3 py-2">
                    <div className="flex flex-wrap gap-2">
                      <span className="font-medium">#{attempt.attemptNumber}</span>
                      <StatusBadge tone={statusTone(attempt.status)}>{attempt.status}</StatusBadge>
                      <span className="text-muted-foreground">{formatDateTime(attempt.startedAt)}</span>
                    </div>
                    {attempt.errorMessage && <p className="mt-1 text-destructive">{attempt.errorMessage}</p>}
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>
      )}
    </Dialog>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs tracking-wide text-muted-foreground uppercase">{label}</dt>
      <dd className="mt-0.5 break-all">{value}</dd>
    </div>
  );
}

function formatAddrs(value: unknown[]): string {
  if (!value?.length) return "—";
  return value
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "email" in item) return String((item as { email: string }).email);
      return JSON.stringify(item);
    })
    .join(", ");
}

function statusTone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (status === "accepted" || status === "delivered") return "success";
  if (status === "failed" || status === "bounced") return "danger";
  if (status === "queued" || status === "sending") return "warning";
  return "neutral";
}
