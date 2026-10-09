import { MONEY, MONEY_MESSAGE, previewTotal } from "../cost/record-form";

import type {
  ActionFields,
  ApprovalFunction,
  Car,
  CarAction,
  CarFields,
  CarStatus,
  EffectivenessResult,
} from "./api";

/** Yes / No / not recorded. "" is not recorded: never treated as No. */
export type YesNo = "" | "yes" | "no";

export const TEXT_FIELDS = [
  "requestedBy",
  "assignedTo",
  "dueDate",
  "sourceCode",
  "departmentCode",
  "startedOn",
  "startedTime",
  "endedOn",
  "endedTime",
  "previousCar",
  "nonconformityDescription",
  "objectiveEvidence",
  "immediateActions",
  "containmentOwner",
  "containmentCompletedOn",
  "dispositionOther",
  "incidentType",
  "rootCauseCode",
  "equipmentInvolved",
  "workOrderNumber",
  "investigationSummary",
  "trueRootCause",
  "complaintNumber",
  "dateReported",
  "drNumber",
  "materialName",
  "poNumber",
  "supplier",
  "dateDelivered",
  "productionLot",
  "quantityAffected",
  "similarNonconformities",
  "proceduresRevised",
  "supportingDocuments",
  "planCompletedOn",
  "successCriteria",
  "effectivenessEvidence",
  "reviewer",
  "reviewDate",
  "followUpReference",
  "materialLoss",
  "productionTimeLoss",
  "otherCosts",
  "dateClosed",
  "closureApprovedBy",
  "product",
  "campaign",
  "lot",
  "location",
  "counterparty",
] as const satisfies readonly (keyof CarFields)[];
export type TextField = (typeof TEXT_FIELDS)[number];

export const YES_NO_FIELDS = [
  "previousOccurrence",
  "safetyHazard",
  "environmentalHazard",
  "customerImpact",
  "similarIssueFound",
  "additionalActionRequired",
  "trainingCompleted",
] as const satisfies readonly (keyof CarFields)[];
export type YesNoField = (typeof YES_NO_FIELDS)[number];

export const COST_LINES = [
  { field: "materialLoss", label: "Material loss" },
  { field: "productionTimeLoss", label: "Production time loss" },
  { field: "otherCosts", label: "Other costs" },
] as const;

export type WhyDraft = {
  what: string;
  why: string;
  rootCause: string;
  countermeasure: string;
  who: string;
  targetDate: string;
};

export type CarDraft = Record<TextField, string> &
  Record<YesNoField, YesNo> & {
    subject: string;
    requestDate: string;
    dispositionCodes: string[];
    effectivenessResult: "" | EffectivenessResult;
    /** "" only on imported CARs whose form recorded no status. */
    status: "" | CarStatus;
    whySteps: WhyDraft[];
    approvals: Partial<Record<ApprovalFunction, { name: string; approvedOn: string }>>;
    references: { type: string; key: string; label: string }[];
  };

export const EMPTY_WHY: WhyDraft = { what: "", why: "", rootCause: "", countermeasure: "", who: "", targetDate: "" };

function yesNo(value: boolean | null): YesNo {
  return value === null ? "" : value ? "yes" : "no";
}

function fromYesNo(value: YesNo): boolean | null {
  return value === "" ? null : value === "yes";
}

/** "07:30:00" as "07:30"; times with seconds keep them. */
function timeOf(value: string | null): string {
  if (!value) return "";
  return value.endsWith(":00") && value.length === 8 ? value.slice(0, 5) : value;
}

export function emptyDraft(today: string): CarDraft {
  const draft = {
    subject: "",
    requestDate: today,
    dispositionCodes: [],
    effectivenessResult: "",
    status: "open",
    whySteps: [],
    approvals: {},
    references: [],
  } as unknown as CarDraft;
  for (const field of TEXT_FIELDS) draft[field] = "";
  for (const field of YES_NO_FIELDS) draft[field] = "";
  return draft;
}

export function draftOf(car: Car): CarDraft {
  const draft = emptyDraft(car.requestDate);
  for (const field of TEXT_FIELDS) {
    const value = car[field];
    draft[field] = field === "startedTime" || field === "endedTime" ? timeOf(value) : (value ?? "");
  }
  for (const field of YES_NO_FIELDS) draft[field] = yesNo(car[field]);
  draft.subject = car.subject;
  draft.dispositionCodes = [...car.dispositionCodes];
  draft.effectivenessResult = car.effectivenessResult ?? "";
  draft.status = car.status ?? "";
  draft.whySteps = car.whySteps.map((step) => ({
    what: step.what ?? "",
    why: step.why ?? "",
    rootCause: step.rootCause ?? "",
    countermeasure: step.countermeasure ?? "",
    who: step.who ?? "",
    targetDate: step.targetDate ?? "",
  }));
  draft.approvals = Object.fromEntries(
    car.approvals.map((a) => [a.functionCode, { name: a.name, approvedOn: a.approvedOn ?? "" }]),
  );
  draft.references = car.references.map((r) => ({ type: r.type, key: r.key, label: r.label ?? "" }));
  return draft;
}

