// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BarSeries, LineSeries } from "@/components/common/bar-chart";

import { NOTES, type DashboardView } from "./analytics-data";
import {
  emptyAnalyticsExtras,
  fixtureBehavior,
  fixtureBreakdown,
  fixtureCategory,
  fixtureReconciliation,
} from "./analytics.fixture";
import type { AnalyticsKpi, AnalyticsSeries, IncidentAnalyticsResponse } from "./api";
import { IncidentDashboard } from "./incident-dashboard";
import { siteIsoDate } from "../site-calendar";

// ECharts needs a canvas; the stand-in shows what each chart is given.
vi.mock("@/components/common/bar-chart", async (original) => ({
  ...(await original<object>()),
  BarChart: ({
    title,
    description,
    categories,
    series,
    lines = [],
    footer,
    emptyState,
    loading,
  }: {
    title: string;
    description?: string;
    categories: string[];
    series: BarSeries[];
    lines?: LineSeries[];
    footer?: ReactNode;
    emptyState?: ReactNode;
    loading?: boolean;
  }) => (
    <section
      data-chart={title}
      data-series={series.map((s) => `${s.name}:${s.color ?? ""}:${s.stack ?? ""}`).join("|")}
      data-lines={lines.map((l) => `${l.name}:${l.axis ?? "left"}:${l.values.join(",")}`).join("|")}
    >
      <h2>{title}</h2>
      <p>{description}</p>
      {loading ? null : series.some((s) => s.values.some((value) => value !== null)) ? (
        <ol>
          {categories.map((category, index) => (
            <li key={category}>
              {category}: {series.map((s) => (s.values[index] === null ? "unreported" : s.values[index])).join("/")}
            </li>
          ))}
        </ol>
      ) : (
        emptyState
      )}
      {footer}
    </section>
  ),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const OCTOBER_8_2026 = "2026-10-08T15:00:00Z";

function series(values: (number | null)[], overrides: Partial<AnalyticsSeries> = {}): AnalyticsSeries {
  const reported = values.filter((value): value is number => value !== null);
  const unreported = values.flatMap((value, index) => (value === null ? [index + 1] : []));
  return {
    section: "incident_classification",
    code: "code",
    name: "Name",
    values,
    total: reported.length ? reported.reduce((a, b) => a + b, 0) : null,
    monthsReported: reported.length,
    unreportedMonths: unreported,
    complete: values.length > 0 && unreported.length === 0,
    ...overrides,
  };
}

/** Test fixture, not production data. */
function analytics(
  year: number,
  through: number | null,
  values: Partial<Record<"incidents" | "nearMisses" | "lopc" | "psif" | "pit" | "property" | "equipment", (number | null)[]>> = {},
  extras: Partial<IncidentAnalyticsResponse> = {},
): IncidentAnalyticsResponse {
  const months = through ?? 0;
  const of = (key: keyof typeof values) => values[key] ?? Array.from({ length: months }, () => null);
  const incidents = series(of("incidents"), { section: "incident_near_miss_totals", code: "incident", name: "Incident" });
  const nearMisses = series(of("nearMisses"), { section: "incident_near_miss_totals", code: "near_miss", name: "Near Miss" });
  const lopc = series(of("lopc"), { section: "lopc", code: "lopc", name: "LOPC" });
  const psif = series(of("psif"), { section: "psif", code: "psif", name: "PSIF" });
  const pit = series(of("pit"), { code: "pit_accident", name: "PIT Accident" });
  const propertyDamage = series(of("property"), { code: "property_damage", name: "Property Damage" });
  const equipmentDamage = series(of("equipment"), {
    code: "equipment_damage_failure",
    name: "Equipment Damage / Failure",
  });
  const combined = propertyDamage.values.map((p, i) => {
    const e = equipmentDamage.values[i];
    return p === null && e === null ? null : (p ?? 0) + (e ?? 0);
  });
  // A combined month is reported only when both parts are.
  const bothUnreported = [...new Set([...propertyDamage.unreportedMonths, ...equipmentDamage.unreportedMonths])].sort(
    (a, b) => a - b,
  );
  const combinedDamage = series(combined, {
    code: "property_damage+equipment_damage_failure",
    name: "Combined Damage",
    unreportedMonths: bothUnreported,
    monthsReported: months - bothUnreported.length,
    complete: months > 0 && bothUnreported.length === 0,
  });
  const kpi = (key: AnalyticsKpi["key"], s: AnalyticsSeries, parts: AnalyticsSeries[] = []): AnalyticsKpi => ({
    key,
    value: s.total,
    monthsReported: s.monthsReported,
    throughMonth: through,
    complete: s.complete,
    parts: parts.map((p) => ({ code: p.code, name: p.name, value: p.total, complete: p.complete })),
  });
  return {
    year,
    throughMonth: through,
    latestMonth: through,
    availableYears: [year],
    kpis: [
      kpi("incidents", incidents),
      kpi("near_misses", nearMisses),
      kpi("lopc", lopc),
      kpi("psif", psif),
      kpi("pit", pit),
      kpi("combined_damage", combinedDamage, [propertyDamage, equipmentDamage]),
    ],
    incidents,
    nearMisses,
    classifications: [
      series(Array.from({ length: months }, () => null), { code: "first_aid", name: "First Aid" }),
      pit,
      propertyDamage,
      equipmentDamage,
      psif,
    ],
    lopc,
    psif,
    pit,
    propertyDamage,
    equipmentDamage,
    combinedDamage,
    ...emptyAnalyticsExtras(year, months),
    ...extras,
  };
}

/** Test fixture: the approved 2026 Behavior counts, highest first. */
const BEHAVIOR_COUNTS: [string, string, number][] = [
  ["eyes_on_path", "Eyes On Path", 12],
  ["pre_post_job_inspection", "Pre & Post Job Inspection", 9],
  ["communications_of_hazards", "Communications Of Hazards", 4],
  ["knowledge_of_task", "Knowledge of Task", 4],
  ["energy_isolation", "Energy Isolation", 4],
  ["pinch_points", "Pinch Points", 3],
  ["get_assistance", "Get Assistance", 3],
  ["line_of_fire", "Line Of Fire", 2],
  ["ppe_hands", "PPE Hands", 2],
  ["ppe_eye", "PPE Eye", 1],
];
const BEHAVIOR_2026 = fixtureBehavior(2026, BEHAVIOR_COUNTS, 41, ["Housekeeping", "Hot work"]);

// API ------------------------------------------------------------------------------

let requested: URL[] = [];

type Reply = { status: number; body: unknown } | undefined;

/** Requests the responder does not answer stay pending: the page shows its loading state. */
function stubApi(respond: (url: URL) => Reply = () => undefined) {
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) => {
      const url = new URL(path, "http://baytown.test");
      requested.push(url);
      const reply = respond(url);
      if (reply === undefined) return new Promise(() => {});
      return Promise.resolve({
        ok: reply.status < 400,
        status: reply.status,
        json: async () => reply.body,
      });
    }),
  );
}

