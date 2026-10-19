"use client";

import { AlertTriangle, GitBranch } from "lucide-react";
import { useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { usePermissions } from "@/features/auth/use-session";

import { describeNotificationsError, updateWorkflow, type RecipientRuleInput, type Workflow } from "./api";
import { Notice, Section, inputClass } from "./notifications-shared";
import { useNotificationsMutation, useTemplates, useWorkflows } from "./use-notifications";

export function WorkflowsPage({ title, description }: { title: string; description?: string }) {
  const { has } = usePermissions();
  const canManage = has("notifications.workflows.manage");
  const workflows = useWorkflows();
  const templates = useTemplates();
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const rows = workflows.data ?? [];
  const selected = rows.find((w) => w.id === selectedId) ?? rows[0] ?? null;

  useEffect(() => {
    if (selectedId === null && rows[0]) setSelectedId(rows[0].id);
  }, [rows, selectedId]);

  const publishedTemplateIds = new Set(
    (templates.data ?? []).filter((t) => t.currentPublishedRevisionId != null).map((t) => t.id),
  );

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Administration" title={title} description={description} />

      {workflows.isError ? (
        <EmptyState
          icon={AlertTriangle}
          title="Workflows could not be loaded"
          description={describeNotificationsError(workflows.error)}
        />
      ) : workflows.isPending ? (
        <p className="py-6 text-sm text-muted-foreground">Loading workflows…</p>
      ) : rows.length === 0 ? (
        <EmptyState icon={GitBranch} title="No workflows" description="Seeded workflows appear here after migration." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
          <Section title="Workflows">
            <ul className="space-y-1">
              {rows.map((workflow) => (
                <li key={workflow.id}>
                  <button
                    type="button"
                    className={`w-full rounded-md px-2 py-1.5 text-left text-sm ${
                      selected?.id === workflow.id ? "bg-muted font-medium" : "hover:bg-muted/60"
                    }`}
                    onClick={() => setSelectedId(workflow.id)}
                  >
                    <span className="flex items-center gap-2">
                      <span>{workflow.displayName}</span>
                      <StatusBadge tone={workflow.enabled ? "success" : "neutral"}>
                        {workflow.enabled ? "On" : "Off"}
                      </StatusBadge>
                    </span>
                    <span className="block font-mono text-xs text-muted-foreground">{workflow.eventTypeCode}</span>
                  </button>
                </li>
              ))}
            </ul>
          </Section>

          {selected && (
            <WorkflowEditor
              workflow={selected}
              canManage={canManage}
              hasPublishedTemplate={publishedTemplateIds.has(selected.templateId)}
            />
          )}
        </div>
      )}
    </div>
  );
}

function WorkflowEditor({
  workflow,
  canManage,
  hasPublishedTemplate,
}: {
  workflow: Workflow;
  canManage: boolean;
  hasPublishedTemplate: boolean;
}) {
  const [displayName, setDisplayName] = useState(workflow.displayName);
  const [enabled, setEnabled] = useState(workflow.enabled);
  const [rules, setRules] = useState<RecipientRuleInput[]>(
    workflow.recipientRules.map((r) => ({
      recipientType: r.recipientType,
      strategyCode: r.strategyCode,
      strategyConfigJson: r.strategyConfigJson,
      active: r.active,
      displayOrder: r.displayOrder,
    })),
  );
  const [message, setMessage] = useState<{ tone: "success" | "error" | "warning"; text: string } | null>(null);

  useEffect(() => {
    setDisplayName(workflow.displayName);
    setEnabled(workflow.enabled);
    setRules(
      workflow.recipientRules.map((r) => ({
        recipientType: r.recipientType,
        strategyCode: r.strategyCode,
        strategyConfigJson: r.strategyConfigJson,
        active: r.active,
        displayOrder: r.displayOrder,
      })),
    );
    setMessage(null);
  }, [workflow]);

  const save = useNotificationsMutation(() =>
    updateWorkflow(workflow.id, { displayName, enabled, recipientRules: rules }),
  );

  return (
    <Section
      title={workflow.displayName}
      description={`${workflow.code} · template ${workflow.templateCode}`}
      actions={
        <StatusBadge tone={workflow.enabled ? "success" : "neutral"}>
          {workflow.enabled ? "Enabled" : "Disabled"}
        </StatusBadge>
      }
    >
      <div className="space-y-3">
        {message && <Notice tone={message.tone}>{message.text}</Notice>}
        {!hasPublishedTemplate && (
          <Notice tone="warning">
            Enable is blocked until template {workflow.templateCode} has a published revision.
          </Notice>
        )}

        <label className="block space-y-1">
          <span className="text-sm font-medium">Display name</span>
          <input
            className={inputClass}
            value={displayName}
            disabled={!canManage}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </label>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={enabled}
            disabled={!canManage || (!hasPublishedTemplate && !workflow.enabled)}
            onChange={(e) => {
              if (e.target.checked && !hasPublishedTemplate) {
                setMessage({ tone: "warning", text: "Publish a template revision before enabling this workflow." });
                return;
              }
              setEnabled(e.target.checked);
            }}
          />
          Enabled (immediate delivery when event is published)
        </label>

        <p className="text-xs text-muted-foreground">
          Event: <span className="font-mono">{workflow.eventTypeCode}</span> · Timing: {workflow.deliveryTimingCode}
        </p>

        <div className="space-y-2">
          <p className="text-sm font-medium">Recipient rules</p>
          {rules.length === 0 ? (
            <p className="text-sm text-muted-foreground">No recipient rules configured.</p>
          ) : (
            <ul className="space-y-2">
              {rules.map((rule, index) => (
                <li key={`${rule.recipientType}-${rule.strategyCode}-${index}`} className="rounded-md border p-3">
                  <div className="grid gap-2 sm:grid-cols-3">
                    <label className="space-y-1 text-sm">
                      <span className="text-xs text-muted-foreground">Type</span>
                      <select
                        className={inputClass}
                        value={rule.recipientType}
                        disabled={!canManage}
                        onChange={(e) => {
                          const next = [...rules];
                          next[index] = { ...rule, recipientType: e.target.value as RecipientRuleInput["recipientType"] };
                          setRules(next);
                        }}
                      >
                        <option value="to">TO</option>
                        <option value="cc">CC</option>
                        <option value="bcc">BCC</option>
                      </select>
                    </label>
                    <label className="space-y-1 text-sm sm:col-span-2">
                      <span className="text-xs text-muted-foreground">Strategy</span>
                      <input
                        className={inputClass}
                        value={rule.strategyCode}
                        disabled={!canManage}
                        onChange={(e) => {
                          const next = [...rules];
                          next[index] = { ...rule, strategyCode: e.target.value };
                          setRules(next);
                        }}
                      />
                    </label>
                  </div>
                  <label className="mt-2 flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="size-4"
                      checked={rule.active !== false}
                      disabled={!canManage}
                      onChange={(e) => {
                        const next = [...rules];
                        next[index] = { ...rule, active: e.target.checked };
                        setRules(next);
                      }}
                    />
                    Active
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>

        {canManage && (
          <Button
            disabled={save.isPending}
            onClick={() =>
              save.mutate(undefined, {
                onSuccess: () => setMessage({ tone: "success", text: "Workflow saved." }),
                onError: (error) => setMessage({ tone: "error", text: describeNotificationsError(error) }),
              })
            }
          >
            Save workflow
          </Button>
        )}
      </div>
    </Section>
  );
}
