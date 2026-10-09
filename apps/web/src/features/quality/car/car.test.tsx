// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getNavItem, moduleItems } from "@/config/navigation";

import {
  canCompleteCarAction,
  carQueryFromParams,
  carQueryParams,
  EMPTY_CAR_QUERY,
  type Car,
  type CarAbilities,
  type CarAction,
  type CarDashboard,
  type CarOptions,
  type CarSummary,
} from "./api";
import {
  actionFieldsOf,
  actionProblems,
  costTotal,
  draftOf,
  draftProblems,
  emptyActionDraft,
  emptyDraft,
  fieldsOf,
} from "./car-draft";
import { CarRecordPage } from "./car-record-page";
import { CarDashboardPage } from "./dashboard-page";
import { CarRegisterPage } from "./register-page";

vi.mock("@/components/common/bar-chart", () => ({
  BarChart: ({ title, categories, series }: { title: string; categories: string[]; series: { name: string; values: (number | null)[] }[] }) => (
    <div data-chart={title} data-categories={categories.join("|")} data-series={series.map((s) => `${s.name}:${s.values.join(",")}`).join("|")} />
  ),
}));

vi.mock("@/features/safety/site-calendar", () => ({ siteToday: () => "2003-03-15" }));

const router = { push: vi.fn(), replace: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const BASE = "/api/v1/quality/cars";

/** Test fixture: a user who may do everything. */
const ALL_ABILITIES: CarAbilities = {
  create: true,
  edit: true,
  assign: true,
  manageActions: true,
  completeAction: true,
  reviewEffectiveness: true,
  approve: true,
  close: true,
  reopen: true,
  admin: true,
  createQualityCost: true,
  linkQualityCost: true,
};

/** Test fixture: a user who may only view. */
const NO_ABILITIES: CarAbilities = Object.fromEntries(
  Object.keys(ALL_ABILITIES).map((key) => [key, false]),
) as CarAbilities;

/** Test fixture, not production data. */
const OPTIONS: CarOptions = {
  sources: [
    { code: "internal_audit", label: "Internal Audit", active: true },
    { code: "customer_complaint", label: "Customer Complaint", active: true },
  ],
  departments: [
    { code: "production", label: "Production", active: true },
    { code: "ca_operation", label: "CA Operation", active: false },
  ],
  rootCauses: [
    { code: "method", label: "Method", active: true },
    { code: "machine", label: "Machine", active: true },
  ],
  dispositions: [
    { code: "hold", label: "Hold", active: true },
    { code: "blended", label: "Blended", active: false },
  ],
  actionStatuses: [
    { code: "open", label: "Open" },
    { code: "in_progress", label: "In Progress" },
    { code: "complete", label: "Complete" },
    { code: "on_hold", label: "On Hold" },
  ],
  effectivenessResults: [
    { code: "effective", label: "Effective" },
    { code: "not_effective", label: "Not Effective" },
  ],
  carStatuses: [
    { code: "open", label: "Open" },
    { code: "closed", label: "Closed" },
  ],
  approvalFunctions: [
    { code: "quality", label: "Quality" },
    { code: "department_supervisor", label: "Department Supervisor" },
  ],
  referenceTypes: [
    { code: "document", label: "Document" },
    { code: "evidence", label: "Evidence" },
  ],
  steps: [
    { code: "identify", label: "Identify" },
    { code: "contain", label: "Contain" },
    { code: "investigate", label: "Investigate" },
    { code: "evaluate", label: "Evaluate" },
    { code: "correct", label: "Correct" },
    { code: "verify", label: "Verify" },
    { code: "cost", label: "Cost" },
    { code: "close", label: "Close" },
  ],
  people: ["Fixture Person"],
  assignees: ["Fixture Person"],
  dueSoonDays: 14,
  canEdit: true,
  canEditCost: true,
  abilities: ALL_ABILITIES,
};

/** Test fixture, not production data. */
const action = (overrides: Partial<CarAction> = {}): CarAction => ({
  id: 31,
  position: 1,
  action: "Fixture action",
  owner: "Fixture Person",
  ownerUserId: "user-fixture",
  targetDate: "2003-03-01",
  status: "open",
  statusLabel: "Open",
  completedOn: null,
  proceduresRevised: null,
  trainingCompleted: null,
  supportingDocuments: null,
  overdue: true,
  version: 1,
  createdAt: "2003-02-10T12:00:00Z",
  createdBy: "fixture-user",
  updatedAt: "2003-02-10T12:00:00Z",
  updatedBy: "fixture-user",
  createdByName: "Fixture Person",
  updatedByName: "Fixture Person",
  ...overrides,
});

/** Test fixture, not production data. */
const summary = (overrides: Partial<CarSummary> = {}): CarSummary => ({
  id: 9,
  carNumber: "Q-2003-001",
  subject: "Fixture mislabelled drum",
  requestedBy: "Fixture Person",
  requestedByUserId: "user-fixture",
  requestDate: "2003-02-10",
  assignedTo: "Fixture Person",
  assignedToUserId: "user-fixture",
  dueDate: "2003-03-01",
  status: "open",
  statusLabel: "Open",
  dateClosed: null,
  sourceCode: "internal_audit",
  sourceLabel: "Internal Audit",
  departmentCode: "production",
  departmentLabel: "Production",
  rootCauseCode: null,
  rootCauseLabel: null,
  effectivenessResult: null,
  effectivenessLabel: null,
  previousOccurrence: true,
  daysOpen: 33,
  pastDue: true,
  dueSoon: false,
  awaitingEffectiveness: false,
  totalCost: "1250.5",
  qualityCostRecordId: null,
  actions: { total: 2, complete: 1, outstanding: 1, overdue: 1 },
  source: "manual",
  ...overrides,
});

/** Test fixture, not production data. */
const car = (overrides: Partial<Car> = {}): Car => {
  const base = summary();
  const draft = fieldsOf(emptyDraft(base.requestDate));
  return {
    ...draft,
    ...base,
    whySteps: [],
    dispositionLabels: [],
    qualityCost: null,
    reviewer: null,
    reviewerUserId: null,
    closureApprovedBy: null,
    closureApprovedByUserId: null,
    approvals: [],
    references: [],
    materialLoss: "1000.5",
    productionTimeLoss: "250",
    otherCosts: null,
    actionItems: [action(), action({ id: 32, position: 2, status: "complete", statusLabel: "Complete", completedOn: "2003-03-02", overdue: false })],
    steps: OPTIONS.steps.map((s) => ({ ...s, state: s.code === "identify" ? "complete" : "not_started" })),
    legacyFields: [],
    migrationNotes: null,
    version: 4,
    createdAt: "2003-02-10T12:00:00Z",
    createdBy: "fixture-user",
    updatedAt: "2003-02-11T12:00:00Z",
    updatedBy: "fixture-user",
    createdByName: "Fixture Person",
    updatedByName: "Fixture Person",
    ...overrides,
  } as Car;
};

/** Test fixture, not production data. */
const DASHBOARD: CarDashboard = {
  today: "2003-03-15",
  year: 2003,
  dueSoonDays: 14,
  kpis: { total: 3, open: 2, pastDue: 1, dueSoon: 1, awaitingEffectiveness: 1, closedYtd: 1, statusNotRecorded: 0, actionsOverdue: 2 },
  byStatus: [
    { code: "open", label: "Open", count: 2 },
    { code: "closed", label: "Closed", count: 1 },
  ],
  byDepartment: [
    { code: null, label: "Not recorded", count: 1 },
    { code: "production", label: "Production", count: 2 },
  ],
  bySource: [{ code: "internal_audit", label: "Internal Audit", count: 3 }],
  byRootCause: [{ code: "method", label: "Method", count: 0 }],
  effectiveness: [
    { code: "effective", label: "Effective", count: 1 },
    { code: "not_effective", label: "Not Effective", count: 0 },
    { code: null, label: "Not recorded", count: 2 },
  ],
  repeat: [
    { code: "yes", label: "Repeat", count: 1 },
    { code: "no", label: "Not a repeat", count: 2 },
  ],
  repeatCars: [{ id: 9, carNumber: "Q-2003-001", subject: "Fixture mislabelled drum", previousCar: "Q-2002-004" }],
  trend: [{ year: 2003, month: 2, opened: 3, closed: 1 }],
  aging: [
    { label: "0-30", minDays: 0, maxDays: 30, count: 1 },
    { label: "31-60", minDays: 31, maxDays: 60, count: 1 },
  ],
  cost: {
    total: "1250.5",
    withCost: 1,
    withoutCost: 2,
    linkedToQualityCost: 0,
    byDepartment: [{ code: "production", label: "Production", total: "1250.5", count: 1 }],
  },
};

/** A record response as the signed-in fixture user. */
const carResponse = (record: Car = car(), abilities: CarAbilities = ALL_ABILITIES, currentUserId = "user-fixture") => ({
  car: record,
  canEdit: abilities.edit,
  canEditCost: abilities.createQualityCost,
  abilities,
  currentUserId,
});

/** Test fixture: the user directory behind the person pickers. */
const DIRECTORY = {
  users: [
    { id: "user-fixture", name: "Fixture Person", active: true },
    { id: "user-other", name: "Fixture Other", active: true },
    { id: "user-former", name: "Fixture Former", active: false },
  ],
};

type Fixture = { status: number; body: unknown };
let responses: Record<string, Fixture>;
let requested: { path: string; init?: RequestInit }[];
let queryClient: QueryClient;
let container: HTMLDivElement;
let root: Root | null = null;

beforeEach(() => {
  requested = [];
  router.push.mockReset();
  router.replace.mockReset();
  responses = {
    [`GET ${BASE}/options`]: { status: 200, body: OPTIONS },
    [`GET ${BASE}`]: { status: 200, body: { cars: [summary()], total: 1, canEdit: true, abilities: ALL_ABILITIES } },
    [`GET ${BASE}/dashboard`]: { status: 200, body: DASHBOARD },
    [`GET ${BASE}/9`]: { status: 200, body: carResponse() },
    [`GET ${BASE}/9/history`]: { status: 200, body: { carId: 9, events: [] } },
    ["GET /api/v1/users/directory"]: { status: 200, body: DIRECTORY },
  };
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  container = document.createElement("div");
  document.body.append(container);
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      requested.push({ path, init });
      const key = `${init?.method ?? "GET"} ${path.split("?")[0]}`;
      const response = responses[key] ?? { status: 404, body: { detail: { message: `No fixture for ${key}` } } };
      return Promise.resolve({ ok: response.status < 400, status: response.status, json: async () => response.body });
    }),
  );
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  container.remove();
  queryClient.clear();
  vi.unstubAllGlobals();
});

