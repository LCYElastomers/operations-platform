/**
 * Process Safety Management API (`/api/v1/safety/psm`). Every figure and list is
 * calculated by the API from stored records; nothing here invents data.
 */
import { APP_HEADER, apiGet, apiSend, ApiError } from "@/lib/api-client";

const BASE = "/api/v1/safety/psm";

export type Risk = "high" | "medium" | "low";
export type Disposition = "pending_review" | "accepted" | "rejected";
export type ActionStatus = "not_started" | "in_progress" | "pending_verification" | "closed";
export type DueState = "overdue" | "due_7" | "due_30" | "later" | "no_due_date" | "closed";

export const RISKS: Risk[] = ["high", "medium", "low"];
export const RISK_LABELS: Record<string, string> = { high: "High", medium: "Medium", low: "Low" };
export const DISPOSITION_LABELS: Record<string, string> = {
  pending_review: "Pending Review",
  accepted: "Accepted",
  rejected: "Rejected",
};
export const ACTION_STATUS_LABELS: Record<string, string> = {
  not_started: "Not Started",
  in_progress: "In Progress",
  pending_verification: "Pending Verification",
  closed: "Closed",
};
export const DUE_STATE_LABELS: Record<string, string> = {
  overdue: "Overdue",
  due_7: "Due in 7 days",
  due_30: "Due in 30 days",
  later: "Due later",
  no_due_date: "No due date",
  closed: "Closed",
};
export const ATTENTION_LABELS: Record<string, string> = {
  overdue: "Overdue",
  missing_owner: "No owner",
  missing_department: "No department",
  missing_due_date: "No due date",
  returned_or_reopened: "Returned or reopened",
  notification_failed: "Email not delivered",
  requires_resolution: "Needs resolution (recommendation rejected)",
};
export const NOTIFICATION_STATUS_LABELS: Record<string, string> = {
  queued: "Not sent yet",
  sent: "Sent",
  failed: "Failed",
  skipped: "Not sent",
};

export type Option = { id: number; name: string; active: boolean };
export type CodeLabel = { code: string; label: string };

export type Abilities = {
  editRecommendation: boolean;
  decideDisposition: boolean;
  manageActions: boolean;
  requestClosure: boolean;
  verifyClosure: boolean;
  reopen: boolean;
  admin: boolean;
  manageStudies: boolean;
  importData: boolean;
  export: boolean;
};

export type PsmOptions = {
  studies: Option[];
  studyTypes: Option[];
  areas: Option[];
  departments: Option[];
  processNodes: Option[];
  equipment: string[];
  owners: CodeLabel[];
  elements: CodeLabel[];
  dispositions: CodeLabel[];
  actionStatuses: CodeLabel[];
  risks: CodeLabel[];
  evidenceTypes: CodeLabel[];
  abilities: Abilities;
};

export type Study = {
  id: number;
  studyCode: string;
  title: string;
  year: number;
  studyTypeId: number;
  studyType: string;
  description: string | null;
  recommendationPrefix: string;
  status: string;
  studyDate: string | null;
  areas: Option[];
  sourceFileName: string | null;
  sourceSheetName: string | null;
  sourceReference: string | null;
  imported: boolean;
  version: number;
  createdAt: string;
  updatedAt: string;
  counts: Record<string, number>;
};

export type Scenario = {
  id: number;
  sequenceNumber: number;
  event: string;
  cause: string;
  consequence: string;
  risk: Risk;
  riskSource: string | null;
  areaEquipment: string | null;
  processNodeId: number | null;
  processNode: string | null;
  sourceRow: number | null;
  version: number;
};

export type Action = {
  id: number;
  actionNumber: string;
  recommendationId: number;
  recommendationDisplayId: string;
  studyId: number;
  title: string;
  description: string | null;
  recommendationText: string;
  areaEquipment: string;
  governingRisk: Risk | null;
  departmentId: number | null;
  department: string | null;
  ownerUserId: string | null;
  ownerName: string | null;
  ownerEmail: string | null;
  dueDate: string | null;
  status: ActionStatus;
  dueState: DueState | null;
  overdue: boolean;
  ageDays: number;
  attention: string[];
  closureSummary: string | null;
  closureExceptionReason: string | null;
  closureRequestedAt: string | null;
  closureRequestedByName: string | null;
  verifiedAt: string | null;
  verifiedByName: string | null;
  closedAt: string | null;
  returnedAt: string | null;
  returnReason: string | null;
  reopenedAt: string | null;
  reopenReason: string | null;
  requiresResolution: boolean;
  archived: boolean;
  version: number;
  createdAt: string;
  updatedAt: string;
};

