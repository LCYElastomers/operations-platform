// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BarSeries } from "@/components/common/bar-chart";

import { NOTES } from "./analytics-data";
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
    footer,
    emptyState,
    loading,
  }: {
    title: string;
    description?: string;
    categories: string[];
    series: BarSeries[];
    footer?: ReactNode;
    emptyState?: ReactNode;
    loading?: boolean;
  }) => (
    <section data-chart={title}>
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
  };
}

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

async function render(instant = OCTOBER_8_2026) {
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
  vi.setSystemTime(new Date(instant));
  root = createRoot(container);
  await act(async () =>
    root!.render(
      <QueryClientProvider client={queryClient}>
        <IncidentDashboard title="Incident & Near Miss Dashboard" siteToday={siteIsoDate(new Date())} />
      </QueryClientProvider>,
    ),
  );
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
    await render("2026-02-10T15:00:00Z");

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
      "Incident Classification",
      "LOPC by Month",
      "Property vs Equipment Damage by Month",
      "Powered Industrial Vehicle (PIT) Incidents",
      "PSIF by Month",
    ]);
    expect(container.querySelector('[aria-label="Methodology and data completeness"]')).not.toBeNull();
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

    expect(chart("Powered Industrial Vehicle (PIT) Incidents")).not.toBeNull();
    const captions = [...container.querySelectorAll("table caption")].map((c) => c.textContent);
    expect(captions).toHaveLength(6);
    expect(captions).toContain("Incident Classification, Jan 2026");
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
