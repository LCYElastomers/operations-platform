import { ApiError, apiGet, apiSend } from "@/lib/api-client";

import type { CoqClass, CostHistoryEvent, FinancialStatus } from "../cost/api";

export type CarStatus = "open" | "closed";
export type ActionStatus = "open" | "in_progress" | "complete" | "on_hold";
export type EffectivenessResult = "effective" | "not_effective";
export type StepState = "not_started" | "in_progress" | "complete";
export type ApprovalFunction =
  | "quality"
  | "department_supervisor"
  | "safety_environmental"
  | "operations_maintenance"
  | "engineering"
  | "process_manager";

/** The filter value matching reports where a field was not recorded. */
export const NOT_RECORDED = "not_recorded";

export type WhyStep = {
  what: string | null;
  why: string | null;
  rootCause: string | null;
  countermeasure: string | null;
  who: string | null;
  targetDate: string | null;
};

export type ReferenceInput = { type: string; key: string; label: string | null };

/**
 * Everything on the report except its corrective actions and approvals. Null
 * is "not recorded". People are platform users sent by ID; the API records
 * their names. A name without an ID may only repeat a name recorded before
 * users existed. The effectiveness reviewer and closure approver are not
 * fields: the API records the signed-in user who records the review or closes.
 */
export type CarFields = {
  subject: string;
  requestedByUserId: string | null;
  requestedBy: string | null;
  requestDate: string;
  assignedToUserId: string | null;
  assignedTo: string | null;
  dueDate: string | null;
  sourceCode: string | null;
  departmentCode: string | null;
  startedOn: string | null;
  startedTime: string | null;
  endedOn: string | null;
  endedTime: string | null;
  previousOccurrence: boolean | null;
  previousCar: string | null;
  nonconformityDescription: string | null;
  objectiveEvidence: string | null;
  immediateActions: string | null;
  containmentOwnerUserId: string | null;
  containmentOwner: string | null;
  containmentCompletedOn: string | null;
  dispositionCodes: string[];
  dispositionOther: string | null;
  safetyHazard: boolean | null;
  environmentalHazard: boolean | null;
  customerImpact: boolean | null;
  incidentType: string | null;
  rootCauseCode: string | null;
  equipmentInvolved: string | null;
  workOrderNumber: string | null;
  investigationSummary: string | null;
  trueRootCause: string | null;
  whySteps: WhyStep[];
  complaintNumber: string | null;
  dateReported: string | null;
  drNumber: string | null;
  materialName: string | null;
  poNumber: string | null;
  supplier: string | null;
  dateDelivered: string | null;
  productionLot: string | null;
  quantityAffected: string | null;
  similarNonconformities: string | null;
  similarIssueFound: boolean | null;
  additionalActionRequired: boolean | null;
  proceduresRevised: string | null;
  trainingCompleted: boolean | null;
  supportingDocuments: string | null;
  planCompletedOn: string | null;
  successCriteria: string | null;
  effectivenessEvidence: string | null;
  reviewDate: string | null;
  effectivenessResult: EffectivenessResult | null;
  followUpReference: string | null;
  materialLoss: string | null;
  productionTimeLoss: string | null;
  otherCosts: string | null;
  status: CarStatus | null;
  dateClosed: string | null;
  product: string | null;
  campaign: string | null;
  lot: string | null;
  location: string | null;
  counterparty: string | null;
  references: ReferenceInput[];
};

export type ActionFields = {
  action: string;
  ownerUserId: string | null;
  /** Only a name recorded before users existed, kept unchanged. */
  owner: string | null;
  targetDate: string | null;
  status: ActionStatus;
  completedOn: string | null;
  proceduresRevised: string | null;
  trainingCompleted: boolean | null;
  supportingDocuments: string | null;
};

export type CarAction = Omit<ActionFields, "status"> & {
  id: number;
  position: number;
  /** Null when an imported action recorded no status. */
  status: ActionStatus | null;
  statusLabel: string;
  overdue: boolean;
  version: number;
  createdAt: string;
  createdBy: string;
  createdByName: string;
  updatedAt: string;
  updatedBy: string;
  updatedByName: string;
};

export type ActionProgress = { total: number; complete: number; outstanding: number; overdue: number };

