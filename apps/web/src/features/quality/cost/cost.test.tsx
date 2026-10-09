// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getNavItem, moduleItems } from "@/config/navigation";

import {
  COST_FIELDS,
  type CostMonth,
  type CostRecord,
  type CostRecordOptions,
  type CostSummary,
  type Estimate,
  type EstimatorReference,
} from "./api";
import { CopqPage } from "./copq-page";
import { buildEstimateRequest } from "./estimator";
import { CoqMatrixPage } from "./matrix-page";
import { draftProblems, emptyDraft, fieldsOf, previewTotal } from "./record-form";
import { CostRegisterPage } from "./register-page";

vi.mock("@/components/common/bar-chart", () => ({
  BarChart: ({ title, categories, series, lines }: { title: string; categories: string[]; series: { name: string; values: (number | null)[] }[]; lines?: { name: string; values: (number | null)[] }[] }) => (
    <div data-chart={title} data-categories={categories.join("|")} data-series={[...series, ...(lines ?? [])].map((s) => `${s.name}:${s.values.join(",")}`).join("|")} />
  ),
}));

vi.mock("@/features/safety/site-calendar", () => ({ siteToday: () => "2003-03-15" }));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/** Test fixture, not production data. */
const OPTIONS: CostRecordOptions = {
  areas: [
    { id: 1, code: "FX-A", name: "Fixture Area A", active: true },
    { id: 2, code: "FX-B", name: "Fixture Area B", active: false },
  ],
  classes: [
    { code: "prevention", label: "Prevention", qualityGroup: "good", categories: [{ code: "prevention.training", label: "Training" }] },
    { code: "appraisal", label: "Appraisal", qualityGroup: "good", categories: [{ code: "appraisal.testing", label: "Testing" }] },
    { code: "internal_failure", label: "Internal Failure", qualityGroup: "poor", categories: [{ code: "internal_failure.scrap", label: "Scrap" }] },
    { code: "external_failure", label: "External Failure", qualityGroup: "poor", categories: [{ code: "external_failure.complaint", label: "Customer complaint" }] },
  ],
  financialStatuses: [
    { code: "potential", label: "Potential", confirmed: false },
    { code: "validating", label: "Validating", confirmed: false },
    { code: "confirmed", label: "Confirmed", confirmed: true },
    { code: "closed", label: "Closed", confirmed: true },
  ],
  operationalStatuses: [
    { code: "open", label: "Open" },
    { code: "under_review", label: "Under Review" },
    { code: "action_required", label: "Action Required" },
    { code: "monitoring", label: "Monitoring" },
    { code: "closed", label: "Closed" },
  ],
  costComponents: COST_FIELDS.map((field) => ({ field, label: `Fixture ${field}` })),
  referenceTypes: [{ code: "reference", label: "Reference / document number" }],
  products: ["FX-PRODUCT"],
  owners: ["Fixture Owner"],
  canEdit: true,
};

/** Test fixture, not production data. */
const record = (overrides: Partial<CostRecord> = {}): CostRecord => ({
  id: 7,
  recordNumber: "QC-00007",
  recordDate: "2003-02-10",
  title: "Fixture scrap event",
  areaId: 1,
  areaName: "Fixture Area A",
  coqClass: "internal_failure",
  coqClassLabel: "Internal Failure",
  qualityGroup: "poor",
  categoryCode: "internal_failure.scrap",
  categoryLabel: "Scrap",
  description: "Fixture description.",
  product: "FX-PRODUCT",
  campaign: null,
  lot: "FX-LOT-1",
  location: null,
  process: null,
  equipment: null,
  counterparty: null,
  owner: "Fixture Owner",
  notes: null,
  financialStatus: "confirmed",
  financialStatusLabel: "Confirmed",
  costConfirmed: true,
  status: "open",
  statusLabel: "Open",
  dueDate: null,
  dateClosed: null,
  resolutionNotes: null,
  recoveredCost: "100",
  avoidedCost: null,
  ...(Object.fromEntries(COST_FIELDS.map((field) => [field, null])) as Record<(typeof COST_FIELDS)[number], null>),
  materialCost: "1000",
  totalCost: "1000",
  netCost: "900",
  overdue: false,
  daysOpen: 33,
  references: [],
  source: "manual",
  version: 1,
  createdAt: "2003-02-10T12:00:00Z",
  createdBy: "fixture-user",
  updatedAt: "2003-02-10T12:00:00Z",
  updatedBy: "fixture-user",
  ...overrides,
});