export type RecommendationRow = {
  id: number;
  displayId: string;
  studyId: number;
  recommendationNumber: number;
  areaEquipment: string;
  recommendationText: string;
  governingRisk: Risk | null;
  scenarioCount: number;
  scenarioRisks: Record<string, number>;
  processNodeId: number | null;
  processNode: string | null;
  disposition: Disposition;
  department: string | null;
  owner: string | null;
  dueDate: string | null;
  actionId: number | null;
  actionNumber: string | null;
  actionStatus: ActionStatus | null;
  dueState: DueState | null;
  overdue: boolean;
  isDraft: boolean;
  archived: boolean;
  updatedAt: string;
};

export type Page<T> = { rows: T[]; total: number; page: number; pageSize: number };
export type ActionPage = Page<Action> & { tabCounts: Record<string, number> };

export type Attachment = {
  id: number;
  recommendationId: number | null;
  actionId: number | null;
  evidenceType: string;
  description: string | null;
  originalFileName: string;
  contentType: string;
  sizeBytes: number;
  uploadedByName: string;
  uploadedAt: string;
  removedAt: string | null;
  removedByName: string | null;
  removalReason: string | null;
};

export type ActionUpdate = {
  id: number;
  updateType: string;
  body: string;
  previousStatus: string | null;
  newStatus: string | null;
  createdByName: string;
  createdAt: string;
};

export type Notification = {
  id: number;
  eventType: string;
  recipientName: string | null;
  recipientEmail: string | null;
  subject: string;
  status: "queued" | "sent" | "failed" | "skipped";
  statusDetail: string | null;
  attempts: number;
  createdAt: string;
  lastAttemptAt: string | null;
  sentAt: string | null;
};

export type RecommendationDetail = {
  id: number;
  displayId: string;
  study: Study;
  recommendationNumber: number;
  areaEquipment: string;
  recommendationText: string;
  processNodeId: number | null;
  processNode: string | null;
  governingRisk: Risk | null;
  disposition: Disposition;
  dispositionJustification: string | null;
  dispositionByName: string | null;
  dispositionAt: string | null;
  notes: string | null;
  isDraft: boolean;
  archivedAt: string | null;
  archiveReason: string | null;
  sourceRowStart: number | null;
  sourceRowEnd: number | null;
  sourceKey: string | null;
  version: number;
  createdAt: string;
  updatedAt: string;
  scenarios: Scenario[];
  action: Action | null;
  attachments: Attachment[];
  abilities: Abilities;
};

export type ActionDetail = {
  action: Action;
  updates: ActionUpdate[];
  attachments: Attachment[];
  notifications: Notification[];
  mailEnabled: boolean;
  abilities: Abilities;
};

export type TimelineEvent = {
  occurredAt: string;
  actorName: string;
  event: string;
  entity: string;
  entityKey: string;
  action: string;
  oldValue: Record<string, unknown> | null;
  newValue: Record<string, unknown> | null;
};

export type Stage = { code: string; label: string; definition: string; count: number };
export type DashboardItem = {
  recommendationId: number;
  displayId: string;
  actionId: number;
  actionNumber: string;
  title: string;
  owner: string | null;
  department: string | null;
  dueDate: string | null;
  status: ActionStatus;
  governingRisk: Risk | null;
};
export type OwnerLoad = {
  owner: string;
  ownerKey: string | null;
  notStarted: number;
  inProgress: number;
  pendingVerification: number;
  overdue: number;
  totalActive: number;
};
export type DepartmentLoad = { department: string; departmentId: number | null; counts: Record<string, number> };

export type Kpis = {
  total: number;
  pending: number;
  accepted: number;
  rejected: number;
  notStarted: number;
  inProgress: number;
  pendingVerification: number;
  closed: number;
  overdue: number;
  needsScheduling: number;
  /** Closed actions as a percentage of actions; null when there are no actions. */
  closurePct: number | null;
  actions: number;
};