export type CarSummary = {
  id: number;
  carNumber: string;
  subject: string;
  requestedBy: string | null;
  requestedByUserId: string | null;
  requestDate: string;
  assignedTo: string | null;
  assignedToUserId: string | null;
  dueDate: string | null;
  status: CarStatus | null;
  statusLabel: string;
  dateClosed: string | null;
  sourceCode: string | null;
  sourceLabel: string | null;
  departmentCode: string | null;
  departmentLabel: string | null;
  rootCauseCode: string | null;
  rootCauseLabel: string | null;
  effectivenessResult: EffectivenessResult | null;
  effectivenessLabel: string | null;
  previousOccurrence: boolean | null;
  daysOpen: number;
  pastDue: boolean;
  dueSoon: boolean;
  awaitingEffectiveness: boolean;
  /** Sum of the entered cost lines; null when none is entered. */
  totalCost: string | null;
  qualityCostRecordId: number | null;
  actions: ActionProgress;
  source: "manual" | "legacy_import";
};

export type LinkedCost = {
  id: number;
  recordNumber: string;
  title: string;
  coqClassLabel: string;
  totalCost: string | null;
  financialStatusLabel: string;
  statusLabel: string;
};

export type Approval = {
  functionCode: ApprovalFunction;
  functionLabel: string;
  name: string;
  /** The approving user; null on imported approvals. */
  userId: string | null;
  approvedOn: string | null;
  /** The platform user who recorded the approval (not a signature). */
  recordedBy: string;
  recordedByName: string;
  recordedAt: string;
};

export type Car = CarSummary &
  Omit<CarFields, keyof CarSummary | "references" | "whySteps"> & {
    whySteps: (WhyStep & { position: number })[];
    dispositionLabels: string[];
    qualityCost: LinkedCost | null;
    /** Who recorded the effectiveness review (the signed-in user), or a name from an imported form. */
    reviewer: string | null;
    reviewerUserId: string | null;
    /** Who closed the CAR (the signed-in user), or a name from an imported form. */
    closureApprovedBy: string | null;
    closureApprovedByUserId: string | null;
    approvals: Approval[];
    references: (ReferenceInput & { typeLabel: string })[];
    actionItems: CarAction[];
    steps: { code: string; label: string; state: StepState }[];
    legacyFields: { label: string; value: string }[];
    migrationNotes: string | null;
    version: number;
    createdAt: string;
    createdBy: string;
    createdByName: string;
    updatedAt: string;
    updatedBy: string;
    updatedByName: string;
  };

/** What the signed-in user may do. The interface uses it to offer controls; the API checks every request. */
export type CarAbilities = {
  create: boolean;
  edit: boolean;
  assign: boolean;
  manageActions: boolean;
  completeAction: boolean;
  reviewEffectiveness: boolean;
  approve: boolean;
  close: boolean;
  reopen: boolean;
  admin: boolean;
  createQualityCost: boolean;
  linkQualityCost: boolean;
};

export type CarResponse = {
  car: Car;
  canEdit: boolean;
  canEditCost: boolean;
  abilities: CarAbilities;
  currentUserId: string | null;
};
export type CarList = { cars: CarSummary[]; total: number; canEdit: boolean; abilities: CarAbilities };

export type Choice = { code: string; label: string; active: boolean };
export type CodeLabel = { code: string; label: string };

export type CarOptions = {
  sources: Choice[];
  departments: Choice[];
  rootCauses: Choice[];
  dispositions: Choice[];
  actionStatuses: CodeLabel[];
  effectivenessResults: CodeLabel[];
  carStatuses: CodeLabel[];
  approvalFunctions: { code: ApprovalFunction; label: string }[];
  referenceTypes: CodeLabel[];
  steps: CodeLabel[];
  /** Names already used on reports, for filters. */
  people: string[];
  assignees: string[];
  dueSoonDays: number;
  canEdit: boolean;
  canEditCost: boolean;
  abilities: CarAbilities;
};

export type CarHistoryEvent = CostHistoryEvent & { entity: "car" | "action"; actionId: number | null };

export type Count = { code: string | null; label: string; count: number };

export type CarDashboard = {
  today: string;
  year: number;
  dueSoonDays: number;
  kpis: {
    total: number;
    open: number;
    pastDue: number;
    dueSoon: number;
    awaitingEffectiveness: number;
    closedYtd: number;
    statusNotRecorded: number;
    actionsOverdue: number;
  };
  byStatus: Count[];
  byDepartment: Count[];
  bySource: Count[];
  byRootCause: Count[];
  effectiveness: Count[];
  repeat: Count[];
  repeatCars: { id: number; carNumber: string; subject: string; previousCar: string | null }[];
  trend: { year: number; month: number; opened: number; closed: number }[];
  aging: { label: string; minDays: number; maxDays: number | null; count: number }[];
  cost: {
    total: string | null;
    withCost: number;
    withoutCost: number;
    linkedToQualityCost: number;
    byDepartment: { code: string | null; label: string; total: string; count: number }[];
  };
};

