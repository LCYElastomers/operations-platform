// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MetricSectionBlock, MonthlyMetricsResponse } from "./api";
import { IncidentDataEntry } from "./incident-data-entry";
import { siteIsoDate } from "../site-calendar";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const year = (values: Record<number, number>): (number | null)[] =>
  Array.from({ length: 12 }, (_, index) => values[index + 1] ?? null);

function section(id: number, code: string, name: string, rows: [string, string, Record<number, number>][]): MetricSectionBlock {
  return {
    id,
    code,
    name,
    categories: rows.map(([categoryCode, categoryName, values], index) => ({
      id: id * 100 + index + 1,
      code: categoryCode,
      name: categoryName,
      values: year(values),
      ytd: null,
    })),
  };
}

/** Test fixture, not production data. */
const METRICS: MonthlyMetricsResponse = {
  metricSet: "incidents",
  year: 2026,
  canEdit: true,
  yearsWithData: [2026],
  sections: [
    section(1, "incident_near_miss_totals", "Incident & Near Miss Totals", [
      ["near_miss", "Near Miss", { 1: 2 }],
      ["incident", "Incident", { 1: 2, 2: 3 }],
    ]),
    section(2, "incident_classification", "Incident Classification", [
      ["first_aid", "First Aid", { 1: 1 }],
      ["recordable_injury", "Recordable Injury", { 1: 0 }],
    ]),
    section(3, "lopc", "LOPC", [["lopc", "LOPC", { 1: 1 }]]),
    section(7, "incidents_by_area", "Incidents by Area", [
      ["100", "100", { 1: 1 }],
      ["mundy", "MUNDY", { 1: 1, 2: 1 }],
      ["lab", "Lab", {}],
    ]),
    section(10, "near_miss_cause", "Near-Miss Cause", [["housekeeping", "Housekeeping", { 1: 3 }]]),
    section(11, "lopc_contributing_factor", "LOPC Contributing Factor", [["other", "Other", {}]]),
    section(13, "body_part", "Body Part", [
      ["hand", "Hand", { 1: 1 }],
      ["fingers", "Fingers", { 1: 1 }],
    ]),
  ],
};

let root: Root | null = null;
let container: HTMLDivElement;
let queryClient: QueryClient;
let patches: unknown[] = [];

beforeEach(() => {
  patches = [];
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  container = document.createElement("div");
  document.body.append(container);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn((_path: string, init?: RequestInit) => {
      if (init?.method === "PATCH") patches.push(JSON.parse(String(init.body)));
      return Promise.resolve({ ok: true, status: 200, json: async () => METRICS });
    }),
  );
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  container.remove();
  queryClient.clear();
  window.sessionStorage.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function render() {
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
  vi.setSystemTime(new Date("2026-10-08T15:00:00Z"));
  root = createRoot(container);
  await act(async () =>
    root!.render(
      <QueryClientProvider client={queryClient}>
        <IncidentDataEntry title="Incident & Near Miss Data Entry" siteToday={siteIsoDate(new Date())} />
      </QueryClientProvider>,
    ),
  );
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

const grid = (title: string) =>
  [...container.querySelectorAll("section")].find((s) => s.querySelector("h2")?.textContent?.includes(title))!;
const input = (label: string) => container.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;

async function type(label: string, value: string) {
  const element = input(label);
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

describe("Incident & Near Miss Data Entry breakdowns", () => {
  it("groups the totals as A and each breakdown as B–H", async () => {
    await render();

    const headings = [...container.querySelectorAll("h2")].map((h) => h.textContent);
    expect(headings).toContain("A · Incident totals and classifications");
    expect(headings).toContain("Breakdowns");
    expect(headings).toContain("B · Incidents by Area");
    expect(headings).toContain("E · Near-Miss Cause");
    expect(headings).toContain("F · LOPC Contributing Factor");
    expect(headings).toContain("H · Body Part");
    expect(headings.join(" ")).not.toMatch(/Behavior|Process Safety/);
  });

  it("checks areas against Incidents live, as a warning that never fills or blocks", async () => {
    await render();
    const areas = grid("B · Incidents by Area");

    expect(areas.textContent).toContain("Checked against Incidents (warning only).");
    expect(areas.textContent).toContain("Reconciled: Jan");
    expect(areas.textContent).toContain("Feb: Areas 1, Incidents 3 · below total (reconciliation difference −2)");

    await type("MUNDY, Feb", "3");

    expect(areas.textContent).toContain("Reconciled: Jan, Feb");
    // Nothing was filled into the other areas.
    expect(input("100, Feb").value).toBe("");
    expect(input("Lab, Feb").value).toBe("");

    await type("MUNDY, Feb", "5");
    expect(areas.textContent).toContain("Feb: Areas 5, Incidents 3 · above total (reconciliation difference +2)");
    const save = [...container.querySelectorAll("button")].find((b) => b.textContent === "Save changes")!;
    expect(save.disabled).toBe(false);
  });

  it("follows edits to the authoritative total and keeps a zero distinct from blank", async () => {
    await render();
    const areas = grid("B · Incidents by Area");

    await type("Incident, Mar", "0");
    expect(areas.textContent).toContain("Mar: Areas not reported, Incidents 0 · no area data");

    await type("Lab, Mar", "0");
    expect(areas.textContent).toContain("Reconciled: Jan, Mar");
  });

  it("checks body parts against First Aid + Recordable and allows a higher count", async () => {
    await render();
    const body = grid("H · Body Part");

    expect(body.textContent).toContain("Checked against First Aid + Recordable Injury (warning only).");
    expect(body.textContent).toContain("Body parts are tags");
    expect(body.textContent).toContain(
      "Jan: Body parts 2, First Aid + Recordable Injury 1 · above total (reconciliation difference +1)",
    );
  });

  it("notes that near-miss tags may exceed the near-miss count", async () => {
    await render();

    expect(grid("E · Near-Miss Cause").textContent).toContain("Tags may exceed the near-miss count");
    expect(grid("E · Near-Miss Cause").textContent).not.toContain("Checked against");
  });

  it("flags LOPC months with no factor data", async () => {
    await render();

    expect(grid("F · LOPC Contributing Factor").textContent).toContain(
      "Jan: Factors not reported, LOPC 1 · no breakdown data",
    );
  });
});