async function settle() {
  for (let i = 0; i < 4; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

async function render(page: React.ReactNode) {
  root = createRoot(container);
  await act(async () => root!.render(<QueryClientProvider client={queryClient}>{page}</QueryClientProvider>));
  await settle();
}

function control<T extends HTMLElement>(label: string, scope: ParentNode = container): T {
  const element = [...scope.querySelectorAll("label")].find((l) => l.textContent?.startsWith(label));
  if (!element) throw new Error(`No control labelled ${label}`);
  const target = element.htmlFor ? scope.querySelector<T>(`[id="${element.htmlFor}"]`) : element.querySelector<T>("input, select, textarea");
  if (!target) throw new Error(`No control for ${label}`);
  return target;
}

async function change(element: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement, value: string) {
  await act(async () => {
    const prototype = Object.getPrototypeOf(element) as object;
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(element, value);
    element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
  });
  await settle();
}

async function click(element: Element) {
  await act(async () => (element as HTMLElement).click());
  await settle();
}

const button = (label: string, scope: ParentNode = container) => {
  const found = [...scope.querySelectorAll("button")].find((b) => b.textContent?.trim() === label);
  if (!found) throw new Error(`No button ${label}`);
  return found;
};

const sent = (method: string, path: string) =>
  requested.filter((r) => r.init?.method === method && r.path === path).map((r) => JSON.parse(String(r.init!.body)));

const lastQuery = (path: string) => {
  const found = requested.filter((r) => (r.init?.method ?? "GET") === "GET" && r.path.split("?")[0] === path).at(-1);
  return new URLSearchParams(found?.path.split("?")[1] ?? "");
};

describe("CAR navigation", () => {
  it("adds Dashboard, CAR Register and New CAR under Quality → Corrective Action Reports", () => {
    const quality = moduleItems.find((item) => item.id === "quality")!;
    const group = quality.children!.find((child) => child.id === "quality-cars")!;
    expect(group.label).toBe("Corrective Action Reports");
    expect(group.children!.map((item) => [item.label, item.href])).toEqual([
      ["Dashboard", "/quality/cars"],
      ["CAR Register", "/quality/cars/register"],
      ["+ New CAR", "/quality/cars/new"],
    ]);
    expect(getNavItem("/quality/cars").exact).toBe(true);
    // The Cost of Quality pages are still registered.
    expect(getNavItem("/quality/cost/copq").label).toBe("Cost of Poor Quality");
    expect(getNavItem("/quality/cost/matrix").label).toBe("COQ Matrix");
  });
});

describe("CAR draft", () => {
  it("sends blanks as not recorded, never as zero or No", () => {
    const fields = fieldsOf(emptyDraft("2003-03-15"));
    expect(fields.materialLoss).toBeNull();
    expect(fields.safetyHazard).toBeNull();
    expect(fields.previousOccurrence).toBeNull();
    expect(fields.status).toBe("open");
    expect(fields.whySteps).toEqual([]);
    expect(fields.assignedToUserId).toBeNull();
    expect(fields.assignedTo).toBeNull();
    // Approvals, the reviewer and the closure approver come from the signed-in user, never the form.
    expect(fields).not.toHaveProperty("approvals");
    expect(fields).not.toHaveProperty("reviewer");
    expect(fields).not.toHaveProperty("closureApprovedBy");

    const draft = { ...emptyDraft("2003-03-15"), subject: "  Leak  ", safetyHazard: "no" as const, materialLoss: "0" };
    const filled = fieldsOf(draft);
    expect(filled.subject).toBe("Leak");
    expect(filled.safetyHazard).toBe(false);
    expect(filled.materialLoss).toBe("0");
  });

  it("round-trips a saved CAR without changes", () => {
    const saved = car({ startedTime: "07:30:00", safetyHazard: true, dispositionCodes: ["blended"] });
    const draft = draftOf(saved);
    expect(draft.startedTime).toBe("07:30");
    expect(draft.safetyHazard).toBe("yes");
    expect(draftOf(saved)).toEqual(draft);
    expect(fieldsOf(draft).dispositionCodes).toEqual(["blended"]);
  });

  it("totals the cost lines exactly; nothing entered is not $0", () => {
    const draft = emptyDraft("2003-03-15");
    expect(costTotal(draft)).toBeNull();
    expect(costTotal({ ...draft, materialLoss: "0" })).toBe(0);
    expect(costTotal({ ...draft, materialLoss: "0.1", productionTimeLoss: "0.2" })).toBe(0.3);
    expect(costTotal({ ...draft, materialLoss: "1000.5", otherCosts: "250" })).toBe(1250.5);
    expect(costTotal({ ...draft, materialLoss: "-5" })).toBeNull();
  });

  it("allows saving incomplete work with only the subject and request date", () => {
    const draft = emptyDraft("2003-03-15");
    expect(draftProblems(draft, "2003-03-15", null)).toEqual({ subject: "Enter the subject / issue." });
    expect(draftProblems({ ...draft, subject: "Leak" }, "2003-03-15", null)).toEqual({});
  });

  it("checks dates and amounts", () => {
    const draft = { ...emptyDraft("2003-03-15"), subject: "Leak" };
    expect(draftProblems({ ...draft, dueDate: "2003-03-01", requestDate: "2003-03-10" }, "2003-03-15", null).dueDate).toMatch(/before the request/);
    expect(draftProblems({ ...draft, requestDate: "2003-03-16" }, "2003-03-15", null).requestDate).toMatch(/future/);
    expect(draftProblems({ ...draft, startedTime: "07:00" }, "2003-03-15", null).startedOn).toMatch(/start date/);
    expect(draftProblems({ ...draft, otherCosts: "12,5" }, "2003-03-15", null).otherCosts).toMatch(/amount/);
  });

  it("only closes a CAR whose actions are complete, with effectiveness and date", () => {
    const saved = car();
    const closing = { ...draftOf(saved), status: "closed" as const };
    const problems = draftProblems(closing, "2003-03-15", saved);
    expect(problems.status).toMatch(/1 corrective action\(s\) are not complete/);
    expect(problems.dateClosed).toBe("Enter the date closed.");
    expect(problems.effectivenessResult).toMatch(/effectiveness/);

    const done = { ...saved, actions: { total: 2, complete: 2, outstanding: 0, overdue: 0 } };
    const ready = { ...closing, dateClosed: "2003-03-14", effectivenessResult: "effective" as const };
    expect(draftProblems(ready, "2003-03-15", done)).toEqual({});
    expect(draftProblems({ ...ready, effectivenessResult: "not_effective" }, "2003-03-15", done).followUpReference).toMatch(/follow-up/);
    expect(draftProblems(ready, "2003-03-15", null).status).toMatch(/Save the CAR/);
  });

  it("keeps an imported CAR with no recorded status savable", () => {
    const imported = car({ status: null, statusLabel: "Not recorded" });
    expect(draftProblems(draftOf(imported), "2003-03-15", imported)).toEqual({});
    expect(draftProblems({ ...draftOf(car()), status: "" }, "2003-03-15", car()).status).toMatch(/status/);
  });

  it("requires a completion date to complete an action, except imported ones recorded without", () => {
    const draft = { ...emptyActionDraft(), action: "Retrain", status: "complete" as const };
    expect(actionProblems(draft, "2003-03-15", null).completedOn).toMatch(/completed/);
    const imported = action({ status: "complete", statusLabel: "Complete", completedOn: null });
    expect(actionProblems(draft, "2003-03-15", imported)).toEqual({});
    expect(actionFieldsOf({ ...draft, status: "open", completedOn: "2003-03-01" }).completedOn).toBeNull();
  });

  it("keeps a name recorded before user accounts without matching it to a user", () => {
    const legacy = action({ owner: "J. Smith", ownerUserId: null });
    const saved = car({ assignedTo: "J. Smith", assignedToUserId: null, actionItems: [legacy] });
    const fields = fieldsOf(draftOf(saved));
    expect(fields.assignedToUserId).toBeNull();
    expect(fields.assignedTo).toBe("J. Smith");
    // A chosen user is sent by id; the server records the name.
    const chosen = fieldsOf({ ...draftOf(saved), people: { ...draftOf(saved).people, assignedTo: { userId: "user-other", name: "Fixture Other" } } });
    expect(chosen.assignedToUserId).toBe("user-other");
    expect(chosen.assignedTo).toBeNull();
  });

  it("offers Complete only to the action's owner or a CAR administrator", () => {
    const own = action({ ownerUserId: "user-fixture" });
    const theirs = action({ ownerUserId: "user-other" });
    const worker = { abilities: { ...NO_ABILITIES, completeAction: true }, currentUserId: "user-fixture" };
    expect(canCompleteCarAction(own, worker)).toBe(true);
    expect(canCompleteCarAction(theirs, worker)).toBe(false);
    expect(canCompleteCarAction(action({ ownerUserId: null }), worker)).toBe(false);
    expect(canCompleteCarAction(theirs, { abilities: { ...NO_ABILITIES, admin: true }, currentUserId: "user-fixture" })).toBe(true);
  });
});

describe("CAR register filters in the URL", () => {
  it("round-trips the filters and drops unknown values", () => {
    const query = { ...EMPTY_CAR_QUERY, status: "open", pastDue: true, repeat: "yes" as const, rootCause: "not_recorded" };
    const params = carQueryParams(query);
    expect(params.toString()).toBe("status=open&rootCause=not_recorded&pastDue=true&repeat=true");
    expect(carQueryFromParams(Object.fromEntries(params))).toEqual(query);
    expect(carQueryFromParams({ status: "<script>", from: "yesterday", pastDue: "1" })).toEqual(EMPTY_CAR_QUERY);
  });
});

describe("CAR Register", () => {
  it("lists CARs with derived past due, action progress and cost", async () => {
    await render(<CarRegisterPage title="CAR Register" initial={EMPTY_CAR_QUERY} />);
    const headings = [...container.querySelectorAll("thead th")].map((th) => th.textContent);
    expect(headings).toEqual([
      "CAR Number",
      "Request Date",
      "Subject",
      "Department",
      "Source",
      "Assigned To",
      "Due Date",
      "CAR Status",
      "Actions",
      "Effectiveness",
      "Days Open",
      "Cost Impact",
    ]);
    const row = container.querySelector("tbody tr")!;
    expect(row.textContent).toContain("Q-2003-001");
    expect(row.textContent).toContain("Past due");
    expect(row.textContent).toContain("Repeat");
    expect(row.textContent).toContain("1/2 complete");
    expect(row.textContent).toContain("1 overdue");
    expect(row.textContent).toContain("$1,250.50");
    expect(row.textContent).toContain("Not reviewed");
    expect(container.querySelector('a[href="/quality/cars/register/9"]')).not.toBeNull();
    await click(row.querySelector("td:nth-child(2)")!);
    expect(router.push).toHaveBeenCalledWith("/quality/cars/register/9");
  });

  it("sends every filter to the API", async () => {
    await render(<CarRegisterPage title="CAR Register" initial={EMPTY_CAR_QUERY} />);
    await change(control<HTMLSelectElement>("CAR status"), "not_recorded");
    await change(control<HTMLSelectElement>("Department"), "ca_operation");
    await change(control<HTMLSelectElement>("Source"), "internal_audit");
    await change(control<HTMLSelectElement>("Assigned to"), "Fixture Person");
    await change(control<HTMLSelectElement>("Root cause"), "method");
    await change(control<HTMLSelectElement>("Effectiveness"), "effective");
    await change(control<HTMLSelectElement>("Past due"), "true");
    await change(control<HTMLSelectElement>("Previous / repeat"), "no");
    await change(control<HTMLInputElement>("Requested from"), "2003-01-01");
    await change(control<HTMLInputElement>("Requested to"), "2003-02-28");
    await change(control<HTMLInputElement>("Search"), "drum");
    const params = lastQuery(BASE);
    expect(Object.fromEntries(params)).toEqual({
      status: "not_recorded",
      department: "ca_operation",
      source: "internal_audit",
      assignedTo: "Fixture Person",
      rootCause: "method",
      effectiveness: "effective",
      pastDue: "true",
      repeat: "false",
      from: "2003-01-01",
      to: "2003-02-28",
      search: "drum",
    });
    expect(window.location.search).toContain("pastDue=true");
  });

  it("shows an empty state, not invented rows, when there are no CARs", async () => {
    responses[`GET ${BASE}`] = { status: 200, body: { cars: [], total: 0, canEdit: true, abilities: ALL_ABILITIES } };
    await render(<CarRegisterPage title="CAR Register" initial={EMPTY_CAR_QUERY} />);
    expect(container.textContent).toContain("No Corrective Action Reports yet");
    expect(container.querySelector("tbody")).toBeNull();
  });

  it("scrolls the table sideways on narrow screens", async () => {
    await render(<CarRegisterPage title="CAR Register" initial={EMPTY_CAR_QUERY} />);
    expect(container.querySelector("table")!.parentElement!.className).toContain("overflow-x-auto");
  });
});

describe("CAR dashboard", () => {
  it("shows the API's KPIs and charts", async () => {
    await render(<CarDashboardPage title="Corrective Action Reports" />);
    const card = (label: string) =>
      [...container.querySelectorAll("p")].find((p) => p.textContent === label)!.closest("div.rounded-lg")!.textContent;
    expect(card("Open CARs")).toContain("2");
    expect(card("Past due")).toContain("2 corrective actions overdue");
    expect(card("Due soon")).toContain("Due within 14 days");
    expect(card("Awaiting effectiveness")).toContain("1");
    expect(card("Closed YTD")).toContain("Closed in 2003");
    const chart = (title: string) => container.querySelector(`[data-chart="${title}"]`)!;
    expect(chart("CARs by department").getAttribute("data-categories")).toBe("Production|Not recorded");
    expect(chart("CARs by root cause").getAttribute("data-categories")).toBe("");
    expect(chart("Opened vs closed").getAttribute("data-series")).toBe("Opened:3|Closed:1");
    expect(chart("Aging of CARs not closed").getAttribute("data-series")).toBe("CARs:1,1");
    expect(chart("Cost impact by department").getAttribute("data-series")).toBe("Cost impact ($):1250.5");
    expect(container.querySelector('a[href="/quality/cars/register?pastDue=true"]')).not.toBeNull();
    expect(container.textContent).toContain("Repeat CARs");
  });

  it("passes the filters to the dashboard and shows an empty state with no CARs", async () => {
    responses[`GET ${BASE}/dashboard`] = {
      status: 200,
      body: { ...DASHBOARD, kpis: { ...DASHBOARD.kpis, total: 0 } },
    };
    await render(<CarDashboardPage title="Corrective Action Reports" />);
    expect(container.textContent).toContain("No Corrective Action Reports yet");
    await change(control<HTMLSelectElement>("Department"), "production");
    expect(lastQuery(`${BASE}/dashboard`).get("department")).toBe("production");
    expect(container.textContent).toContain("No CARs match these filters");
  });
});

describe("CAR record", () => {
  it("creates a CAR from the subject and request date alone", async () => {
    responses[`POST ${BASE}`] = { status: 201, body: carResponse(car({ id: 10, carNumber: "Q-2003-002" })) };
    await render(<CarRecordPage id={null} />);
    expect(container.textContent).toContain("New Corrective Action Report");
    await click(button("Create CAR"));
    expect(container.textContent).toContain("Enter the subject / issue.");
    expect(sent("POST", BASE)).toEqual([]);

    await change(control<HTMLInputElement>("Subject / issue"), "Fixture leak");
    await click(button("Create CAR"));
    const [body] = sent("POST", BASE);
    expect(body.subject).toBe("Fixture leak");
    expect(body.requestDate).toBe("2003-03-15");
    expect(body.status).toBe("open");
    expect(body.materialLoss).toBeNull();
    expect(router.replace).toHaveBeenCalledWith("/quality/cars/register/10");
  });

  it("opens at the overview and edits a step with the loaded version", async () => {
    responses[`PUT ${BASE}/9`] = {
      status: 200,
      body: carResponse(car({ version: 5, assignedTo: "Fixture Other", assignedToUserId: "user-other" })),
    };
    await render(<CarRecordPage id={9} />);
    expect(container.textContent).toContain("Q-2003-001");
    expect(container.textContent).toContain("Progress");
    expect(button("Save CAR").disabled).toBe(true);

    await click(button("1 Identify"));
    const assignee = control<HTMLSelectElement>("Assigned to");
    // Inactive users are not offered for new assignments.
    expect([...assignee.options].map((o) => o.textContent)).toEqual(["Not recorded", "Fixture Person", "Fixture Other"]);
    await change(assignee, "user-other");
    expect(container.textContent).toContain("Unsaved changes");
    await click(button("Save CAR"));
    const [body] = sent("PUT", `${BASE}/9`);
    expect(body.version).toBe(4);
    expect(body.assignedToUserId).toBe("user-other");
    expect(body.assignedTo).toBeNull();
    // The browser never sends who created or changed the record.
    expect(body).not.toHaveProperty("updatedBy");
    expect(body).not.toHaveProperty("createdBy");
    expect(container.textContent).toContain("Saved");
  });

  it("keeps a name recorded before user accounts selectable, labelled as such", async () => {
    responses[`GET ${BASE}/9`] = {
      status: 200,
      body: carResponse(car({ assignedTo: "J. Smith", assignedToUserId: null })),
    };
    await render(<CarRecordPage id={9} />);
    await click(button("1 Identify"));
    const assignee = control<HTMLSelectElement>("Assigned to");
    expect(assignee.selectedOptions[0].textContent).toBe("J. Smith (recorded before user accounts)");
  });

  it("opens the step of a field the API refused", async () => {
    responses[`PUT ${BASE}/9`] = {
      status: 422,
      body: { detail: { error: "invalid_department", message: "Choose a department from the list.", field: "departmentCode" } },
    };
    await render(<CarRecordPage id={9} />);
    await click(button("7 Cost"));
    await change(control<HTMLInputElement>("Other costs ($)"), "10");
    expect(container.textContent).toContain("Total cost impact: $1,260.50");
    await click(button("Save CAR"));
    expect(container.querySelector('[aria-current="step"]')!.textContent).toContain("1 Identify");
    expect(container.textContent).toContain("Choose a department from the list.");
  });

  it("offers to reload after an edit conflict", async () => {
    responses[`PUT ${BASE}/9`] = { status: 409, body: { detail: { error: "edit_conflict", message: "This CAR was changed by someone else since you loaded it. Nothing was saved." } } };
    await render(<CarRecordPage id={9} />);
    await click(button("1 Identify"));
    await change(control<HTMLSelectElement>("Assigned to"), "user-other");
    await click(button("Save CAR"));
    expect(container.textContent).toContain("changed by someone else");
    await click(button("Discard my changes and load the latest"));
    expect(control<HTMLSelectElement>("Assigned to").value).toBe("user-fixture");
  });

  it("does not close a CAR with outstanding actions", async () => {
    await render(<CarRecordPage id={9} />);
    await click(button("8 Close"));
    expect(container.textContent).toContain("1 of 2 actions complete");
    await change(control<HTMLSelectElement>("CAR status"), "closed");
    await click(button("Save CAR"));
    expect(container.textContent).toContain("1 corrective action(s) are not complete");
    expect(sent("PUT", `${BASE}/9`)).toEqual([]);
  });

  it("adds, edits and completes corrective actions on their own", async () => {
    const updated = carResponse();
    responses[`POST ${BASE}/9/actions`] = { status: 201, body: updated };
    responses[`PUT ${BASE}/9/actions/31`] = { status: 200, body: updated };
    responses[`POST ${BASE}/9/actions/31/complete`] = { status: 200, body: updated };
    await render(<CarRecordPage id={9} />);
    await click(button("5 Correct"));
    expect(container.textContent).toContain("1 of 2 complete");
    expect(container.textContent).toContain("Overdue");

    await click(button("Add action"));
    const dialog = () => container.querySelector("dialog[open]")!;
    await change(control<HTMLTextAreaElement>("Action", dialog()), "Fixture new action");
    await click(button("Add action", dialog()));
    expect(sent("POST", `${BASE}/9/actions`)).toEqual([
      expect.objectContaining({ action: "Fixture new action", status: "open", completedOn: null }),
    ]);

    await click(button("Edit"));
    await change(control<HTMLSelectElement>("Responsible", dialog()), "user-other");
    await click(button("Save action", dialog()));
    expect(sent("PUT", `${BASE}/9/actions/31`)).toEqual([
      expect.objectContaining({ ownerUserId: "user-other", owner: null, version: 1 }),
    ]);

    await click(button("Complete"));
    expect(dialog().textContent).toContain("does not record the CAR's effectiveness review");
    await click(button("Mark complete", dialog()));
    expect(sent("POST", `${BASE}/9/actions/31/complete`)).toEqual([{ version: 1, completedOn: "2003-03-15" }]);
  });

  it("links the CAR to Quality Cost only when there are no unsaved edits", async () => {
    responses[`GET ${BASE}/9`] = {
      status: 200,
      body: carResponse(
        car({
          qualityCostRecordId: 7,
          qualityCost: {
            id: 7,
            recordNumber: "QC-00007",
            title: "Q-2003-001 Fixture mislabelled drum",
            coqClassLabel: "Internal Failure",
            totalCost: "1250.5",
            financialStatusLabel: "Potential",
            statusLabel: "Open",
          },
        }),
      ),
    };
    await render(<CarRecordPage id={9} />);
    await click(button("7 Cost"));
    expect(container.textContent).toContain("QC-00007");
    expect(button("Remove link").disabled).toBe(false);
    await change(control<HTMLInputElement>("Other costs ($)"), "5");
    expect(button("Remove link").disabled).toBe(true);
    expect(container.textContent).toContain("Save the CAR before changing its Quality Cost link.");
  });

  it("is read-only without edit permission", async () => {
    responses[`GET ${BASE}/9`] = { status: 200, body: carResponse(car(), NO_ABILITIES) };
    await render(<CarRecordPage id={9} />);
    expect(container.textContent).toContain("Editing it needs the car.edit permission");
    expect([...container.querySelectorAll("button")].some((b) => b.textContent?.includes("Save CAR"))).toBe(false);
    await click(button("1 Identify"));
    expect(control<HTMLInputElement>("Subject / issue").closest("fieldset")!.disabled).toBe(true);
    await click(button("5 Correct"));
    expect(control<HTMLTextAreaElement>("Procedures revised").closest("fieldset")!.disabled).toBe(true);
    expect([...container.querySelectorAll("button")].some((b) => b.textContent === "Complete")).toBe(false);
    await click(button("8 Close"));
    expect([...container.querySelectorAll("button")].some((b) => b.textContent?.startsWith("Approve as"))).toBe(false);
  });

  it("lets an action owner complete their own action without CAR edit permission", async () => {
    const worker = { ...NO_ABILITIES, completeAction: true };
    responses[`GET ${BASE}/9`] = { status: 200, body: carResponse(car(), worker) };
    responses[`POST ${BASE}/9/actions/31/complete`] = { status: 200, body: carResponse(car(), worker) };
    await render(<CarRecordPage id={9} />);
    await click(button("5 Correct"));
    expect([...container.querySelectorAll("button")].some((b) => b.textContent === "Add action")).toBe(false);
    await click(button("Complete"));
    await click(button("Mark complete", container.querySelector("dialog[open]")!));
    expect(sent("POST", `${BASE}/9/actions/31/complete`)).toEqual([{ version: 1, completedOn: "2003-03-15" }]);
  });

  it("records approvals as the signed-in user, never a typed name", async () => {
    const approver = { ...NO_ABILITIES, approve: true };
    responses[`GET ${BASE}/9`] = { status: 200, body: carResponse(car(), approver) };
    responses[`POST ${BASE}/9/approvals`] = { status: 200, body: carResponse(car(), approver) };
    await render(<CarRecordPage id={9} />);
    await click(button("8 Close"));
    await click(button("Approve as Quality"));
    expect(sent("POST", `${BASE}/9/approvals`)).toEqual([{ version: 4, functionCode: "quality" }]);
  });

  it("keeps step navigation usable on narrow screens", async () => {
    await render(<CarRecordPage id={9} />);
    const list = container.querySelector('nav[aria-label="CAR steps"] ol')!;
    expect(list.className).toContain("overflow-x-auto");
    expect(list.className).toContain("lg:flex-col");
    expect([...list.querySelectorAll("button")].map((b) => b.textContent)).toEqual([
      "Overview",
      "1 Identify",
      "2 Contain",
      "3 Investigate",
      "4 Evaluate",
      "5 Correct",
      "6 Verify",
      "7 Cost",
      "8 Close",
      "Evidence & related",
      "History",
    ]);
  });
});