export type CarQuery = {
  from: string;
  to: string;
  status: string;
  department: string;
  source: string;
  assignedTo: string;
  rootCause: string;
  effectiveness: string;
  pastDue: boolean;
  /** "" any, "yes" repeat only, "no" not a repeat. */
  repeat: "" | "yes" | "no";
  search: string;
};

export const EMPTY_CAR_QUERY: CarQuery = {
  from: "",
  to: "",
  status: "",
  department: "",
  source: "",
  assignedTo: "",
  rootCause: "",
  effectiveness: "",
  pastDue: false,
  repeat: "",
  search: "",
};

export type CarDashboardQuery = Pick<CarQuery, "from" | "to" | "department" | "source" | "assignedTo">;

export const carKeys = {
  all: ["quality", "cars"] as const,
  list: (query: CarQuery) => [...carKeys.all, "list", query] as const,
  dashboard: (query: CarDashboardQuery) => [...carKeys.all, "dashboard", query] as const,
  options: () => [...carKeys.all, "options"] as const,
  car: (id: number) => [...carKeys.all, "car", id] as const,
  history: (id: number) => [...carKeys.all, "history", id] as const,
  linked: (costRecordId: number) => [...carKeys.all, "linked", costRecordId] as const,
};

const BASE = "/api/v1/quality/cars";

/** A CAR's page; under the register so navigation shows where it belongs. */
export function carHref(id: number) {
  return `/quality/cars/register/${id}`;
}