const ok = (body: unknown): Reply => ({ status: 200, body });

// Rendering --------------------------------------------------------------------------

let root: Root | null = null;
let container: HTMLDivElement;
let queryClient: QueryClient;

async function render(instant = OCTOBER_8_2026, initialView?: DashboardView) {
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
  vi.setSystemTime(new Date(instant));
  root = createRoot(container);
  await act(async () =>
    root!.render(
      <QueryClientProvider client={queryClient}>
        <IncidentDashboard
          title="Incident & Near Miss Dashboard"
          siteToday={siteIsoDate(new Date())}
          initialView={initialView}
        />
      </QueryClientProvider>,
    ),
  );
  await settle();
}

const tab = (name: string) =>
  [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((t) => t.textContent === name)!;

async function openTab(name: string) {
  await act(async () => tab(name).click());
  await settle();
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function select(label: string): HTMLSelectElement {
  const found = [...container.querySelectorAll("label")].find(
    (element) => element.querySelector("span")?.textContent === label,
  );
  const control = found?.querySelector("select");
  if (!control) throw new Error(`No "${label}" select`);
  return control;
}

async function choose(control: HTMLSelectElement, value: number) {
  await act(async () => {
    control.value = String(value);
    control.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await settle();
}

const text = () => container.textContent ?? "";
const chart = (title: string) => container.querySelector(`[data-chart="${title}"]`)!;
const kpiSection = () => container.querySelector('section[aria-label="Year to date"]')!;
const cardLabels = () => [...kpiSection().children].map((element) => element.querySelector("p")?.textContent);
const card = (label: string) =>
  [...kpiSection().children].find((element) => element.querySelector("p")?.textContent === label)!.textContent;

beforeEach(() => {
  requested = [];
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  container = document.createElement("div");
  document.body.append(container);
  stubApi();
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  container.remove();
  queryClient.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Incident & Near Miss Dashboard", () => {
  it("is titled Incident & Near Miss Dashboard, links to data entry and reads the Incident Analytics API", async () => {
    await render();

    expect(container.querySelector("h1")?.textContent).toBe("Incident & Near Miss Dashboard");
    expect(text()).not.toContain("Analytics Dashboard");
    const link = [...container.querySelectorAll("a")].find((a) => a.textContent === "Open data entry");
    expect(link?.getAttribute("href")).toBe("/safety/incidents/data-entry");
    expect(requested.map((url) => url.pathname)).toEqual(["/api/v1/safety/incidents/analytics"]);
  });

  it("shows a loading state while the request is pending", async () => {
    await render();

    expect(text()).toContain("Loading Safety data");
    expect(container.querySelectorAll('[aria-busy="true"]').length).toBeGreaterThanOrEqual(4);
  });

  it("explains an API error", async () => {
    stubApi(() => ({ status: 422, body: {} }));
    await render();

    expect(text()).toContain("Could not load Safety data");
    expect(text()).toContain("The API responded with HTTP 422.");
    expect(text()).toContain("Unavailable");
  });

  it("explains missing permission without a retry", async () => {
    stubApi(() => ({ status: 403, body: { detail: { error: "permission_denied" } } }));
    await render();

    expect(text()).toContain("Safety data is not available to you");
    expect(text()).toContain("You do not have permission for this Safety function.");
  });

  it("follows the Baytown year and latest month, and asks the API for its default", async () => {
    await render();

    expect(select("Reporting year").value).toBe("2026");
    expect(select("Through month").value).toBe("10");
    expect([...select("Through month").options].map((o) => o.text)).toEqual(
      ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"],
    );
    expect(requested.map((url) => url.search)).toEqual(["?year=2026"]);
  });

  it("requests a chosen through month, and a chosen year starts from its latest month again", async () => {
    await render();
    await choose(select("Through month"), 9);
    expect(requested.at(-1)!.search).toBe("?year=2026&through=9");

    await choose(select("Reporting year"), 2026);
    expect(select("Through month").value).toBe("10");
  });

  it("renders KPIs, partial-year completeness and the methodology notes", async () => {
    stubApi(() =>
      ok(
        analytics(2026, 10, {
          incidents: [5, 6, 5, 6, 3, 4, 5, 3, 4, null],
          nearMisses: [3, null, null, 11, 2, 4, 4, 5, 2, null],
          psif: [2, null, null, 2, null, null, null, 1, null, null],
        }),
      ),
    );
    await render();

    expect(text()).toContain("Incidents YTD");
    expect(text()).toContain("41");
    expect(text()).toContain("Jan–Oct 2026 · 9 of 10 months reported");
    expect(text()).toContain("Near Misses: Feb, Mar, Oct");
    expect(text()).toContain(NOTES.classification);
    expect(text()).toContain(NOTES.damage);
    expect(text()).toContain(NOTES.psif);
    expect(text()).toContain(NOTES.psifDefinition);
    // Counts only: no percentages, frequencies or ratios.
    expect(text()).not.toContain("%");
    expect(text()).not.toMatch(/frequency|ratio/i);
  });

  it("shows a reported zero as 0 and an unreported month as not reported", async () => {
    stubApi(() => ok(analytics(2026, 2, { psif: [null, 0], incidents: [1, 1] })));
    await render("2026-02-10T15:00:00Z");

    const psif = chart("PSIF by Month");
    expect(psif.querySelector("ol")!.textContent).toBe("Jan: unreportedFeb: 0");
    const cells = [...psif.querySelectorAll("tbody td")].map((cell) => cell.textContent);
    expect(cells).toEqual(["Not reported", "0"]);
    expect(psif.querySelector("tfoot td")!.textContent).toBe("0 (partial)");
  });

  it("shows property and equipment damage separately with their YTD totals", async () => {
    stubApi(() => ok(analytics(2026, 2, { property: [1, 2], equipment: [0, null] })));
    await render("2026-02-10T15:00:00Z", "incident-analysis");

    const damage = chart("Property vs Equipment Damage by Month");
    expect(damage.textContent).toContain("Property Damage · 3 YTD");
    expect(damage.textContent).toContain("Equipment Damage / Failure · 0 YTD (partial)");
    expect(damage.textContent).toContain("combined 3");
    expect(damage.querySelector("ol")!.textContent).toBe("Jan: 1/0Feb: 2/unreported");
  });

  it("shows six YTD cards, with PIT 9 and damage 14 as 6 property · 8 equipment", async () => {
    // Test fixture: the approved 2026 monthly values, January–September.
    stubApi(() =>
      ok(
        analytics(2026, 9, {
          incidents: [5, 6, 5, 6, 3, 4, 5, 3, 4],
          nearMisses: [3, null, null, 11, 2, 4, 4, 5, 2],
          lopc: [1, 2, 2, 1, null, 2, 3, 2, 1],
          psif: [2, null, null, 2, null, null, null, 1, null],
          pit: [null, 1, null, 3, 1, 2, 1, null, 1],
          property: [1, 1, null, null, 2, null, 2, null, null],
          equipment: [0, null, 1, 4, null, 2, null, null, 1],
        }),
      ),
    );
    await render();

    expect(cardLabels()).toEqual([
      "Incidents YTD",
      "Near Misses YTD",
      "LOPC YTD",
      "PSIF YTD",
      "PIT Incidents YTD",
      "Property & Equipment Damage YTD",
    ]);
    expect(card("Incidents YTD")).toBe("Incidents YTD41Jan–Sep 2026 · all 9 months reported");
    expect(card("Near Misses YTD")).toBe("Near Misses YTD31Jan–Sep 2026 · 7 of 9 months reported");
    expect(card("LOPC YTD")).toBe("LOPC YTD14Jan–Sep 2026 · 8 of 9 months reported");
    expect(card("PSIF YTD")).toBe("PSIF YTD5Jan–Sep 2026 · 3 of 9 months reported");
    expect(card("PIT Incidents YTD")).toBe("PIT Incidents YTD9Jan–Sep 2026 · 6 of 9 months reported");
    expect(card("Property & Equipment Damage YTD")).toBe(
      "Property & Equipment Damage YTD146 property · 8 equipment · Jan–Sep 2026, partial, both reported in 1 of 9 months",
    );
    expect([...container.querySelectorAll("[data-chart]")].map((c) => c.getAttribute("data-chart"))).toEqual([
      "Incidents vs Near Misses by Month",
      "Incidents vs Prior Year by Month (2026 vs 2025)",
      "Incident Classification",
      "PSIF by Month",
    ]);
    expect(container.querySelector('[aria-label="Methodology and data completeness"]')).not.toBeNull();

    await openTab("Incident Analysis");
    expect([...container.querySelectorAll("[data-chart]")].map((c) => c.getAttribute("data-chart"))).toEqual([
      "LOPC by Month",
      "LOPC vs Prior Year by Month (2026 vs 2025)",
      "LOPC Contributing Factors",
      "Property vs Equipment Damage by Month",
      "Powered Industrial Vehicle (PIT) Incidents",
      "Injury Cause",
      "Body Part",
      "Near-Miss Potential",
      "Near-Miss Cause",
    ]);
    // Damage is shown once, on Incident Analysis only.
    await openTab("Overview");
    expect(chart("Property vs Equipment Damage by Month")).toBeNull();
  });

  it("shows a complete damage total, a reported zero and an unreported component", async () => {
    stubApi(() => ok(analytics(2026, 2, { property: [1, 2], equipment: [0, 0], pit: [0, 0] })));
    await render("2026-02-10T15:00:00Z");

    expect(card("Property & Equipment Damage YTD")).toBe(
      "Property & Equipment Damage YTD33 property · 0 equipment · Jan–Feb 2026, all 2 months reported",
    );
    expect(card("PIT Incidents YTD")).toBe("PIT Incidents YTD0Jan–Feb 2026 · all 2 months reported");

    await act(async () => root?.unmount());
    root = null;
    queryClient.clear();
    stubApi(() => ok(analytics(2026, 2, { property: [4, 0] })));
    await render("2026-02-10T15:00:00Z");

    expect(card("Property & Equipment Damage YTD")).toBe(
      "Property & Equipment Damage YTD44 property · equipment not reported · Jan–Feb 2026, partial, both reported in 0 of 2 months",
    );
    expect(card("PIT Incidents YTD")).toBe("PIT Incidents YTD—No dataNo months reported, Jan–Feb 2026");
  });

  it("titles the PIT chart and gives every chart a data table alternative", async () => {
    stubApi(() => ok(analytics(2026, 1, { pit: [1] })));
    await render("2026-01-10T15:00:00Z");

    // Overview: the prior-year chart has no table while 2025 is unavailable.
    let captions = [...container.querySelectorAll("table caption")].map((c) => c.textContent);
    expect(captions).toEqual([
      "Incidents and Near Misses by month, Jan 2026",
      "Incident Classification, Jan 2026",
      "PSIF by month, Jan 2026",
    ]);

    await openTab("Incident Analysis");
    expect(chart("Powered Industrial Vehicle (PIT) Incidents")).not.toBeNull();
    captions = [...container.querySelectorAll("table caption")].map((c) => c.textContent);
    expect(captions).toContain("LOPC by month, Jan 2026");
    expect(captions).toContain("LOPC contributing factors by month, Jan 2026");
    expect(captions).toContain("Powered Industrial Vehicle (PIT) Incidents by month, Jan 2026");
    expect(captions).toContain("Near-Miss Cause, Jan 2026");
  });

  it("renders an empty year as not reported, without 2026 values", async () => {
    stubApi((url) => ok(analytics(Number(url.searchParams.get("year")), 1)));
    await render("2027-01-01T06:01:00Z");

    expect(select("Reporting year").value).toBe("2027");
    expect(text()).toContain("No months have been reported for Jan 2027.");
    expect(text()).toContain("No months reported, Jan 2027");
    expect(card("PIT Incidents YTD")).toBe("PIT Incidents YTD—No dataNo months reported, Jan 2027");
    expect(card("Property & Equipment Damage YTD")).toBe(
      "Property & Equipment Damage YTD—No dataNo months reported, Jan 2027",
    );
    expect(chart("Incident Classification").textContent).toContain("Nothing has been reported for Jan 2027.");
    expect(text()).not.toContain("2026 ·");
    expect(requested.map((url) => url.searchParams.get("year"))).toEqual(["2027"]);
  });
});

/** Test fixture: two months with area, factor and tag breakdowns. */
function withBreakdowns(): IncidentAnalyticsResponse {
  const incidentAreas = [
    fixtureCategory("100", "100", [null, 1], { description: "Ingredient Prep", areaKind: "process_unit" }),
    fixtureCategory("lab", "Lab", [0, null], { areaKind: "support" }),
    fixtureCategory("mundy", "MUNDY", [2, 2], { areaKind: "organization" }),
    fixtureCategory("admin", "Admin", [null, null], { areaKind: "support" }),
  ];
  const nearMissAreas = [fixtureCategory("600", "600", [1, null], { areaKind: "process_unit" })];
  const factors = fixtureBreakdown(
    "lopc_contributing_factor",
    [
      fixtureCategory("mechanical_integrity", "Mechanical Integrity", [1, 1]),
      fixtureCategory("human_error", "Human Error", [null, 1]),
      fixtureCategory("other", "Other", [null, null]),
    ],
    2,
  );
  const reported = (rows: ReturnType<typeof fixtureCategory>[]) =>
    fixtureBreakdown("x", rows, 2).categories.filter((row) => row.total !== null);
  const response = analytics(
    2026,
    2,
    { incidents: [2, 4], nearMisses: [1, null], lopc: [1, 2] },
    {
      incidentsByArea: reported(incidentAreas),
      nearMissesByArea: reported(nearMissAreas),
      incidentAreaMonthly: incidentAreas,
      nearMissAreaMonthly: nearMissAreas,
      areaReconciliation: {
        incidents: fixtureReconciliation([2, 3], [2, 4]),
        nearMisses: fixtureReconciliation([1, null], [1, null]),
      },
      incidentsPriorYearMonthly: series([5, 0], { section: "incident_near_miss_totals", code: "incident", name: "Incident" }),
      incidentsPriorYearAvailable: true,
      lopcContributingFactors: {
        breakdown: factors,
        cumulative: factors.rows.map((row) => ({ code: row.code, name: row.name, values: row.values })),
        cumulativeTotal: [1, 3],
      },
      lopcFactorReconciliation: fixtureReconciliation(factors.monthlyTotals, [1, 2]),
      nearMissCause: fixtureBreakdown(
        "near_miss_cause",
        [fixtureCategory("housekeeping", "Housekeeping", [1, null]), fixtureCategory("procedures", "Procedures", [2, null])],
        2,
        true,
      ),
    },
  );
  response.kpis[0] = {
    ...response.kpis[0],
    priorYear: { year: 2025, value: 5, monthsReported: 2, complete: true, delta: 1 },
  };
  return response;
}

describe("Incident & Near Miss Dashboard views", () => {
  afterEach(() => window.history.replaceState(null, "", "/"));

  it("opens on Overview, switches views in the URL and keeps the year, month and request", async () => {
    stubApi(() => ok(withBreakdowns()));
    await render("2026-02-10T15:00:00Z");
    await choose(select("Through month"), 1);
    const requests = requested.length;

    expect(tab("Overview").getAttribute("aria-selected")).toBe("true");
    await openTab("Area");

    expect(tab("Area").getAttribute("aria-selected")).toBe("true");
    expect(new URL(window.location.href).searchParams.get("view")).toBe("area");
    expect(select("Through month").value).toBe("1");
    expect(requested).toHaveLength(requests);
    const link = [...container.querySelectorAll("a")].find((a) => a.textContent === "Open data entry");
    expect(link?.getAttribute("href")).toBe("/safety/incidents/data-entry");
  });

  it("moves between tabs with the arrow keys", async () => {
    stubApi(() => ok(withBreakdowns()));
    await render("2026-02-10T15:00:00Z");

    await act(async () => {
      tab("Overview").dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }));
    });

    expect(tab("Behavior").getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(tab("Behavior"));
  });

  it("compares Incidents with the prior year in grey, keeping a reported zero", async () => {
    stubApi(() => ok(withBreakdowns()));
    await render("2026-02-10T15:00:00Z");

    const prior = chart("Incidents vs Prior Year by Month (2026 vs 2025)");
    expect(prior.getAttribute("data-series")).toBe("2025:#94a3b8:|2026:#2563eb:");
    expect(prior.querySelector("ol")!.textContent).toBe("Jan: 5/2Feb: 0/4");
    expect(card("Incidents YTD")).toContain("Prior year (Jan–Feb 2025): 5 · +1");
  });

  it("shows an empty prior-year chart when the prior year is unavailable", async () => {
    stubApi(() => ok(analytics(2026, 2, { incidents: [1, 1] })));
    await render("2026-02-10T15:00:00Z");

    const prior = chart("Incidents vs Prior Year by Month (2026 vs 2025)");
    expect(prior.textContent).toContain("No Incidents values are recorded for 2025, so there is nothing to compare.");
    expect(prior.querySelector("ol")).toBeNull();
    expect(card("Incidents YTD")).not.toContain("Prior year");
  });

  it("lists reported areas only and shows blank as – and a reported zero as 0", async () => {
    stubApi(() => ok(withBreakdowns()));
    await render("2026-02-10T15:00:00Z", "area");

    expect(chart("Incidents by Area").querySelector("ol")!.textContent).toBe("MUNDY: 4100: 1Lab: 0");
    expect(chart("Incidents by Area").textContent).toContain("Jan–Feb 2026");
    const grid = container.querySelector('section[aria-label="Incidents by Area and Month"]')!;
    const row = (label: string) =>
      [...grid.querySelectorAll("tbody tr")].find((tr) => tr.querySelector("th")!.textContent!.startsWith(label))!;
    const cells = (label: string) => [...row(label).querySelectorAll("td")].map((td) => td.textContent);
    expect(cells("Lab")).toEqual(["0", "–Not reported", "0"]);
    expect(cells("Admin")).toEqual(["–Not reported", "–Not reported", "–Not reported"]);
    expect(row("100").querySelector("th")!.getAttribute("title")).toBe("Ingredient Prep");
    // Area rows stay in display order; the footer adds the reported areas.
    expect([...grid.querySelectorAll("tbody th")].map((th) => th.childNodes[0].textContent)).toEqual([
      "100",
      "Lab",
      "MUNDY",
      "Admin",
    ]);
    expect([...grid.querySelectorAll("tfoot tr")[0].querySelectorAll("td")].map((td) => td.textContent)).toEqual([
      "2",
      "3",
      "5",
    ]);
    const checks = [...grid.querySelectorAll("tfoot tr")[1].querySelectorAll("td")].map((td) => td.getAttribute("title"));
    expect(checks[0]).toBe("January: areas total 2, matches Incidents 2");
    expect(checks[1]).toBe("February: areas total 3, Incidents 4 (reconciliation difference −1)");
    expect(grid.textContent).toContain("Reconciled in 1 of 2 months; 1 with a reconciliation difference.");
  });

  it("stacks the LOPC factors with a cumulative total and flags the tags", async () => {
    stubApi(() => ok(withBreakdowns()));
    await render("2026-02-10T15:00:00Z", "incident-analysis");

    const factors = chart("LOPC Contributing Factors");
    expect(factors.getAttribute("data-series")).toBe(
      "Mechanical Integrity:#7c3aed:factors|Human Error:#0d9488:factors|Other:#64748b:factors",
    );
    expect(factors.getAttribute("data-lines")).toBe("Cumulative total:right:1,3");
    expect(factors.textContent).toContain("Reconciled in 2 of 2 months.");
    const cause = chart("Near-Miss Cause");
    expect(cause.textContent).toContain(NOTES.tags);
    expect(cause.querySelector("ol")!.textContent).toBe("Procedures: 2Housekeeping: 1");
    expect(chart("Body Part").textContent).toContain(NOTES.injuries);
  });

  it("shows a legitimate empty Behavior view with no values and no data entry", async () => {
    stubApi(() => ok(withBreakdowns()));
    await render("2026-02-10T15:00:00Z", "behavior");

    const panel = container.querySelector('[role="tabpanel"]')!;
    expect(panel.textContent).toContain("No behavior data recorded for 2026.");
    expect(panel.textContent).not.toMatch(/\b0 behaviors?\b|zero/i);
    expect(panel.querySelector("a")).toBeNull();
    expect(panel.querySelector("[data-chart]")).toBeNull();
  });

  it("renders the 2026 Behavior Pareto with derived shares, matching its table", async () => {
    stubApi(() => ok(analytics(2026, 9, {}, { behavior: BEHAVIOR_2026 })));
    await render(OCTOBER_8_2026, "behavior");
    const panel = container.querySelector('[role="tabpanel"]')!;

    const kpis = panel.querySelector('section[aria-label="Behavior 2026"]')!;
    const cards = [...kpis.children].map((element) => element.textContent);
    expect(cards[0]).toContain("Behavior Tags44");
    expect(cards[1]).toContain("Incident Reports41");
    expect(cards[2]).toContain("Behaviors per Incident1.07");
    expect(cards[2]).toContain("44 tags ÷ 41 incident reports");
    expect(cards[2]).toContain("One incident can carry more than one behavior tag.");

    const pareto = chart("Behavior Pareto, 2026");
    const bars = [...pareto.querySelectorAll("li")].map((li) => li.textContent);
    expect(bars).toEqual(BEHAVIOR_COUNTS.map(([, name, count]) => `${name}: ${count}`));
    expect(pareto.getAttribute("data-lines")).toBe(
      "Cumulative % of tags:right:27.3,47.7,56.8,65.9,75,81.8,88.6,93.2,97.7,100",
    );
    expect(pareto.textContent).toContain("can add up to more than 100%");

    const table = pareto.querySelector("table")!;
    expect([...table.querySelectorAll("thead th")].map((th) => th.textContent)).toEqual([
      "Behavior",
      "Count",
      "% of behavior tags",
      "% of incident reports",
      "Cumulative % of tags",
    ]);
    const rows = [...table.querySelectorAll("tbody tr")].map((tr) =>
      [...tr.querySelectorAll("th, td")].map((cell) => cell.textContent),
    );
    // The table lists the bars in the same order with the same counts.
    expect(rows.map(([name, count]) => `${name}: ${count}`)).toEqual(bars);
    expect(rows[0]).toEqual(["Eyes On Path", "12", "27.3%", "29.3%", "27.3%"]);
    expect(rows.at(-1)).toEqual(["PPE Eye", "1", "2.3%", "2.4%", "100.0%"]);
    expect(table.querySelector("tfoot")?.textContent).toContain("107.3% (tags per incident report; can exceed 100%)");
    expect(pareto.textContent).toContain("Not reported for 2026 (no entry, not zero): Housekeeping, Hot work.");
  });

  it("shows a legitimate empty Behavior state for a year without Behavior counts", async () => {
    stubApi((url) => {
      const year = Number(url.searchParams.get("year"));
      return ok(analytics(year, 3, {}, year === 2026 ? { behavior: BEHAVIOR_2026 } : {}));
    });
    await render("2027-03-10T15:00:00Z", "behavior");
    await choose(select("Reporting year"), 2027);

    const panel = container.querySelector('[role="tabpanel"]')!;
    expect(panel.textContent).toContain("No behavior data recorded for 2027.");
    expect(panel.querySelector("[data-chart]")).toBeNull();
    expect(panel.querySelector("table")).toBeNull();
  });

  it("never shows TRIR, Process Safety or pie charts", async () => {
    stubApi(() => ok(withBreakdowns()));
    for (const view of ["overview", "area", "incident-analysis", "behavior"] as const) {
      await render("2026-02-10T15:00:00Z", view);
      expect(text()).not.toMatch(/TRIR|Process Safety|PSM|\bpie\b/i);
      await act(async () => root?.unmount());
      root = null;
    }
  });
});
