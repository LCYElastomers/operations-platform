import { ApiError, apiGet, apiSend } from "@/lib/api-client";

const BASE = "/api/v1/admin/notifications";

export type Overview = {
  provider: string;
  apiKeyConfigured: boolean;
  deliveryMode: string;
  emailEnabled: boolean;
  emergencyPause: boolean;
  pendingOutbox: number;
  acceptedCount: number;
  failedCount: number;
  warnings: string[];
  recentDeliveries: RecentDelivery[];
};

export type RecentDelivery = {
  id: string;
  status: string;
  renderedSubject: string;
  queuedAt: string;
  isTest: boolean;
  workflowCode: string | null;
};

export type EventType = {
  code: string;
  displayName: string;
  moduleCode: string;
  description: string;
  active: boolean;
  variables: string[];
};

export type TemplateRevision = {
  id: number;
  templateId: number;
  revisionNumber: number;
  status: "draft" | "published" | "retired";
  subjectTemplate: string;
  htmlTemplate: string;
  textTemplate: string;
  variableSchemaJson: Record<string, unknown>;
  createdAt: string;
  createdBy: string;
  publishedAt: string | null;
  publishedBy: string | null;
};

export type Template = {
  id: number;
  code: string;
  displayName: string;
  description: string;
  moduleCode: string;
  active: boolean;
  currentPublishedRevisionId: number | null;
  draftRevision: TemplateRevision | null;
  publishedRevision: TemplateRevision | null;
  createdAt: string;
  updatedAt: string;
};

export type ValidateResult = {
  valid: boolean;
  unresolvedVariables: string[];
  unsupportedVariables: string[];
  unsafeContentFindings: string[];
  missingRequired: string[];
};

export type PreviewResult = { subject: string; html: string; text: string };

export type RecipientRule = {
  id: number;
  recipientType: "to" | "cc" | "bcc";
  strategyCode: string;
  strategyConfigJson: Record<string, unknown>;
  active: boolean;
  displayOrder: number;
};

export type RecipientRuleInput = {
  recipientType: "to" | "cc" | "bcc";
  strategyCode: string;
  strategyConfigJson?: Record<string, unknown>;
  active?: boolean;
  displayOrder?: number;
};

export type Workflow = {
  id: number;
  code: string;
  displayName: string;
  eventTypeCode: string;
  templateId: number;
  templateCode: string;
  enabled: boolean;
  deliveryTimingCode: "immediate" | "scheduled";
  scheduleConfigJson: Record<string, unknown> | null;
  recipientRules: RecipientRule[];
  createdAt: string;
  updatedAt: string;
};

export type DeliveryListItem = {
  id: string;
  status: string;
  deliveryMode: string;
  renderedSubject: string;
  queuedAt: string;
  isTest: boolean;
  eventTypeCode: string | null;
  workflowCode: string | null;
  entityType: string | null;
  entityId: string | null;
  entityReference: string | null;
};

export type DeliveryAttempt = {
  attemptNumber: number;
  startedAt: string;
  completedAt: string | null;
  status: string;
  providerHttpStatus: number | null;
  providerErrorCode: string | null;
  errorMessage: string | null;
  retryable: boolean;
};

export type DeliveryDetail = {
  id: string;
  status: string;
  deliveryMode: string;
  renderedSubject: string;
  renderedHtml: string;
  renderedText: string;
  queuedAt: string;
  attemptedAt: string | null;
  acceptedAt: string | null;
  failedAt: string | null;
  isTest: boolean;
  outboxId: string | null;
  notificationEventId: string | null;
  workflowId: number | null;
  workflowCode: string | null;
  eventTypeCode: string | null;
  entityType: string | null;
  entityId: string | null;
  entityReference: string | null;
  intendedToJson: unknown[];
  intendedCcJson: unknown[];
  intendedBccJson: unknown[];
  actualToJson: unknown[];
  actualCcJson: unknown[];
  actualBccJson: unknown[];
  providerCode: string | null;
  providerMessageId: string | null;
  attempts: DeliveryAttempt[];
};

export type DeliveryQuery = {
  status?: string;
  fromDate?: string;
  toDate?: string;
  eventTypeCode?: string;
  moduleCode?: string;
  workflowId?: number;
  search?: string;
  limit?: number;
  offset?: number;
};

export type Settings = {
  provider: string;
  apiKeyConfigured: boolean;
  emailEnabled: boolean;
  deliveryMode: string;
  emailFromAddress: string | null;
  emailFromName: string | null;
  emailReplyTo: string | null;
  emailRedirectTo: string | null;
  emergencyPause: boolean;
};

export type PsmActionPickerItem = {
  id: number;
  reference: string;
  title: string;
  ownerName: string | null;
};

export type TestPreview = {
  subject: string;
  html: string;
  text: string;
  intendedTo: string[];
  deliveryMode: string;
};

export type TestSendResult = {
  deliveryId: string;
  status: string;
  deliveryMode: string;
  renderedSubject: string;
};

export const notificationKeys = {
  all: ["notifications"] as const,
  overview: (days: number) => [...notificationKeys.all, "overview", days] as const,
  eventTypes: () => [...notificationKeys.all, "event-types"] as const,
  templates: () => [...notificationKeys.all, "templates"] as const,
  template: (id: number) => [...notificationKeys.templates(), id] as const,
  workflows: () => [...notificationKeys.all, "workflows"] as const,
  workflow: (id: number) => [...notificationKeys.workflows(), id] as const,
  deliveries: (query: DeliveryQuery) => [...notificationKeys.all, "deliveries", query] as const,
  delivery: (id: string) => [...notificationKeys.all, "delivery", id] as const,
  settings: () => [...notificationKeys.all, "settings"] as const,
  psmActions: () => [...notificationKeys.all, "psm-actions"] as const,
};