function withParams(path: string, params: URLSearchParams) {
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

/** Query string of the filters, shared by the API request and the register's URL. */
export function carQueryParams(query: Partial<CarQuery>): URLSearchParams {
  const params = new URLSearchParams();
  if (query.from) params.set("from", query.from);
  if (query.to) params.set("to", query.to);
  if (query.status) params.set("status", query.status);
  if (query.department) params.set("department", query.department);
  if (query.source) params.set("source", query.source);
  if (query.rootCause) params.set("rootCause", query.rootCause);
  if (query.effectiveness) params.set("effectiveness", query.effectiveness);
  if (query.assignedTo?.trim()) params.set("assignedTo", query.assignedTo.trim());
  if (query.pastDue) params.set("pastDue", "true");
  if (query.repeat) params.set("repeat", query.repeat === "yes" ? "true" : "false");
  if (query.search?.trim()) params.set("search", query.search.trim());
  return params;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Register filters from a URL query (e.g. a dashboard link); unknown values are dropped. */
export function carQueryFromParams(params: Record<string, string | string[] | undefined>): CarQuery {
  const one = (key: string) => {
    const value = params[key];
    return (Array.isArray(value) ? value[0] : value)?.slice(0, 200) ?? "";
  };
  const code = (key: string) => (/^[a-z_]{1,50}$/.test(one(key)) ? one(key) : "");
  const date = (key: string) => (ISO_DATE.test(one(key)) ? one(key) : "");
  const repeat = one("repeat");
  return {
    from: date("from"),
    to: date("to"),
    status: code("status"),
    department: code("department"),
    source: code("source"),
    assignedTo: one("assignedTo"),
    rootCause: code("rootCause"),
    effectiveness: code("effectiveness"),
    pastDue: one("pastDue") === "true",
    repeat: repeat === "true" ? "yes" : repeat === "false" ? "no" : "",
    search: one("search"),
  };
}

export function fetchCars(query: CarQuery, signal?: AbortSignal) {
  return apiGet<CarList>(withParams(BASE, carQueryParams(query)), { signal });
}

export function fetchCarDashboard(query: CarDashboardQuery, signal?: AbortSignal) {
  return apiGet<CarDashboard>(withParams(`${BASE}/dashboard`, carQueryParams(query)), { signal });
}

export function fetchCarOptions(signal?: AbortSignal) {
  return apiGet<CarOptions>(`${BASE}/options`, { signal });
}

export function fetchCar(id: number, signal?: AbortSignal) {
  return apiGet<CarResponse>(`${BASE}/${id}`, { signal });
}

export function fetchCarHistory(id: number, signal?: AbortSignal) {
  return apiGet<{ carId: number; events: CarHistoryEvent[] }>(`${BASE}/${id}/history`, { signal });
}

export function fetchLinkedCars(costRecordId: number, signal?: AbortSignal) {
  return apiGet<{ id: number; carNumber: string; subject: string }[]>(
    `${BASE}/linked?costRecordId=${costRecordId}`,
    { signal },
  );
}

export function createCar(body: CarFields) {
  return apiSend<CarResponse>("POST", BASE, body);
}

export function updateCar(id: number, body: CarFields & { version: number }) {
  return apiSend<CarResponse>("PUT", `${BASE}/${id}`, body);
}

export function addAction(carId: number, body: ActionFields) {
  return apiSend<CarResponse>("POST", `${BASE}/${carId}/actions`, body);
}

export function updateAction(carId: number, actionId: number, body: ActionFields & { version: number }) {
  return apiSend<CarResponse>("PUT", `${BASE}/${carId}/actions/${actionId}`, body);
}

export function completeAction(carId: number, actionId: number, body: { version: number; completedOn: string }) {
  return apiSend<CarResponse>("POST", `${BASE}/${carId}/actions/${actionId}/complete`, body);
}

/** Records the signed-in user's approval for one function, dated today. */
export function recordApproval(carId: number, body: { version: number; functionCode: ApprovalFunction }) {
  return apiSend<CarResponse>("POST", `${BASE}/${carId}/approvals`, body);
}

export function withdrawApproval(carId: number, body: { version: number; functionCode: ApprovalFunction }) {
  return apiSend<CarResponse>(
    "DELETE",
    `${BASE}/${carId}/approvals/${encodeURIComponent(body.functionCode)}?version=${body.version}`,
  );
}

/**
 * Whether the signed-in user may record an action as complete: its owner with
 * car.completeAction, or a CAR administrator. The API applies the same rule.
 */
export function canCompleteCarAction(
  action: Pick<CarAction, "ownerUserId">,
  response: Pick<CarResponse, "abilities" | "currentUserId">,
): boolean {
  if (response.abilities.admin) return true;
  return (
    response.abilities.completeAction &&
    action.ownerUserId !== null &&
    action.ownerUserId === response.currentUserId
  );
}

/** Whether the signed-in user may withdraw an approval: their own, or any as a CAR administrator. */
export function canWithdrawApproval(
  approval: Pick<Approval, "userId">,
  response: Pick<CarResponse, "abilities" | "currentUserId">,
): boolean {
  return response.abilities.admin || (approval.userId !== null && approval.userId === response.currentUserId);
}

export type QualityCostCreate = {
  version: number;
  areaId: number;
  coqClass: CoqClass;
  categoryCode: string;
  financialStatus: FinancialStatus;
};

export function createQualityCost(carId: number, body: QualityCostCreate) {
  return apiSend<CarResponse>("POST", `${BASE}/${carId}/quality-cost`, body);
}

export function linkQualityCost(carId: number, body: { version: number; recordId: number | null }) {
  return apiSend<CarResponse>("PUT", `${BASE}/${carId}/quality-cost`, body);
}

/** A save refused by a rule (422, naming the field) or an edit conflict (409). */
export function carSaveError(error: unknown): { message: string; field: string | null; conflict: boolean } | null {
  if (!(error instanceof ApiError)) return null;
  const detail = error.detail as { message?: string; field?: unknown } | undefined;
  if (error.status === 409) {
    return {
      message: detail?.message ?? "This CAR changed since you loaded it. Nothing was saved.",
      field: null,
      conflict: true,
    };
  }
  if (detail?.message && (error.status === 422 || error.status === 404 || error.status === 403)) {
    return { message: detail.message, field: typeof detail.field === "string" ? detail.field : null, conflict: false };
  }
  return null;
}

export function describeCarError(error: unknown): string {
  if (!(error instanceof ApiError)) return "The API could not be reached.";
  switch (error.status) {
    case 401:
      return "Your session has ended. Sign in again to continue.";
    case 403:
      return error.detail?.message ?? "You do not have permission to view Corrective Action Reports.";
    case 404:
      return "No such Corrective Action Report.";
    case 422:
      return error.detail?.message ?? "Check the values entered.";
    case 503:
      return "Corrective Action Report data is unavailable because the database could not be reached.";
    default:
      return error.detail?.message ?? `The API responded with HTTP ${error.status}.`;
  }
}