function text(value: string): string | null {
  return value.trim() ? value.trim() : null;
}

/** The request body. Blank fields are sent as null (not recorded), never as 0 or No. */
export function fieldsOf(draft: CarDraft): CarFields {
  const fields = {} as Record<string, unknown>;
  for (const field of TEXT_FIELDS) fields[field] = text(draft[field]);
  for (const field of YES_NO_FIELDS) fields[field] = fromYesNo(draft[field]);
  return {
    ...(fields as Omit<CarFields, "subject" | "requestDate">),
    subject: draft.subject.trim(),
    requestDate: draft.requestDate,
    dispositionCodes: draft.dispositionCodes,
    effectivenessResult: draft.effectivenessResult || null,
    status: draft.status || null,
    whySteps: draft.whySteps
      .map((step) => ({
        what: text(step.what),
        why: text(step.why),
        rootCause: text(step.rootCause),
        countermeasure: text(step.countermeasure),
        who: text(step.who),
        targetDate: step.targetDate || null,
      }))
      .filter((step) => Object.values(step).some((value) => value !== null)),
    approvals: Object.entries(draft.approvals)
      .filter(([, approval]) => approval && (approval.name.trim() || approval.approvedOn))
      .map(([functionCode, approval]) => ({
        functionCode: functionCode as ApprovalFunction,
        name: approval!.name.trim(),
        approvedOn: approval!.approvedOn || null,
      })),
    references: draft.references
      .filter((r) => r.key.trim())
      .map((r) => ({ type: r.type, key: r.key.trim(), label: text(r.label) })),
  };
}

/**
 * Sum of the entered cost lines while typing, or null when none is entered
 * (not $0) or one is not a valid amount. The saved total is calculated by the API.
 */
export function costTotal(draft: Pick<CarDraft, "materialLoss" | "productionTimeLoss" | "otherCosts">): number | null {
  const entered = COST_LINES.map(({ field }) => draft[field].trim()).filter(Boolean);
  if (entered.some((value) => !MONEY.test(value))) return null;
  return previewTotal(entered);
}

export type Problems = Partial<Record<string, string>>;

/**
 * The checks the API also makes, so problems show on the field before saving.
 * `current` is the saved CAR (null for a new one); unchanged saved values are
 * not re-checked against today's date.
 */
export function draftProblems(
  draft: CarDraft,
  today: string,
  current: Pick<Car, "requestDate" | "dateClosed" | "status" | "actions"> | null,
): Problems {
  const problems: Problems = {};
  if (!draft.subject.trim()) problems.subject = "Enter the subject / issue.";
  if (!draft.requestDate) problems.requestDate = "Enter the request date.";
  else if (draft.requestDate < "2000-01-01") problems.requestDate = "The request date is before 2000.";
  else if (draft.requestDate > today && draft.requestDate !== current?.requestDate)
    problems.requestDate = "The request date cannot be in the future.";
  if (draft.dueDate && draft.requestDate && draft.dueDate < draft.requestDate)
    problems.dueDate = "The due date cannot be before the request date.";
  if (draft.startedTime && !draft.startedOn) problems.startedOn = "Enter the start date for the start time.";
  if (draft.endedTime && !draft.endedOn) problems.endedOn = "Enter the end date for the end time.";
  if (draft.startedOn && draft.endedOn) {
    const start = `${draft.startedOn}T${draft.startedTime || "00:00"}`;
    const end = `${draft.endedOn}T${draft.endedTime || "23:59:59"}`;
    if (end < start) problems.endedOn = "The nonconformity cannot end before it started.";
  }
  for (const { field, label } of COST_LINES) {
    const value = text(draft[field]);
    if (value !== null && !MONEY.test(value)) problems[field] = `${label}: ${MONEY_MESSAGE}`;
  }
  for (const [code, approval] of Object.entries(draft.approvals)) {
    if (approval && !approval.name.trim() && approval.approvedOn)
      problems[`approval.${code}`] = "Enter the approver's name for the approval date.";
    if (approval?.approvedOn && approval.approvedOn > today)
      problems[`approval.${code}`] = "The approval date cannot be in the future.";
  }
  if (!draft.status && current?.status !== null) problems.status = "Choose the CAR status.";
  if (draft.status === "closed") {
    if (current === null) problems.status = "Save the CAR and record its actions before closing it.";
    else if (current.actions.outstanding > 0)
      problems.status = `${current.actions.outstanding} corrective action(s) are not complete. Complete them before closing the CAR.`;
    if (!draft.dateClosed) problems.dateClosed = "Enter the date closed.";
    else if (draft.dateClosed < draft.requestDate)
      problems.dateClosed = "The date closed cannot be before the request date.";
    else if (draft.dateClosed > today && draft.dateClosed !== current?.dateClosed)
      problems.dateClosed = "The date closed cannot be in the future.";
    if (!draft.closureApprovedBy.trim()) problems.closureApprovedBy = "Enter who approved closure.";
    if (!draft.effectivenessResult)
      problems.effectivenessResult = "Record the effectiveness review result before closing.";
    else if (draft.effectivenessResult === "not_effective" && !draft.followUpReference.trim())
      problems.followUpReference = "A CAR found Not Effective needs a follow-up CAR or action reference.";
  } else if (draft.dateClosed) {
    problems.dateClosed = "Only a closed CAR has a date closed. Set the status to Closed or clear the date.";
  }
  return problems;
}