const NONE = { prevention: null, appraisal: null, internal_failure: null, external_failure: null };

/** Test fixture, not production data. */
const month = (overrides: Partial<CostMonth> & { month: number }): CostMonth => ({
  confirmed: NONE,
  potential: NONE,
  good: null,
  poor: null,
  poorPotential: null,
  netPoor: null,
  recordCount: 0,
  productionLbs: null,
  salesRevenue: null,
  copqPctOfSales: null,
  ...overrides,
});

const figures = (overrides: Partial<CostSummary["copq"]["figures"]> = {}) => ({
  count: 0,
  confirmedCount: 0,
  potentialCount: 0,
  noCostCount: 0,
  confirmed: null,
  potential: null,
  totalExposure: null,
  recovered: null,
  avoided: null,
  net: null,
  ...overrides,
});

/** Test fixture, not production data. */
const SUMMARY: CostSummary = {
  year: 2003,
  fromMonth: 1,
  throughMonth: 2,
  availableYears: [2003],
  latestMonth: 2,
  classes: [
    { code: "prevention", label: "Prevention", qualityGroup: "good", figures: figures(), shareOfTotal: null },
    { code: "appraisal", label: "Appraisal", qualityGroup: "good", figures: figures(), shareOfTotal: null },
    {
      code: "internal_failure",
      label: "Internal Failure",
      qualityGroup: "poor",
      figures: figures({ count: 2, confirmedCount: 1, potentialCount: 1, confirmed: "1000", potential: "400", recovered: "100", net: "900" }),
      shareOfTotal: null,
    },
    {
      code: "external_failure",
      label: "External Failure",
      qualityGroup: "poor",
      figures: figures({ count: 1, confirmedCount: 1, confirmed: "100", net: "100" }),
      shareOfTotal: null,
    },
  ],
  matrix: { good: null, poor: "1100", total: null, poorPct: null, goodPotential: null, poorPotential: "400", totalPotential: null },
  copq: {
    figures: figures({ count: 3, confirmedCount: 2, potentialCount: 1, confirmed: "1100", potential: "400", recovered: "100", net: "1000" }),
    openCount: 2,
    overdueCount: 1,
    productionLbs: "1000000",
    salesRevenue: "100000",
    internalCostPerLb: "0.001",
    copqPctOfSales: "0.011",
  },
  months: [
    month({ month: 1, confirmed: { ...NONE, internal_failure: "1000" }, poor: "1000", netPoor: "900", recordCount: 1 }),
    month({ month: 2, confirmed: { ...NONE, external_failure: "100" }, potential: { ...NONE, internal_failure: "400" }, poor: "100", poorPotential: "400", netPoor: "100", recordCount: 2 }),
    ...Array.from({ length: 10 }, (_, index) => month({ month: index + 3 })),
  ],
  categories: [
    { coqClass: "internal_failure", code: "internal_failure.scrap", label: "Scrap", figures: figures({ count: 2, confirmed: "1000", potential: "400" }), shareOfClass: "1", cumulativeShareOfPoor: "0.909" },
    { coqClass: "external_failure", code: "external_failure.complaint", label: "Customer complaint", figures: figures({ count: 1, confirmed: "100" }), shareOfClass: "1", cumulativeShareOfPoor: "1" },
  ],
  aging: [
    { label: "0–30 days", minDays: 0, maxDays: 30, count: 1, exposure: "400" },
    { label: "31–60 days", minDays: 31, maxDays: 60, count: 1, exposure: "1000" },
    { label: "61–90 days", minDays: 61, maxDays: 90, count: 0, exposure: null },
    { label: "Over 90 days", minDays: 91, maxDays: null, count: 0, exposure: null },
  ],
  dataChecks: [{ status: "info", message: "Fixture: 1 record has Potential status." }],
  definitions: [{ term: "Fixture term", definition: "Fixture definition." }],
};

