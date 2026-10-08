// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getNavItem, moduleItems } from "@/config/navigation";

import type { CostMonth, CostSummary, Estimate, EstimatorReference } from "./api";
import { CopqPage } from "./copq-page";
import { buildEstimateRequest } from "./estimator";
import { CoqMatrixPage } from "./matrix-page";

vi.mock("@/components/common/bar-chart", () => ({
  BarChart: ({ title, categories, series, lines }: { title: string; categories: string[]; series: { name: string; values: (number | null)[] }[]; lines?: { name: string; values: (number | null)[] }[] }) => (
    <div data-chart={title} data-categories={categories.join("|")} data-series={[...series, ...(lines ?? [])].map((s) => `${s.name}:${s.values.join(",")}`).join("|")} />
  ),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/** Test fixture, not production data. */
const month = (overrides: Partial<CostMonth> & { month: number }): CostMonth => ({
  year: 2003,
  reported: false,
  totalProductionLbs: null,
  scrapProducedLbs: null,
  offspecProducedLbs: null,
  scrapLossPerLb: null,
  offspecLossPerLb: null,
  complaintCount: null,
  returnedProductLbs: null,
  salesRevenue: null,
  elements: {},
  internalFailure: null,
  externalFailure: null,
  copq: null,
  internalCostPerLb: null,
  externalPctOfSales: null,
  copqPctOfSales: null,
  note: null,
  ...overrides,
});

/** Test fixture, not production data. */
const SUMMARY: CostSummary = {
  year: 2003,
  availableYears: [2003],
  latestReportedMonth: 2,
  months: [
    month({
      month: 1,
      reported: true,
      totalProductionLbs: "1000000",
      scrapProducedLbs: "1000",
      elements: { scrap: "500", offspec: null, lab_investigation: "100" },
      internalFailure: "500",
      externalFailure: "100",
      copq: "600",
      salesRevenue: "100000",
      copqPctOfSales: "0.006",
      complaintCount: 1,
      note: "Fixture note for January.",
    }),
    month({
      month: 2,
      reported: true,
      elements: { scrap: "300", offspec: "200", lab_investigation: "0" },
      internalFailure: "500",
      externalFailure: "0",
      copq: "500",
      complaintCount: 0,
    }),
    ...Array.from({ length: 10 }, (_, index) => month({ month: index + 3 })),
  ],
  period: {
    fromMonth: 1,
    throughMonth: 2,
    monthsInPeriod: 2,
    monthsReported: 2,
    reportedMonths: [1, 2],
    internalFailure: "1000",
    externalFailure: "100",
    copq: "1100",
    totalProductionLbs: "1000000",
    salesRevenue: "100000",
    complaintCount: 1,
    returnedProductLbs: "0",
    copqPctOfSales: "0.006",
    externalPctOfSales: "0.001",
    internalCostPerLb: "0.0005",
  },
  elements: [
    { code: "scrap", label: "Scrap", coqClass: "internal_failure", category: "Scrap", sourceTerm: "Fixture Scrap ($)", value: "800", shareOfCopq: "0.727", cumulativeShare: "0.727" },
    { code: "offspec", label: "Off-spec", coqClass: "internal_failure", category: "Off-spec (C-grade)", sourceTerm: "Fixture Offspec ($)", value: "200", shareOfCopq: "0.182", cumulativeShare: "0.909" },
    { code: "lab_investigation", label: "Lab / investigation", coqClass: "external_failure", category: "Investigation", sourceTerm: "Fixture Lab ($)", value: "100", shareOfCopq: "0.091", cumulativeShare: "1" },
  ],
  matrix: {
    classes: [
      { code: "prevention", label: "Prevention", value: null, recorded: false, shareOfRecorded: null },
      { code: "appraisal", label: "Appraisal", value: null, recorded: false, shareOfRecorded: null },
      { code: "internal_failure", label: "Internal Failure", value: "1000", recorded: true, shareOfRecorded: "0.909" },
      { code: "external_failure", label: "External Failure", value: "100", recorded: true, shareOfRecorded: "0.091" },
    ],
    good: null,
    poor: "1100",
    total: null,
    poorPct: null,
    recordedTotal: "1100",
    unavailableReason: "Fixture: prevention and appraisal are not recorded.",
  },
  dataChecks: [{ year: 2003, month: 1, status: "warning", message: "Fixture: Off-spec not reported." }],
  definitions: [{ term: "Fixture term", definition: "Fixture definition." }],
  source: "Fixture workbook",
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

let container: HTMLDivElement;
let queryClient: QueryClient;
let root: Root | null = null;
let requested: { path: string; init?: RequestInit }[] = [];
let responses: Record<string, { status: number; body: unknown }>;

beforeEach(() => {
  requested = [];
  responses = {
    "/api/v1/quality/cost/summary": { status: 200, body: SUMMARY },
    "/api/v1/quality/cost/estimator": { status: 200, body: REFERENCE },
    "/api/v1/quality/cost/estimate": { status: 200, body: ESTIMATE },
  };
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  container = document.createElement("div");
  document.body.append(container);
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      requested.push({ path, init });
      const response = responses[path.split("?")[0]];
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
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function render(page: React.ReactNode) {
  root = createRoot(container);
  await act(async () => root!.render(<QueryClientProvider client={queryClient}>{page}</QueryClientProvider>));
  await settle();
}

const text = (selector: string) => container.querySelector(selector)?.textContent ?? "";

async function select(label: string, value: string) {
  const element = [...container.querySelectorAll("label")]
    .find((l) => l.textContent?.startsWith(label))!
    .querySelector("select")!;
  await act(async () => {
    element.value = value;
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await settle();
}

describe("Quality navigation", () => {
  it("lists both cost modules under Quality without the development fixture badge", () => {
    const quality = moduleItems.find((item) => item.id === "quality")!;
    const area = quality.children!.find((child) => child.id === "quality-cost")!;
    expect(area.children!.map((child) => child.href)).toEqual(["/quality/cost/copq", "/quality/cost/matrix"]);
    expect(area.children!.every((child) => !child.fixture)).toBe(true);
    expect(getNavItem("/quality/raw-materials/moisture").fixture).toBe(true);
  });
});

describe("Cost of Poor Quality", () => {
  it("shows the period totals from the API and says what is not tracked", async () => {
    await render(<CopqPage title="Cost of Poor Quality" />);

    expect(requested[0].path).toBe("/api/v1/quality/cost/summary");
    const kpis = text('section[aria-label="Cost of Poor Quality"]');
    expect(kpis).toContain("Total COPQ$1,100");
    expect(kpis).toContain("Jan–Feb 2003 · 2 of 2 months reported");
    expect(kpis).toContain("COPQ % of sales0.60%");
    expect(kpis).toContain("$0.0005 per lb produced");
    expect(kpis).toContain("Not tracked");
  });

  it("charts the Pareto by class with the cumulative share and the monthly trend", async () => {
    await render(<CopqPage title="Cost of Poor Quality" />);

    const pareto = container.querySelector('[data-chart="COPQ Pareto by cost line"]')!;
    expect(pareto.getAttribute("data-categories")).toBe("Scrap|Off-spec|Lab / investigation");
    expect(pareto.getAttribute("data-series")).toBe(
      "Internal failure:800,200,|External failure:,,100|Cumulative %:72.7,90.9,100",
    );
    const trend = container.querySelector('[data-chart="Monthly COPQ trend"]')!;
    expect(trend.getAttribute("data-series")).toBe("Internal failure:500,500|External failure:100,0");
  });

  it("keeps not-reported values distinct from zero in the tables", async () => {
    await render(<CopqPage title="Cost of Poor Quality" />);

    const monthly = text('section[aria-labelledby="copq-monthly"]');
    expect(monthly).toContain("Fixture note for January.");
    const lines = [...container.querySelectorAll('section[aria-labelledby="cost-lines"] tbody tr')].map((row) => row.textContent);
    expect(lines).toContainEqual(expect.stringContaining("Off-specOff-spec (C-grade)Internal FailureFixture Offspec ($)Not reported"));
    expect(lines).toContainEqual(expect.stringContaining("Lab / investigationInvestigationExternal FailureFixture Lab ($)$0.00"));
  });

  it("searches the cost lines", async () => {
    await render(<CopqPage title="Cost of Poor Quality" />);
    const search = container.querySelector<HTMLInputElement>('input[type="search"]')!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(search, "investigation");
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const rows = container.querySelectorAll('section[aria-labelledby="cost-lines"] tbody tr');
    expect(rows).toHaveLength(2);
  });

  it("requests the selected period", async () => {
    await render(<CopqPage title="Cost of Poor Quality" />);
    await select("From", "2");

    expect(requested.at(-1)!.path).toBe("/api/v1/quality/cost/summary?from=2");
  });

  it("explains a missing permission without a retry", async () => {
    responses["/api/v1/quality/cost/summary"] = { status: 403, body: {} };
    await render(<CopqPage title="Cost of Poor Quality" />);

    expect(container.textContent).toContain("Cost of Quality data is not available to you");
    expect([...container.querySelectorAll("button")].some((b) => b.textContent === "Retry")).toBe(false);
  });

  it("shows no figures rather than zeros when nothing is imported", async () => {
    responses["/api/v1/quality/cost/summary"] = {
      status: 200,
      body: { ...SUMMARY, year: null, availableYears: [], months: [] },
    };
    await render(<CopqPage title="Cost of Poor Quality" />);

    expect(container.textContent).toContain("No Cost of Quality figures");
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
    await act(async () => (tab as HTMLButtonElement).click());
    await settle();

    const scrap = [...container.querySelectorAll("fieldset")].find((f) => f.textContent?.includes("More scrap"))!;
    await act(async () => scrap.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    const quantityInput = scrap.querySelector<HTMLInputElement>('input[inputmode="decimal"]')!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(quantityInput, "2000");
      quantityInput.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const submit = [...container.querySelectorAll("button")].find((b) => b.textContent === "Calculate estimate")!;
    await act(async () => submit.click());
    await settle();

    const post = requested.find((r) => r.path === "/api/v1/quality/cost/estimate")!;
    expect(post.init?.method).toBe("POST");
    expect(JSON.parse(String(post.init?.body))).toEqual({ scrap: { quantityLbs: "2000" } });
    expect(text('section[aria-labelledby="estimate-result"]')).toContain("$1,500");
    expect(text('section[aria-labelledby="estimate-result"]')).toContain("Not saved");
  });
});

describe("Cost of Quality Matrix", () => {
  it("never shows unrecorded classes or totals that need them as $0", async () => {
    await render(<CoqMatrixPage title="Cost of Quality Matrix" />);

    const kpis = text('section[aria-label="Cost of Quality"]');
    expect(kpis).toContain("Poor COQ (IF + EF)$1,100");
    expect(kpis).toContain("Total COQ—No dataNot calculable");
    expect(kpis).not.toContain("$0");
    const matrix = text('section[aria-labelledby="coq-matrix"]');
    expect(matrix).toContain("PreventionNot recorded");
    expect(matrix).toContain("AppraisalNot recorded");
    expect(matrix).toContain("Internal Failure$1,00090.9% of recorded costs");
  });

  it("shows the failure-cost mix and says what is missing", async () => {
    await render(<CoqMatrixPage title="Cost of Quality Matrix" />);

    const mix = text('section[aria-labelledby="coq-mix"]');
    expect(mix).toContain("Prevention and Appraisal are not recorded");
    expect(mix).toContain("External Failure9.1%");
  });

  it("filters the detail by COQ class", async () => {
    await render(<CoqMatrixPage title="Cost of Quality Matrix" />);
    await select("COQ class", "external_failure");

    const rows = [...container.querySelectorAll('section[aria-labelledby="cost-lines"] tbody tr')];
    expect(rows.length).toBe(2);
    expect(rows.every((row) => row.textContent?.includes("External Failure"))).toBe(true);

    await select("COQ class", "prevention");
    expect(text('section[aria-labelledby="cost-lines"]')).toContain("Prevention costs are not recorded in the source workbook.");
  });
});
