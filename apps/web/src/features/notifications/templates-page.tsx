"use client";

import { AlertTriangle, FileText } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { usePermissions } from "@/features/auth/use-session";

import {
  createDraft,
  describeNotificationsError,
  previewRevision,
  publishRevision,
  updateDraft,
  validateRevision,
  type PreviewResult,
  type Template,
  type ValidateResult,
} from "./api";
import { Notice, Section, inputClass, insertAtCursor, textareaClass } from "./notifications-shared";
import { useEventTypes, useNotificationsMutation, useTemplates } from "./use-notifications";

export function TemplatesPage({ title, description }: { title: string; description?: string }) {
  const { has } = usePermissions();
  const canManage = has("notifications.templates.manage");
  const templates = useTemplates();
  const eventTypes = useEventTypes();
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const rows = templates.data ?? [];
  const selected = rows.find((t) => t.id === selectedId) ?? rows[0] ?? null;

  useEffect(() => {
    if (selectedId === null && rows[0]) setSelectedId(rows[0].id);
  }, [rows, selectedId]);

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Administration" title={title} description={description} />

      {templates.isError ? (
        <EmptyState
          icon={AlertTriangle}
          title="Templates could not be loaded"
          description={describeNotificationsError(templates.error)}
        />
      ) : templates.isPending ? (
        <p className="py-6 text-sm text-muted-foreground">Loading templates…</p>
      ) : rows.length === 0 ? (
        <EmptyState icon={FileText} title="No templates" description="Seeded templates appear here after migration." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
          <Section title="Templates">
            <ul className="space-y-1">
              {rows.map((template) => (
                <li key={template.id}>
                  <button
                    type="button"
                    className={`w-full rounded-md px-2 py-1.5 text-left text-sm ${
                      selected?.id === template.id ? "bg-muted font-medium" : "hover:bg-muted/60"
                    }`}
                    onClick={() => setSelectedId(template.id)}
                  >
                    <span className="block">{template.displayName}</span>
                    <span className="block font-mono text-xs text-muted-foreground">{template.code}</span>
                  </button>
                </li>
              ))}
            </ul>
          </Section>

          {selected && (
            <TemplateEditor
              template={selected}
              canManage={canManage}
              eventTypeCodes={(eventTypes.data ?? []).map((e) => e.code)}
              variables={
                (eventTypes.data ?? []).find((e) => e.moduleCode === selected.moduleCode)?.variables ??
                Object.keys(selected.draftRevision?.variableSchemaJson ?? selected.publishedRevision?.variableSchemaJson ?? {})
              }
            />
          )}
        </div>
      )}
    </div>
  );
}