/** Test fixture, not production data. */
const REFERENCE: EstimatorReference = {
  source: "Fixture estimator workbook",
  products: [{ code: "FX1", standardRateMtPerDay: "100" }],
  packageTypes: ["Bags", "Box"],
  assumptions: [{ label: "Fixture margin", value: "1", unit: "USD per MT" }],
  guidance: ["Fixture guidance."],
  notes: ["Fixture note."],
};

/** Test fixture, not production data. */
const ESTIMATE: Estimate = {
  lines: [
    { code: "scrap", label: "Scrap", totalKusd: "1.5", formula: "Fixture formula", steps: [{ label: "Quantity", value: "2000", unit: "lb" }] },
  ],
  totalKusd: "1.5",
  totalUsd: "1500",
  warnings: [],
  source: "Fixture estimator workbook",
};

const BASE = "/api/v1/quality/cost";

let container: HTMLDivElement;
let queryClient: QueryClient;
let root: Root | null = null;
let requested: { path: string; init?: RequestInit }[] = [];
let responses: Record<string, { status: number; body: unknown }>;

beforeEach(() => {
  requested = [];
  responses = {
    [`GET ${BASE}/summary`]: { status: 200, body: SUMMARY },
    [`GET ${BASE}/records/options`]: { status: 200, body: OPTIONS },
    [`GET ${BASE}/records`]: { status: 200, body: { records: [record()], total: 1, canEdit: true } },
    [`GET ${BASE}/records/7`]: { status: 200, body: { record: record(), canEdit: true } },
    [`GET ${BASE}/records/7/history`]: { status: 200, body: { recordId: 7, events: [] } },
    [`POST ${BASE}/records`]: { status: 201, body: { record: record({ id: 8, recordNumber: "QC-00008" }), canEdit: true } },
    [`GET ${BASE}/records/8`]: { status: 200, body: { record: record({ id: 8, recordNumber: "QC-00008" }), canEdit: true } },
    [`GET ${BASE}/estimator`]: { status: 200, body: REFERENCE },
    [`POST ${BASE}/estimate`]: { status: 200, body: ESTIMATE },
  };
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  container = document.createElement("div");
  document.body.append(container);
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      requested.push({ path, init });
      const key = `${init?.method ?? "GET"} ${path.split("?")[0]}`;
      const response = responses[key] ?? { status: 404, body: { message: `No fixture for ${key}` } };
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
  for (let i = 0; i < 3; i += 1) {
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

const text = (selector: string) => container.querySelector(selector)?.textContent ?? "";
const paths = (prefix: string) => requested.map((r) => r.path).filter((path) => path.startsWith(prefix));

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

describe("Quality navigation", () => {
  it("lists the register and both cost dashboards under Quality", () => {
    const quality = moduleItems.find((item) => item.id === "quality")!;
    const area = quality.children!.find((child) => child.id === "quality-cost")!;
    expect(area.children!.map((child) => child.href)).toEqual([
      "/quality/cost/register",
      "/quality/cost/copq",
      "/quality/cost/matrix",
    ]);
    expect(area.children!.every((child) => !child.fixture)).toBe(true);
    expect(getNavItem("/quality/raw-materials/moisture").fixture).toBe(true);
  });
});

describe("Quality cost entry form helpers", () => {
  it("adds decimals exactly and keeps blank apart from zero", () => {
    expect(previewTotal(["0.1", "0.2", ""])).toBe(0.3);
    expect(previewTotal(["", " "])).toBeNull();
    expect(previewTotal(["0"])).toBe(0);
    expect(previewTotal(["-5", "abc"])).toBeNull();
  });

  it("reports missing required fields, negatives and closing rules", () => {
    const draft = emptyDraft("2003-03-15");
    expect(Object.keys(draftProblems(draft, "2003-03-15", true)).sort()).toEqual(
      ["areaId", "categoryCode", "coqClass", "description", "title"].sort(),
    );
    const filled = {
      ...draft,
      title: "T",
      description: "D",
      areaId: "1",
      coqClass: "internal_failure" as const,
      categoryCode: "internal_failure.scrap",
    };
    expect(draftProblems(filled, "2003-03-15", true)).toEqual({});
    expect(draftProblems({ ...filled, materialCost: "-1" }, "2003-03-15", true)).toHaveProperty("materialCost");
    expect(draftProblems({ ...filled, recordDate: "2003-03-16" }, "2003-03-15", true)).toHaveProperty("recordDate");
    expect(draftProblems({ ...filled, status: "closed" }, "2003-03-15", true)).toHaveProperty("dateClosed");
    expect(draftProblems({ ...filled, status: "closed", dateClosed: "2003-03-15" }, "2003-03-15", true)).toEqual({});
    expect(draftProblems({ ...filled, recordDate: "2003-03-10", status: "closed", dateClosed: "2003-03-01" }, "2003-03-15", true)).toHaveProperty("dateClosed");
  });

  it("sends blanks as null, zero as zero and date closed only when closed", () => {
    const body = fieldsOf({
      ...emptyDraft("2003-03-15", "internal_failure"),
      title: " T ",
      materialCost: "0",
      laborCost: " ",
      dateClosed: "2003-03-01",
      reference: " NCR-1 ",
    });
    expect(body.materialCost).toBe("0");
    expect(body.laborCost).toBeNull();
    expect(body.product).toBeNull();
    expect(body.dateClosed).toBeNull();
    expect(body.references).toEqual([{ type: "reference", key: "NCR-1", label: null }]);
  });
});

describe("Quality Cost Register", () => {
  it("lists records with the register columns and a stable record ID", async () => {
    await render(<CostRegisterPage title="Quality Cost Register" />);

    const headings = [...container.querySelectorAll("thead th")].map((th) => th.textContent);
    expect(headings).toEqual([
      "Record ID",
      "Date",
      "Title",
      "Area",
      "COQ classification",
      "Category",
      "Product",
      "Lot",
      "Owner",
      "Financial status",
      "Total cost",
      "Recovered",
      "Net cost",
      "Status",
      "Days open",
    ]);
    const row = container.querySelector("tbody tr")!.textContent;
    expect(row).toContain("QC-00007");
    expect(row).toContain("Feb 10, 2003");
    expect(row).toContain("$1,000.00");
    expect(row).toContain("$900.00");
  });

  it("sends the filters to the API", async () => {
    await render(<CostRegisterPage title="Quality Cost Register" />);
    await change(control<HTMLSelectElement>("COQ class"), "external_failure");
    await change(control<HTMLSelectElement>("Financial status"), "potential");
    await change(control<HTMLSelectElement>("Status"), "open");

    const last = paths(`${BASE}/records?`).at(-1)!;
    expect(last).toContain("coqClass=external_failure");
    expect(last).toContain("financialStatus=potential");
    expect(last).toContain("status=open");
  });

  it("shows an empty state, not zeros, when there are no records", async () => {
    responses[`GET ${BASE}/records`] = { status: 200, body: { records: [], total: 0, canEdit: true } };
    await render(<CostRegisterPage title="Quality Cost Register" />);

    expect(container.textContent).toContain("No quality cost items yet");
    expect(container.querySelector("table")).toBeNull();
  });

  it("hides the add button from users who cannot edit", async () => {
    responses[`GET ${BASE}/records/options`] = { status: 200, body: { ...OPTIONS, canEdit: false } };
    await render(<CostRegisterPage title="Quality Cost Register" />);

    expect(container.textContent).not.toContain("Add Quality Cost Item");
  });

  it("adds an item through the shared form and shows it", async () => {
    await render(<CostRegisterPage title="Quality Cost Register" />);
    await click(button("Add Quality Cost Item"));

    const form = container.querySelector<HTMLFormElement>('form[aria-label="Add quality cost item"]')!;
    expect(form).not.toBeNull();
    await click(button("Add quality cost item", form));
    expect(form.textContent).toContain("Check the highlighted fields");
    expect(requested.some((r) => r.init?.method === "POST")).toBe(false);

    await change(control<HTMLInputElement>("Title", form), "Fixture title");
    await change(control<HTMLTextAreaElement>("Description", form), "Fixture description");
    await change(control<HTMLSelectElement>("Area", form), "1");
    await click([...form.querySelectorAll('[role="radio"]')].find((r) => r.textContent?.startsWith("Internal Failure"))!);
    await change(control<HTMLSelectElement>("Category", form), "internal_failure.scrap");
    await change(control<HTMLInputElement>("Fixture materialCost", form), "1000.50");
    await change(control<HTMLInputElement>("Fixture laborCost", form), "0");
    expect(form.textContent).toContain("Estimated total cost$1,000.50");
    await click(button("Add quality cost item", form));

    const post = requested.find((r) => r.init?.method === "POST")!;
    const body = JSON.parse(String(post.init!.body));
    expect(body).toMatchObject({
      title: "Fixture title",
      areaId: 1,
      coqClass: "internal_failure",
      categoryCode: "internal_failure.scrap",
      materialCost: "1000.50",
      laborCost: "0",
      testingCost: null,
      financialStatus: "potential",
      status: "open",
    });
    expect(container.textContent).toContain("Added QC-00008.");
    expect(container.querySelector("dialog[open] h2")!.textContent).toBe("Quality cost item");
  });

  it("shows a server rule refusal on its field", async () => {
    responses[`POST ${BASE}/records`] = {
      status: 422,
      body: { detail: { error: "category_mismatch", message: "Fixture: category does not belong to the class.", field: "categoryCode" } },
    };
    await render(<CostRegisterPage title="Quality Cost Register" />);
    await click(button("Add Quality Cost Item"));
    const form = container.querySelector<HTMLFormElement>("form")!;
    await change(control<HTMLInputElement>("Title", form), "T");
    await change(control<HTMLTextAreaElement>("Description", form), "D");
    await change(control<HTMLSelectElement>("Area", form), "1");
    await click([...form.querySelectorAll('[role="radio"]')].find((r) => r.textContent?.startsWith("Prevention"))!);
    await change(control<HTMLSelectElement>("Category", form), "prevention.training");
    await click(button("Add quality cost item", form));

    expect(form.querySelector('[role="alert"]')!.textContent).toContain("category does not belong");
    expect(control<HTMLSelectElement>("Category", form).getAttribute("aria-invalid")).toBe("true");
  });

  it("opens a record's detail from its row, with audit metadata", async () => {
    await render(<CostRegisterPage title="Quality Cost Register" />);
    await click(container.querySelector("tbody tr")!);

    const dialog = container.querySelector("dialog[open]")!;
    expect(dialog.textContent).toContain("Fixture scrap event");
    for (const section of ["Identification", "Classification", "Cost breakdown", "Recovery and avoidance", "Related records and notes", "Audit"]) {
      expect(dialog.textContent).toContain(section);
    }
    expect(dialog.textContent).toContain("by fixture-user");
    expect(paths(`${BASE}/records/7`)).toContain(`${BASE}/records/7`);

    await click(button("Edit", dialog));
    expect(dialog.querySelector('form[aria-label="Edit quality cost item"]')).not.toBeNull();
    expect(control<HTMLInputElement>("Title", dialog).value).toBe("Fixture scrap event");
  });
});

describe("Cost of Poor Quality", () => {
  it("reports confirmed COPQ and potential exposure separately", async () => {
    await render(<CopqPage title="Cost of Poor Quality" />);

    expect(paths(`${BASE}/summary`)[0]).toBe(`${BASE}/summary?poorOnly=true`);
    const kpis = text('section[aria-label="Cost of Poor Quality"]');
    expect(kpis).toContain("Confirmed COPQ$1,100");
    expect(kpis).toContain("Potential exposure$400");
    expect(kpis).toContain("Net COPQ$1,000");
    expect(kpis).toContain("COPQ % of sales1.10%");
    expect(kpis).toContain("Open items2");
  });

  it("charts the category Pareto and the monthly trend from the records", async () => {
    await render(<CopqPage title="Cost of Poor Quality" />);

    const pareto = container.querySelector('[data-chart="COPQ Pareto by category"]')!;
    expect(pareto.getAttribute("data-categories")).toBe("Scrap|Customer complaint");
    expect(pareto.getAttribute("data-series")).toBe(
      "Internal failure:1000,|External failure:,100|Potential exposure:400,|Cumulative %:90.9,100",
    );
    const trend = container.querySelector('[data-chart="Monthly COPQ trend"]')!;
    expect(trend.getAttribute("data-series")).toBe("Internal failure:1000,|External failure:,100|Potential exposure:,400");
  });

  it("lists open failure items for the period", async () => {
    await render(<CopqPage title="Cost of Poor Quality" />);

    const open = paths(`${BASE}/records?`).at(-1)!;
    expect(open).toContain("from=2003-01-01");
    expect(open).toContain("to=2003-02-28");
    expect(open).toContain("coqClass=internal_failure&coqClass=external_failure");
    expect(open).toContain("open=true");
    expect(text('section[aria-labelledby="copq-open"]')).toContain("QC-00007");
  });

  it("offers only the failure classes in the class filter", async () => {
    await render(<CopqPage title="Cost of Poor Quality" />);

    const classes = [...control<HTMLSelectElement>("COQ class").options].map((o) => o.value);
    expect(classes).toEqual(["", "internal_failure", "external_failure"]);
  });

  it("explains a missing permission without a retry", async () => {
    responses[`GET ${BASE}/summary`] = { status: 403, body: {} };
    await render(<CopqPage title="Cost of Poor Quality" />);

    expect(container.textContent).toContain("Cost of Quality data is not available to you");
    expect([...container.querySelectorAll("button")].some((b) => b.textContent === "Retry")).toBe(false);
  });

  it("shows an empty state rather than zeros when there are no records", async () => {
    responses[`GET ${BASE}/summary`] = {
      status: 200,
      body: { ...SUMMARY, year: null, availableYears: [], latestMonth: null },
    };
    await render(<CopqPage title="Cost of Poor Quality" />);

    expect(container.textContent).toContain("No quality cost items yet");
    expect(container.querySelector('section[aria-label="Cost of Poor Quality"]')).toBeNull();
  });
});

describe("Incident estimator", () => {
  it("validates the selected sections before sending", () => {
    const draft = {
      product: "",
      selected: { downtime: true, lowerProduction: false, scrap: false, cGrade: false, rework: false, repack: false },
      values: { downtime: { downtimeHours: "48" }, lowerProduction: {}, scrap: {}, cGrade: {}, rework: {}, repack: {} },
      packageType: { rework: "" as const, repack: "" as const },
    };
    expect(buildEstimateRequest(draft)).toEqual({ problem: expect.stringContaining("Select the product") });
    expect(buildEstimateRequest({ ...draft, product: "FX1" })).toEqual({
      request: { product: "FX1", downtime: { downtimeHours: "48" } },
    });
    expect(
      buildEstimateRequest({ ...draft, product: "FX1", values: { ...draft.values, downtime: { downtimeHours: "-1" } } }),
    ).toEqual({ problem: expect.stringContaining("as a number") });
    expect(buildEstimateRequest({ ...draft, selected: { ...draft.selected, downtime: false } })).toEqual({
      problem: expect.stringContaining("at least one"),
    });
    expect(
      buildEstimateRequest({
        ...draft,
        product: "FX1",
        selected: { ...draft.selected, repack: true },
        values: {
          ...draft.values,
          repack: { quantityLbs: "1", packageLoadLbPerPiece: "1", extraPersons: "1.5", overtimeHoursPerPerson: "1", payRateUsdPerHour: "1" },
        },
      }),
    ).toEqual({ problem: expect.stringContaining("whole number") });
  });

  it("sends the estimate to the server and shows its lines, not saving anything", async () => {
    await render(<CopqPage title="Cost of Poor Quality" />);
    const tab = [...container.querySelectorAll('[role="tab"]')].find((t) => t.textContent === "Incident estimator")!;
    await click(tab);

    const scrap = [...container.querySelectorAll("fieldset")].find((f) => f.textContent?.includes("More scrap"))!;
    await act(async () => scrap.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    await change(scrap.querySelector<HTMLInputElement>('input[inputmode="decimal"]')!, "2000");
    await click(button("Calculate estimate"));

    const post = requested.find((r) => r.path === `${BASE}/estimate`)!;
    expect(post.init?.method).toBe("POST");
    expect(JSON.parse(String(post.init?.body))).toEqual({ scrap: { quantityLbs: "2000" } });
    expect(text('section[aria-labelledby="estimate-result"]')).toContain("$1,500");
    expect(text('section[aria-labelledby="estimate-result"]')).toContain("Not saved");
    expect(requested.some((r) => r.path === `${BASE}/records` && r.init?.method === "POST")).toBe(false);
  });
});

describe("Cost of Quality Matrix", () => {
  it("never shows a missing good cost or the totals that need it as $0", async () => {
    await render(<CoqMatrixPage title="Cost of Quality Matrix" />);

    expect(paths(`${BASE}/summary`)[0]).toBe(`${BASE}/summary`);
    const kpis = text('section[aria-label="Cost of Quality"]');
    expect(kpis).toContain("Poor COQ (IF + EF)$1,100");
    expect(kpis).toContain("Plus $400 potential exposure");
    expect(kpis).toContain("Not calculable");
    expect(kpis).not.toContain("$0");
    const matrix = text('section[aria-labelledby="coq-matrix"]');
    expect(matrix).toContain("Prevention0 records—Not recordedNo confirmed cost");
    expect(matrix).toContain("Internal Failure2 records$1,000");
    expect(matrix).toContain("+ $400 potential exposure");
  });

  it("shows the confirmed failure-cost mix and says what is missing", async () => {
    await render(<CoqMatrixPage title="Cost of Quality Matrix" />);

    const mix = text('section[aria-labelledby="coq-mix"]');
    expect(mix).toContain("No Prevention or Appraisal cost is recorded");
    expect(mix).toContain("External Failure9.1%");
    expect(mix).toContain("Preventionnot recorded");
  });

  it("lists a class's items when its quadrant is selected", async () => {
    await render(<CoqMatrixPage title="Cost of Quality Matrix" />);
    await click(container.querySelector('section[aria-labelledby="coq-matrix"] button[aria-pressed]:nth-of-type(4)')!);

    expect(paths(`${BASE}/records?`).at(-1)).toContain("coqClass=external_failure");
    expect(text('section[aria-labelledby="coq-items"]')).toContain("External Failure items");
  });

  it("applies the shared filters to the summary", async () => {
    await render(<CoqMatrixPage title="Cost of Quality Matrix" />);
    await change(control<HTMLSelectElement>("Area"), "1");

    expect(paths(`${BASE}/summary`).at(-1)).toBe(`${BASE}/summary?areaId=1`);
    expect(paths(`${BASE}/records?`).at(-1)).toContain("areaId=1");
  });
});