/** The step each field is entered on, to open the step holding a problem. */
export const FIELD_STEP: Record<string, string> = {
  subject: "identify",
  requestDate: "identify",
  requestedBy: "identify",
  assignedTo: "identify",
  dueDate: "identify",
  sourceCode: "identify",
  departmentCode: "identify",
  startedOn: "identify",
  endedOn: "identify",
  previousCar: "identify",
  dispositionCodes: "contain",
  containmentCompletedOn: "contain",
  rootCauseCode: "investigate",
  whySteps: "investigate",
  planCompletedOn: "correct",
  reviewDate: "verify",
  effectivenessResult: "verify",
  followUpReference: "verify",
  materialLoss: "cost",
  productionTimeLoss: "cost",
  otherCosts: "cost",
  qualityCost: "cost",
  recordId: "cost",
  status: "close",
  dateClosed: "close",
  closureApprovedBy: "close",
  approvals: "close",
  references: "related",
};

export function stepOfProblem(field: string): string {
  return FIELD_STEP[field] ?? (field.startsWith("approval.") ? "close" : "identify");
}

// --- Corrective actions ---

export type ActionDraft = {
  action: string;
  owner: string;
  targetDate: string;
  status: ActionFields["status"] | "";
  completedOn: string;
  proceduresRevised: string;
  trainingCompleted: YesNo;
  supportingDocuments: string;
};

export function emptyActionDraft(): ActionDraft {
  return {
    action: "",
    owner: "",
    targetDate: "",
    status: "open",
    completedOn: "",
    proceduresRevised: "",
    trainingCompleted: "",
    supportingDocuments: "",
  };
}

export function actionDraftOf(action: CarAction): ActionDraft {
  return {
    action: action.action,
    owner: action.owner ?? "",
    targetDate: action.targetDate ?? "",
    status: action.status ?? "",
    completedOn: action.completedOn ?? "",
    proceduresRevised: action.proceduresRevised ?? "",
    trainingCompleted: yesNo(action.trainingCompleted),
    supportingDocuments: action.supportingDocuments ?? "",
  };
}

export function actionFieldsOf(draft: ActionDraft): ActionFields {
  return {
    action: draft.action.trim(),
    owner: text(draft.owner),
    targetDate: draft.targetDate || null,
    status: draft.status || "open",
    completedOn: draft.status === "complete" ? draft.completedOn || null : null,
    proceduresRevised: text(draft.proceduresRevised),
    trainingCompleted: fromYesNo(draft.trainingCompleted),
    supportingDocuments: text(draft.supportingDocuments),
  };
}

export function actionProblems(draft: ActionDraft, today: string, current: CarAction | null): Problems {
  const problems: Problems = {};
  if (!draft.action.trim()) problems.action = "Describe the action.";
  if (!draft.status) problems.status = "Choose the action status.";
  if (draft.status === "complete") {
    const importedWithoutDate = current?.status === "complete" && current.completedOn === null;
    if (!draft.completedOn && !importedWithoutDate) problems.completedOn = "Enter the date the action was completed.";
    else if (draft.completedOn > today && draft.completedOn !== current?.completedOn)
      problems.completedOn = "The completion date cannot be in the future.";
  }
  return problems;
}