function TemplateEditor({
  template,
  canManage,
  eventTypeCodes,
  variables,
}: {
  template: Template;
  canManage: boolean;
  eventTypeCodes: string[];
  variables: string[];
}) {
  const draft = template.draftRevision;
  const published = template.publishedRevision;
  const defaultEvent =
    eventTypeCodes.find((code) => code.startsWith(template.moduleCode.replace(/_/g, "."))) ??
    eventTypeCodes[0] ??
    "";

  const [eventTypeCode, setEventTypeCode] = useState(defaultEvent);
  const [subject, setSubject] = useState(draft?.subjectTemplate ?? "");
  const [html, setHtml] = useState(draft?.htmlTemplate ?? "");
  const [text, setText] = useState(draft?.textTemplate ?? "");
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [validation, setValidation] = useState<ValidateResult | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const activeField = useRef<"subject" | "html" | "text">("html");
  const subjectRef = useRef<HTMLInputElement>(null);
  const htmlRef = useRef<HTMLTextAreaElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setSubject(draft?.subjectTemplate ?? "");
    setHtml(draft?.htmlTemplate ?? "");
    setText(draft?.textTemplate ?? "");
    setValidation(null);
    setPreview(null);
    setMessage(null);
    setEventTypeCode(defaultEvent);
  }, [template.id, draft?.id, draft?.subjectTemplate, draft?.htmlTemplate, draft?.textTemplate, defaultEvent]);

  const create = useNotificationsMutation(() => createDraft(template.id));
  const save = useNotificationsMutation(() =>
    updateDraft(template.id, draft!.id, {
      subjectTemplate: subject,
      htmlTemplate: html,
      textTemplate: text,
    }),
  );
  const validate = useNotificationsMutation(() => validateRevision(template.id, draft!.id, eventTypeCode));
  const previewMut = useNotificationsMutation(() =>
    previewRevision(template.id, draft!.id, { eventTypeCode }),
  );
  const publish = useNotificationsMutation(() => publishRevision(template.id, draft!.id, eventTypeCode));

  const variableList = useMemo(() => {
    const fromSchema = Object.keys(draft?.variableSchemaJson ?? published?.variableSchemaJson ?? {});
    return [...new Set([...variables, ...fromSchema])].sort();
  }, [variables, draft?.variableSchemaJson, published?.variableSchemaJson]);

  function insertVariable(name: string) {
    const token = `{{${name}}}`;
    const field = activeField.current;
    if (field === "subject") {
      const el = subjectRef.current;
      const start = el?.selectionStart ?? subject.length;
      const end = el?.selectionEnd ?? start;
      setSubject(insertAtCursor(subject, token, start, end));
    } else if (field === "html") {
      const el = htmlRef.current;
      const start = el?.selectionStart ?? html.length;
      const end = el?.selectionEnd ?? start;
      setHtml(insertAtCursor(html, token, start, end));
    } else {
      const el = textRef.current;
      const start = el?.selectionStart ?? text.length;
      const end = el?.selectionEnd ?? start;
      setText(insertAtCursor(text, token, start, end));
    }
  }

  return (
    <div className="space-y-4">
      <Section
        title={template.displayName}
        description={template.description || template.code}
        actions={
          <div className="flex flex-wrap gap-2">
            {published && <StatusBadge tone="success">Published r{published.revisionNumber}</StatusBadge>}
            {draft && <StatusBadge tone="warning">Draft r{draft.revisionNumber}</StatusBadge>}
            {!draft && canManage && (
              <Button
                size="sm"
                disabled={create.isPending}
                onClick={() =>
                  create.mutate(undefined, {
                    onSuccess: () => setMessage({ tone: "success", text: "Draft created from published revision." }),
                    onError: (error) => setMessage({ tone: "error", text: describeNotificationsError(error) }),
                  })
                }
              >
                Create draft
              </Button>
            )}
          </div>
        }
      >
        {message && <Notice tone={message.tone}>{message.text}</Notice>}

        {!draft ? (
          <p className="text-sm text-muted-foreground">
            {published
              ? "Create a draft to edit this template. Published content is read-only until a draft is created."
              : "No draft or published revision is available yet."}
          </p>
        ) : (
          <div className="space-y-3">
            <label className="block space-y-1">
              <span className="text-sm font-medium">Event type (for validate / publish)</span>
              <select
                className={inputClass}
                value={eventTypeCode}
                onChange={(e) => setEventTypeCode(e.target.value)}
                disabled={!canManage}
              >
                {eventTypeCodes.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
            </label>

            <label className="block space-y-1">
              <span className="text-sm font-medium">Subject</span>
              <input
                ref={subjectRef}
                className={inputClass}
                value={subject}
                disabled={!canManage}
                onFocus={() => {
                  activeField.current = "subject";
                }}
                onChange={(e) => setSubject(e.target.value)}
              />
            </label>

            <label className="block space-y-1">
              <span className="text-sm font-medium">HTML body</span>
              <textarea
                ref={htmlRef}
                className={textareaClass}
                value={html}
                disabled={!canManage}
                onFocus={() => {
                  activeField.current = "html";
                }}
                onChange={(e) => setHtml(e.target.value)}
              />
            </label>

            <label className="block space-y-1">
              <span className="text-sm font-medium">Text body</span>
              <textarea
                ref={textRef}
                className={textareaClass}
                value={text}
                disabled={!canManage}
                onFocus={() => {
                  activeField.current = "text";
                }}
                onChange={(e) => setText(e.target.value)}
              />
            </label>

            {variableList.length > 0 && (
              <div className="space-y-1">
                <p className="text-sm font-medium">Insert variable</p>
                <div className="flex flex-wrap gap-1.5">
                  {variableList.map((name) => (
                    <Button key={name} type="button" size="sm" variant="outline" disabled={!canManage} onClick={() => insertVariable(name)}>
                      {`{{${name}}}`}
                    </Button>
                  ))}
                </div>
              </div>
            )}

            {canManage && (
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={save.isPending}
                  onClick={() =>
                    save.mutate(undefined, {
                      onSuccess: () => setMessage({ tone: "success", text: "Draft saved." }),
                      onError: (error) => setMessage({ tone: "error", text: describeNotificationsError(error) }),
                    })
                  }
                >
                  Save draft
                </Button>
                <Button
                  variant="outline"
                  disabled={validate.isPending || !eventTypeCode}
                  onClick={() =>
                    validate.mutate(undefined, {
                      onSuccess: (result) => {
                        setValidation(result);
                        setMessage({
                          tone: result.valid ? "success" : "error",
                          text: result.valid ? "Template is valid." : "Template has validation issues.",
                        });
                      },
                      onError: (error) => setMessage({ tone: "error", text: describeNotificationsError(error) }),
                    })
                  }
                >
                  Validate
                </Button>
                <Button
                  variant="outline"
                  disabled={previewMut.isPending || !eventTypeCode}
                  onClick={() =>
                    previewMut.mutate(undefined, {
                      onSuccess: (result) => {
                        setPreview(result);
                        setMessage({ tone: "success", text: "Sanitized preview rendered." });
                      },
                      onError: (error) => setMessage({ tone: "error", text: describeNotificationsError(error) }),
                    })
                  }
                >
                  Preview
                </Button>
                <Button
                  disabled={publish.isPending || !eventTypeCode}
                  onClick={() =>
                    publish.mutate(undefined, {
                      onSuccess: () => setMessage({ tone: "success", text: "Revision published." }),
                      onError: (error) => setMessage({ tone: "error", text: describeNotificationsError(error) }),
                    })
                  }
                >
                  Publish
                </Button>
              </div>
            )}

            {validation && !validation.valid && (
              <Notice tone="error">
                {[
                  ...validation.unsupportedVariables.map((v) => `Unsupported: ${v}`),
                  ...validation.unresolvedVariables.map((v) => `Unresolved: ${v}`),
                  ...validation.unsafeContentFindings,
                  ...validation.missingRequired.map((v) => `Missing: ${v}`),
                ].join(" · ")}
              </Notice>
            )}

            {preview && (
              <Section title="Sanitized preview">
                <p className="mb-2 text-sm font-medium">{preview.subject}</p>
                <iframe
                  title="Email preview"
                  className="h-64 w-full rounded-md border bg-white"
                  sandbox=""
                  srcDoc={preview.html}
                />
                <pre className="mt-2 overflow-auto rounded-md border bg-muted/40 p-2 text-xs whitespace-pre-wrap">
                  {preview.text}
                </pre>
              </Section>
            )}
          </div>
        )}
      </Section>

      <Section title="Revision history">
        <ul className="space-y-2 text-sm">
          {published && (
            <li className="rounded-md border px-3 py-2">
              <StatusBadge tone="success">published</StatusBadge>{" "}
              <span className="font-mono text-xs">r{published.revisionNumber}</span>
              <span className="ml-2 text-muted-foreground">
                by {published.publishedBy ?? published.createdBy}
              </span>
            </li>
          )}
          {draft && (
            <li className="rounded-md border px-3 py-2">
              <StatusBadge tone="warning">draft</StatusBadge>{" "}
              <span className="font-mono text-xs">r{draft.revisionNumber}</span>
              <span className="ml-2 text-muted-foreground">by {draft.createdBy}</span>
            </li>
          )}
          {!published && !draft && <li className="text-muted-foreground">No revisions.</li>}
        </ul>
      </Section>
    </div>
  );
}