export type Dashboard = {
  scopeStudyId: number | null;
  today: string;
  kpis: Kpis;
  lifecycle: Stage[];
  rejected: Stage;
  scenarioRisks: Record<Risk, number>;
  governingRisks: Record<Risk, number>;
  matrix: Record<Risk, Record<string, number>>;
  matrixColumns: CodeLabel[];
  departments: DepartmentLoad[];
  aging: { code: string; label: string; count: number }[];
  due7: DashboardItem[];
  due30: DashboardItem[];
  overdue: DashboardItem[];
  needsScheduling: number;
  distribution: OwnerLoad[];
  drafts: number;
};

export type NotificationSettings = {
  notifyOnAssignment: boolean;
  notifyOnDueDateChange: boolean;
  notifyOnStatusChange: boolean;
  notifyOnComment: boolean;
  dueSoonReminders: boolean;
  overdueReminders: boolean;
  dueSoonDays: number;
};

export type ImportSummary = {
  source: { fileName: string; sheetName: string; sha256?: string };
  study: { studyCode: string; title: string; year: number };
  recommendations: number;
  scenarios: number;
  risks: Record<Risk, number>;
  trimmedValues: number;
  plan: {
    studyExists: boolean;
    newRecommendations: number;
    unchangedRecommendations: number;
    newScenarios: number;
    newProcessNodes: string[];
    differences: string[];
    conflicts: string[];
  };
  studyId?: number;
  created?: { recommendations: number; scenarios: number; processNodes: number };
};

// Register and action-list queries, kept in the page URL -------------------------------

export type RegisterQuery = {
  studyId: string;
  q: string;
  disposition: string;
  actionStatus: string;
  governingRisk: string;
  scenarioRisk: string;
  department: string;
  owner: string;
  equipment: string;
  node: string;
  dueState: string;
  stage: string;
  matrixRisk: string;
  matrixColumn: string;
  overdue: boolean;
  unassigned: boolean;
  missingDueDate: boolean;
  drafts: boolean;
  archived: boolean;
  sort: string;
  desc: boolean;
  page: number;
};

export const EMPTY_REGISTER_QUERY: RegisterQuery = {
  studyId: "",
  q: "",
  disposition: "",
  actionStatus: "",
  governingRisk: "",
  scenarioRisk: "",
  department: "",
  owner: "",
  equipment: "",
  node: "",
  dueState: "",
  stage: "",
  matrixRisk: "",
  matrixColumn: "",
  overdue: false,
  unassigned: false,
  missingDueDate: false,
  drafts: false,
  archived: false,
  sort: "id",
  desc: false,
  page: 1,
};

export type ActionQuery = {
  tab: string;
  studyId: string;
  q: string;
  department: string;
  owner: string;
  risk: string;
  dueState: string;
  aging: string;
  sort: string;
  desc: boolean;
  page: number;
};

export const EMPTY_ACTION_QUERY: ActionQuery = {
  tab: "all",
  studyId: "",
  q: "",
  department: "",
  owner: "",
  risk: "",
  dueState: "",
  aging: "",
  sort: "dueDate",
  desc: false,
  page: 1,
};

export const PAGE_SIZE = 25;

type Params = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

/** A query read from URL parameters; unknown keys and malformed values fall back to the defaults. */
function fromParams<T extends Record<string, string | boolean | number>>(params: Params, empty: T): T {
  const out: Record<string, string | boolean | number> = { ...empty };
  for (const [key, fallback] of Object.entries(empty)) {
    const raw = first(params[key]).slice(0, 200);
    if (raw === "") continue;
    if (typeof fallback === "boolean") out[key] = raw === "true";
    else if (typeof fallback === "number") {
      const n = Number(raw);
      out[key] = Number.isInteger(n) && n >= 1 && n < 100_000 ? n : fallback;
    } else out[key] = raw;
  }
  return out as T;
}

/** URL parameters of a query: only values that differ from the defaults. */
function toParams<T extends Record<string, string | boolean | number>>(query: T, empty: T): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === empty[key] || value === "" || value === false) continue;
    params.set(key, String(value));
  }
  return params;
}

export const registerFromParams = (params: Params) => fromParams(params, EMPTY_REGISTER_QUERY);
export const registerParams = (query: RegisterQuery) => toParams(query, EMPTY_REGISTER_QUERY);
export const actionsFromParams = (params: Params) => fromParams(params, EMPTY_ACTION_QUERY);
export const actionParams = (query: ActionQuery) => toParams(query, EMPTY_ACTION_QUERY);