export const fetchOverview = (days = 7, signal?: AbortSignal) =>
  apiGet<Overview>(`${BASE}/overview?days=${days}`, { signal });

export const fetchEventTypes = (signal?: AbortSignal) =>
  apiGet<EventType[]>(`${BASE}/event-types`, { signal });

export const fetchTemplates = (signal?: AbortSignal) =>
  apiGet<{ templates: Template[] }>(`${BASE}/templates`, { signal }).then((b) => b.templates);

export const fetchTemplate = (id: number, signal?: AbortSignal) =>
  apiGet<Template>(`${BASE}/templates/${id}`, { signal });

export const createDraft = (templateId: number) =>
  apiSend<TemplateRevision>("POST", `${BASE}/templates/${templateId}/draft`);

export const updateDraft = (
  templateId: number,
  revisionId: number,
  body: { subjectTemplate?: string; htmlTemplate?: string; textTemplate?: string },
) => apiSend<TemplateRevision>("PATCH", `${BASE}/templates/${templateId}/revisions/${revisionId}`, body);

export const validateRevision = (templateId: number, revisionId: number, eventTypeCode: string) =>
  apiSend<ValidateResult>("POST", `${BASE}/templates/${templateId}/revisions/${revisionId}/validate`, {
    eventTypeCode,
  });

export const previewRevision = (
  templateId: number,
  revisionId: number,
  body: { eventTypeCode: string; context?: Record<string, unknown>; psmActionId?: number },
) => apiSend<PreviewResult>("POST", `${BASE}/templates/${templateId}/revisions/${revisionId}/preview`, body);

export const publishRevision = (templateId: number, revisionId: number, eventTypeCode: string) =>
  apiSend<Template>("POST", `${BASE}/templates/${templateId}/revisions/${revisionId}/publish`, {
    eventTypeCode,
  });

export const fetchWorkflows = (signal?: AbortSignal) =>
  apiGet<{ workflows: Workflow[] }>(`${BASE}/workflows`, { signal }).then((b) => b.workflows);

export const fetchWorkflow = (id: number, signal?: AbortSignal) =>
  apiGet<Workflow>(`${BASE}/workflows/${id}`, { signal });

export const updateWorkflow = (
  id: number,
  body: {
    displayName?: string;
    enabled?: boolean;
    deliveryTimingCode?: "immediate" | "scheduled";
    scheduleConfigJson?: Record<string, unknown> | null;
    recipientRules?: RecipientRuleInput[];
  },
) => apiSend<Workflow>("PATCH", `${BASE}/workflows/${id}`, body);

export function fetchDeliveries(query: DeliveryQuery, signal?: AbortSignal) {
  const params = new URLSearchParams();
  if (query.status) params.set("status", query.status);
  if (query.fromDate) params.set("fromDate", query.fromDate);
  if (query.toDate) params.set("toDate", query.toDate);
  if (query.eventTypeCode) params.set("eventTypeCode", query.eventTypeCode);
  if (query.moduleCode) params.set("moduleCode", query.moduleCode);
  if (query.workflowId != null) params.set("workflowId", String(query.workflowId));
  if (query.search) params.set("search", query.search);
  params.set("limit", String(query.limit ?? 50));
  params.set("offset", String(query.offset ?? 0));
  return apiGet<{ deliveries: DeliveryListItem[]; total: number }>(`${BASE}/deliveries?${params}`, { signal });
}

export const fetchDelivery = (id: string, signal?: AbortSignal) =>
  apiGet<DeliveryDetail>(`${BASE}/deliveries/${encodeURIComponent(id)}`, { signal });

export const retryDelivery = (id: string) =>
  apiSend<{ outboxId: string; status: string }>("POST", `${BASE}/deliveries/${encodeURIComponent(id)}/retry`);

export const fetchSettings = (signal?: AbortSignal) => apiGet<Settings>(`${BASE}/settings`, { signal });

export const updateSettings = (body: { emergencyPause?: boolean }) =>
  apiSend<Settings>("PATCH", `${BASE}/settings`, body);

export const fetchPsmActionsForTest = (signal?: AbortSignal) =>
  apiGet<{ actions: PsmActionPickerItem[] }>(`${BASE}/test/psm-actions`, { signal }).then((b) => b.actions);

export const testPreview = (body: {
  templateId?: number;
  workflowId?: number;
  templateRevisionId?: number;
  eventTypeCode?: string;
  context?: Record<string, unknown>;
  psmActionId?: number;
  toEmail?: string;
}) => apiSend<TestPreview>("POST", `${BASE}/test/preview`, body);

export const testSend = (body: {
  templateId?: number;
  workflowId?: number;
  templateRevisionId?: number;
  eventTypeCode?: string;
  context?: Record<string, unknown>;
  psmActionId?: number;
  toEmail: string;
}) => apiSend<TestSendResult>("POST", `${BASE}/test/send`, body);

export function describeNotificationsError(error: unknown): string {
  if (!(error instanceof ApiError)) return "The API could not be reached.";
  if (error.detail?.message) return error.detail.message;
  switch (error.status) {
    case 401:
      return "Your session has ended. Sign in again to continue.";
    case 403:
      return "You do not have permission for this action.";
    case 404:
      return "This record no longer exists.";
    case 422:
      return "The request could not be processed.";
    case 503:
      return "Email management is unavailable because the database could not be reached.";
    default:
      return "The request failed. Try again.";
  }
}
