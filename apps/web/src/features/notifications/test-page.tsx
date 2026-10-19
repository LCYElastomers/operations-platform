"use client";

import { AlertTriangle, FlaskConical } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import { usePermissions } from "@/features/auth/use-session";

import { describeNotificationsError, testPreview, testSend, type TestPreview, type TestSendResult } from "./api";
import { Notice, Section, inputClass } from "./notifications-shared";
import {
  useNotificationsMutation,
  usePsmActionsForTest,
  useTemplates,
  useWorkflows,
} from "./use-notifications";

export function TestPage({ title, description }: { title: string; description?: string }) {
  const { has } = usePermissions();
  const canSend = has("notifications.test.send");
  const templates = useTemplates();
  const workflows = useWorkflows();
  const actions = usePsmActionsForTest();

  const [source, setSource] = useState<"template" | "workflow">("workflow");
  const [templateId, setTemplateId] = useState<number | "">("");
  const [workflowId, setWorkflowId] = useState<number | "">("");
  const [psmActionId, setPsmActionId] = useState<number | "">("");
  const [toEmail, setToEmail] = useState("");
  const [preview, setPreview] = useState<TestPreview | null>(null);
  const [sendResult, setSendResult] = useState<TestSendResult | null>(null);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  const previewMut = useNotificationsMutation(() =>
    testPreview({
      templateId: source === "template" && templateId !== "" ? Number(templateId) : undefined,
      workflowId: source === "workflow" && workflowId !== "" ? Number(workflowId) : undefined,
      psmActionId: psmActionId === "" ? undefined : Number(psmActionId),
      toEmail: toEmail || undefined,
    }),
  );
  const sendMut = useNotificationsMutation(() =>
    testSend({
      templateId: source === "template" && templateId !== "" ? Number(templateId) : undefined,
      workflowId: source === "workflow" && workflowId !== "" ? Number(workflowId) : undefined,
      psmActionId: psmActionId === "" ? undefined : Number(psmActionId),
      toEmail,
    }),
  );

  if (!canSend) {
    return (
      <div className="space-y-5">
        <PageHeader eyebrow="Administration" title={title} description={description} />
        <EmptyState
          icon={AlertTriangle}
          title="Permission required"
          description="You need notifications.test.send to use the Test Center."
        />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Administration" title={title} description={description} />

      {(templates.isError || workflows.isError || actions.isError) && (
        <EmptyState
          icon={AlertTriangle}
          title="Test Center could not be loaded"
          description={describeNotificationsError(templates.error ?? workflows.error ?? actions.error)}
        />
      )}

      <Section
        title="Send a TEST email"
        description="Messages are labeled TEST. Use redirect mode in non-production environments."
      >
        <div className="space-y-3">
          {message && <Notice tone={message.tone}>{message.text}</Notice>}

          <div className="flex flex-wrap gap-3 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="source"
                checked={source === "workflow"}
                onChange={() => setSource("workflow")}
              />
              Workflow
            </label>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="source"
                checked={source === "template"}
                onChange={() => setSource("template")}
              />
              Template
            </label>
          </div>

          {source === "workflow" ? (
            <label className="block space-y-1">
              <span className="text-sm font-medium">Workflow</span>
              <select
                className={inputClass}
                value={workflowId === "" ? "" : String(workflowId)}
                onChange={(e) => setWorkflowId(e.target.value ? Number(e.target.value) : "")}
              >
                <option value="">Select workflow…</option>
                {(workflows.data ?? []).map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.displayName} ({w.code})
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <label className="block space-y-1">
              <span className="text-sm font-medium">Template</span>
              <select
                className={inputClass}
                value={templateId === "" ? "" : String(templateId)}
                onChange={(e) => setTemplateId(e.target.value ? Number(e.target.value) : "")}
              >
                <option value="">Select template…</option>
                {(templates.data ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.displayName} ({t.code})
                  </option>
                ))}
              </select>
            </label>
          )}

          <label className="block space-y-1">
            <span className="text-sm font-medium">PSM action context</span>
            <select
              className={inputClass}
              value={psmActionId === "" ? "" : String(psmActionId)}
              onChange={(e) => setPsmActionId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">Sample context (no record)</option>
              {(actions.data ?? []).map((action) => (
                <option key={action.id} value={action.id}>
                  {action.reference} — {action.title}
                </option>
              ))}
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-sm font-medium">Send to</span>
            <input
              className={inputClass}
              type="email"
              value={toEmail}
              placeholder="you@example.com"
              onChange={(e) => setToEmail(e.target.value)}
            />
          </label>

          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              disabled={previewMut.isPending}
              onClick={() =>
                previewMut.mutate(undefined, {
                  onSuccess: (result) => {
                    setPreview(result);
                    setMessage({ tone: "success", text: "Preview ready." });
                  },
                  onError: (error) => setMessage({ tone: "error", text: describeNotificationsError(error) }),
                })
              }
            >
              Preview
            </Button>
            <Button
              disabled={sendMut.isPending || !toEmail.trim()}
              onClick={() =>
                sendMut.mutate(undefined, {
                  onSuccess: (result) => {
                    setSendResult(result);
                    setMessage({ tone: "success", text: `TEST send queued (${result.status}).` });
                  },
                  onError: (error) => setMessage({ tone: "error", text: describeNotificationsError(error) }),
                })
              }
            >
              <FlaskConical />
              Send TEST email
            </Button>
          </div>
        </div>
      </Section>

      {preview && (
        <Section title="Preview" description={`Mode: ${preview.deliveryMode} · TO: ${preview.intendedTo.join(", ") || "—"}`}>
          <p className="mb-2 text-sm font-medium">{preview.subject}</p>
          <iframe title="Test preview" className="h-64 w-full rounded-md border bg-white" sandbox="" srcDoc={preview.html} />
        </Section>
      )}

      {sendResult && (
        <Notice tone="success">
          Delivery {sendResult.deliveryId} — {sendResult.renderedSubject} ({sendResult.deliveryMode})
        </Notice>
      )}
    </div>
  );
}