export function registerHref(query: Partial<RegisterQuery>): string {
  const params = registerParams({ ...EMPTY_REGISTER_QUERY, ...query });
  const text = params.toString();
  return text ? `/safety/psm/pha?${text}` : "/safety/psm/pha";
}

export function actionsHref(query: Partial<ActionQuery>): string {
  const params = actionParams({ ...EMPTY_ACTION_QUERY, ...query });
  const text = params.toString();
  return text ? `/safety/psm/actions?${text}` : "/safety/psm/actions";
}

export const recommendationHref = (id: number) => `/safety/psm/pha/recommendations/${id}`;
export const actionHref = (id: number) => `/safety/psm/actions/${id}`;
export const studyHref = (id: number) => `/safety/psm/pha/${id}`;

function apiQuery(query: RegisterQuery | ActionQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === "" || value === false) continue;
    params.set(key, String(value));
  }
  params.set("pageSize", String(PAGE_SIZE));
  return params.toString();
}

/** Export filters as the report endpoint takes them (lists for multi-valued filters). */
export function registerExportFilters(query: RegisterQuery): Record<string, unknown> {
  const list = (value: string) => (value ? [value] : []);
  return {
    studyId: query.studyId ? Number(query.studyId) : null,
    q: query.q || null,
    disposition: list(query.disposition),
    actionStatus: list(query.actionStatus),
    governingRisk: list(query.governingRisk),
    scenarioRisk: list(query.scenarioRisk),
    department: list(query.department),
    owner: list(query.owner),
    equipment: list(query.equipment),
    node: query.node ? [Number(query.node)] : [],
    dueState: list(query.dueState),
    stage: query.stage || null,
    matrixRisk: query.matrixRisk || null,
    matrixColumn: query.matrixColumn || null,
    overdue: query.overdue || null,
    unassigned: query.unassigned || null,
    missingDueDate: query.missingDueDate || null,
    drafts: query.drafts || null,
    archived: query.archived || null,
    sort: query.sort,
    desc: query.desc || null,
  };
}

export function actionExportFilters(query: ActionQuery): Record<string, unknown> {
  const list = (value: string) => (value ? [value] : []);
  return {
    tab: query.tab,
    studyId: query.studyId ? Number(query.studyId) : null,
    q: query.q || null,
    department: list(query.department),
    owner: list(query.owner),
    risk: list(query.risk),
    dueState: list(query.dueState),
    aging: query.aging || null,
    sort: query.sort,
    desc: query.desc || null,
  };
}

// Reads ---------------------------------------------------------------------------------

export const psmKeys = {
  all: ["psm"] as const,
  options: () => [...psmKeys.all, "options"] as const,
  dashboard: (studyId: string) => [...psmKeys.all, "dashboard", studyId] as const,
  studies: () => [...psmKeys.all, "studies"] as const,
  study: (id: number) => [...psmKeys.all, "study", id] as const,
  register: (query: RegisterQuery) => [...psmKeys.all, "register", query] as const,
  recommendation: (id: number) => [...psmKeys.all, "recommendation", id] as const,
  timeline: (id: number) => [...psmKeys.all, "timeline", id] as const,
  actions: (query: ActionQuery) => [...psmKeys.all, "actions", query] as const,
  action: (id: number) => [...psmKeys.all, "action", id] as const,
  notificationSettings: () => [...psmKeys.all, "notification-settings"] as const,
};

export const fetchOptions = (signal?: AbortSignal) => apiGet<PsmOptions>(`${BASE}/options`, { signal });
export const fetchDashboard = (studyId: string, signal?: AbortSignal) =>
  apiGet<Dashboard>(`${BASE}/dashboard${studyId ? `?studyId=${encodeURIComponent(studyId)}` : ""}`, { signal });
export const fetchStudies = (signal?: AbortSignal) => apiGet<Study[]>(`${BASE}/studies`, { signal });
export const fetchStudy = (id: number, signal?: AbortSignal) => apiGet<Study>(`${BASE}/studies/${id}`, { signal });
export const fetchRegister = (query: RegisterQuery, signal?: AbortSignal) =>
  apiGet<Page<RecommendationRow>>(`${BASE}/recommendations?${apiQuery(query)}`, { signal });
export const fetchRecommendation = (id: number, signal?: AbortSignal) =>
  apiGet<RecommendationDetail>(`${BASE}/recommendations/${id}`, { signal });
export const fetchTimeline = (id: number, signal?: AbortSignal) =>
  apiGet<{ events: TimelineEvent[] }>(`${BASE}/recommendations/${id}/timeline`, { signal }).then((b) => b.events);
export const fetchActions = (query: ActionQuery, signal?: AbortSignal) =>
  apiGet<ActionPage>(`${BASE}/actions?${apiQuery(query)}`, { signal });
export const fetchAction = (id: number, signal?: AbortSignal) =>
  apiGet<ActionDetail>(`${BASE}/actions/${id}`, { signal });
export const fetchNotificationSettings = (signal?: AbortSignal) =>
  apiGet<NotificationSettings>(`${BASE}/notification-settings`, { signal });

export const attachmentHref = (id: number) => `${BASE}/attachments/${id}/content`;

// Writes ----------------------------------------------------------------------------------

export type ScenarioFields = {
  event: string;
  cause: string;
  consequence: string;
  risk: Risk;
  areaEquipment: string | null;
  processNodeId: number | null;
};

export type Assignment = {
  departmentId: number | null;
  ownerUserId: string | null;
  ownerName: string | null;
  ownerEmail: string | null;
  dueDate: string | null;
  task: string | null;
};

export type StudyFields = {
  studyCode: string;
  title: string;
  year: number;
  studyTypeId: number;
  description: string | null;
  recommendationPrefix: string;
  status: string;
  studyDate: string | null;
  areaIds: number[];
  version?: number;
};

export const psmApi = {
  createStudy: (body: StudyFields) => apiSend<Study>("POST", `${BASE}/studies`, body),
  updateStudy: (id: number, body: StudyFields) => apiSend<Study>("PUT", `${BASE}/studies/${id}`, body),
  createRecommendation: (body: {
    studyId: number;
    areaEquipment: string;
    recommendationText: string;
    processNodeId: number | null;
    notes: string | null;
    isDraft: boolean;
    scenarios: ScenarioFields[];
  }) => apiSend<RecommendationDetail>("POST", `${BASE}/recommendations`, body),
  updateRecommendation: (
    id: number,
    body: {
      version: number;
      areaEquipment: string;
      recommendationText: string;
      processNodeId: number | null;
      notes: string | null;
      isDraft: boolean;
    },
  ) => apiSend<RecommendationDetail>("PUT", `${BASE}/recommendations/${id}`, body),
  addScenario: (id: number, body: ScenarioFields) =>
    apiSend<RecommendationDetail>("POST", `${BASE}/recommendations/${id}/scenarios`, body),
  updateScenario: (id: number, scenarioId: number, body: ScenarioFields & { version: number }) =>
    apiSend<RecommendationDetail>("PUT", `${BASE}/recommendations/${id}/scenarios/${scenarioId}`, body),
  reorderScenarios: (id: number, body: { version: number; scenarioIds: number[] }) =>
    apiSend<RecommendationDetail>("PUT", `${BASE}/recommendations/${id}/scenario-order`, body),
  accept: (id: number, body: Partial<Assignment> & { version: number; confirm: true }) =>
    apiSend<RecommendationDetail>("POST", `${BASE}/recommendations/${id}/accept`, body),
  reject: (id: number, body: { version: number; justification: string }) =>
    apiSend<RecommendationDetail>("POST", `${BASE}/recommendations/${id}/reject`, body),
  returnToPending: (id: number, body: { version: number; reason: string }) =>
    apiSend<RecommendationDetail>("POST", `${BASE}/recommendations/${id}/return-to-pending`, body),
  archive: (id: number, body: { version: number; reason: string }) =>
    apiSend<RecommendationDetail>("POST", `${BASE}/recommendations/${id}/archive`, body),
  restore: (id: number, body: { version: number; reason: string }) =>
    apiSend<RecommendationDetail>("POST", `${BASE}/recommendations/${id}/restore`, body),
  updateAction: (id: number, body: Assignment & { version: number; title: string; dueDateReason: string | null }) =>
    apiSend<ActionDetail>("PUT", `${BASE}/actions/${id}`, body),
  changeStatus: (id: number, body: { version: number; status: "not_started" | "in_progress"; note: string | null }) =>
    apiSend<ActionDetail>("POST", `${BASE}/actions/${id}/status`, body),
  requestClosure: (
    id: number,
    body: { version: number; summary: string; exceptionReason: string | null; skipReason: string | null },
  ) => apiSend<ActionDetail>("POST", `${BASE}/actions/${id}/closure-request`, body),
  approveClosure: (id: number, body: { version: number; note: string | null }) =>
    apiSend<ActionDetail>("POST", `${BASE}/actions/${id}/closure-approval`, body),
  returnClosure: (id: number, body: { version: number; reason: string }) =>
    apiSend<ActionDetail>("POST", `${BASE}/actions/${id}/closure-return`, body),
  reopen: (id: number, body: { version: number; reason: string }) =>
    apiSend<ActionDetail>("POST", `${BASE}/actions/${id}/reopen`, body),
  comment: (id: number, body: { body: string }) =>
    apiSend<ActionDetail>("POST", `${BASE}/actions/${id}/comments`, body),
  resolve: (id: number, body: { version: number; resolution: "keep" | "archive"; reason: string }) =>
    apiSend<ActionDetail>("POST", `${BASE}/actions/${id}/resolution`, body),
  removeAttachment: (id: number, reason: string) =>
    apiSend<void>("POST", `${BASE}/attachments/${id}/removal`, { body: reason }),
  saveReference: (kind: "departments" | "process-nodes", body: { name: string; active: boolean }, id?: number) =>
    apiSend<Option>(id ? "PUT" : "POST", `${BASE}/reference/${kind}${id ? `/${id}` : ""}`, body),
  saveNotificationSettings: (body: NotificationSettings) =>
    apiSend<NotificationSettings>("PUT", `${BASE}/notification-settings`, body),
  deliverNow: () =>
    apiSend<{ mailEnabled: boolean; sent: number; failed: number; queued: number }>(
      "POST",
      `${BASE}/notifications/deliver`,
    ),
};

/** Sends a file as the raw request body (the API limits files to 10 MB). */
async function sendFile<T>(path: string, file: File, query: Record<string, string | null>): Promise<T> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) if (value) params.set(key, value);
  const response = await fetch(`${path}?${params}`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/octet-stream", ...APP_HEADER },
    body: file,
  });
  if (!response.ok) {
    let detail: Record<string, unknown> | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (body.detail && typeof body.detail === "object") detail = body.detail as Record<string, unknown>;
    } catch {
      detail = undefined;
    }
    throw new ApiError(response.status, `POST ${path} failed: ${response.status}`, detail);
  }
  return (await response.json()) as T;
}

export const MAX_FILE_BYTES = 10 * 1024 * 1024;

export const uploadEvidence = (
  target: { recommendationId: number } | { actionId: number },
  file: File,
  evidenceType: string,
  description: string | null,
) =>
  sendFile<RecommendationDetail | ActionDetail>(
    "recommendationId" in target
      ? `${BASE}/recommendations/${target.recommendationId}/attachments`
      : `${BASE}/actions/${target.actionId}/attachments`,
    file,
    { fileName: file.name, evidenceType, description },
  );

export const importWorkbook = (step: "plan" | "apply", file: File) =>
  sendFile<ImportSummary>(`${BASE}/imports/pha/${step}`, file, { fileName: file.name });

// Errors ----------------------------------------------------------------------------------

export function describePsmError(error: unknown): string {
  if (!(error instanceof ApiError)) return "The API could not be reached.";
  switch (error.status) {
    case 401:
      return "Your session has ended. Sign in again to continue.";
    case 403:
      return error.detail?.message ?? "You do not have permission for this.";
    case 404:
      return error.detail?.message ?? "No such record.";
    case 409:
      return error.detail?.message ?? "This record changed since you loaded it. Nothing was saved. Reload and try again.";
    case 413:
      return "Files are limited to 10 MB.";
    case 422: {
      const errors = error.detail?.errors;
      if (Array.isArray(errors) && errors.length > 0) return `${error.detail?.message ?? "Not valid."} ${errors.join(" ")}`;
      return error.detail?.message ?? "Check the values entered.";
    }
    case 503:
      return "Process Safety Management data is unavailable because the database could not be reached.";
    default:
      return error.detail?.message ?? `The API responded with HTTP ${error.status}.`;
  }
}
