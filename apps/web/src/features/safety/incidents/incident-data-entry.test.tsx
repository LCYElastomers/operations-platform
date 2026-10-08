// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BehaviorCountsResponse, MetricSectionBlock, MonthlyMetricsResponse } from "./api";
import { IncidentDataEntry } from "./incident-data-entry";
import type { IncidentRecord, ReconciliationResponse } from "./records/api";
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

/** Test fixture, not production data: one count, one explicit zero, one blank. */
const BEHAVIOR: BehaviorCountsResponse = {
  year: 2026,
  canEdit: true,
  categories: [
    { id: 1, code: "pre_post_job_inspection", name: "Pre & Post Job Inspection", value: 9 },
    { id: 9, code: "housekeeping", name: "Housekeeping", value: null },
    { id: 11, code: "ppe_eye", name: "PPE Eye", value: 0 },
  ],
  total: 9,
  yearsWithData: [2026],
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
    vi.fn((path: string, init?: RequestInit) => {
      const behavior = String(path).includes("/incidents/behavior");
      if (init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        patches.push(body);
        const response = behavior ? { changedCategories: body.changes.length, counts: BEHAVIOR } : METRICS;
        return Promise.resolve({ ok: true, status: 200, json: async () => response });
      }
      if (init?.method === "POST") {
        patches.push({ path, body: JSON.parse(String(init.body)) });
        const response = { record: RECORD, canEdit: true, canManage: false, canViewHistory: true };
        return Promise.resolve({ ok: true, status: 201, json: async () => response });
      }
      const records = recordResponse(String(path));
      if (records !== undefined) return Promise.resolve({ ok: true, status: 200, json: async () => records });
      return Promise.resolve({ ok: true, status: 200, json: async () => (behavior ? BEHAVIOR : METRICS) });
    }),
  );
});

/** Test fixture, not production data: January has 2 Incidents reported and 1 documented. */
const RECONCILIATION: ReconciliationResponse = {
  year: 2026,
  canEdit: true,
  canManage: false,
  canViewHistory: true,
  months: (["incident", "near_miss"] as const).flatMap((eventType) =>
    Array.from({ length: 12 }, (_, index) => {
      const month = index + 1;
      const total = METRICS.sections[0].categories.find((c) => c.code === eventType)!.values[index];
      const documented = eventType === "incident" && month === 1 ? 1 : 0;
      return {
        month,
        eventType,
        monthlyTotal: total,
        documented,
        state:
          total === null
            ? ("no_total_and_no_records" as const)
            : documented === total
              ? ("reconciled" as const)
              : ("records_missing" as const),
      };
    }),
  ),
};

/** Test fixture, not production data. */
const RECORD: IncidentRecord = {
  id: 7,
  incidentNumber: "ZZT-2026-001",
  eventType: "incident",
  incidentDate: "2026-01-14",
  reportingYear: 2026,
  reportingMonth: 1,
  description: "Fixture record description.",
  areaId: null,
  areaCode: null,
  areaName: null,
  classificationCategoryId: null,
  classificationCode: null,
  classificationName: null,
  status: "active",
  statusReason: null,
  relatedIncidentId: null,
  relatedIncidentNumber: null,
  source: "manual",
  version: 1,
  createdAt: "2026-01-15T00:00:00Z",
  createdBy: "fixture",
  updatedAt: "2026-01-15T00:00:00Z",
  updatedBy: "fixture",
};

function recordResponse(path: string): unknown {
  if (!path.includes("/incidents/records")) return undefined;
  if (path.includes("/reconciliation")) return RECONCILIATION;
  if (path.includes("/options")) return { areas: [], classifications: [] };
  return { records: [RECORD], total: 1, canEdit: true, canManage: false, canViewHistory: true };
}

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
    // Behavior is annual: only the separate annual card, never a monthly grid.
    expect(headings.filter((h) => h?.includes("Behavior"))).toEqual(["Annual Behavior tagging, 2026"]);
    expect(headings.join(" ")).not.toMatch(/Process Safety/);
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

describe("Monthly record actions", () => {
  const buttonLabelled = (label: string) => container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
  const dialog = () => container.querySelector("dialog")!;
  const settle = () =>
    act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

  it("adds a Records row with a visible button per started month under Incident and Near Miss only", async () => {
    await render();
    const totals = grid("Incident & Near Miss Totals");

    const recordRows = [...totals.querySelectorAll("tbody th")].filter((th) => th.textContent === "Records");
    expect(recordRows).toHaveLength(2);
    expect(buttonLabelled("Manage 1 Incident record for January 2026")!.textContent).toBe("1!");
    expect(buttonLabelled("Add Incident record for February 2026")!.textContent).toBe("Add");
    expect(buttonLabelled("Add Near Miss record for October 2026")).not.toBeNull();
    // The site date is 8 October 2026: no record can be dated in November.
    expect(buttonLabelled("Add Near Miss record for November 2026")).toBeNull();
    expect(grid("Incident Classification").querySelector("button[aria-label^='Add']")).toBeNull();
    expect(buttonLabelled("Manage 1 Incident record for January 2026")!.title).toContain(
      "Reported total 2; 1 record documented. 1 not yet documented.",
    );
  });

  it("opens the month's records with the total, count, status and permitted actions only", async () => {
    await render();
    await act(async () => buttonLabelled("Manage 1 Incident record for January 2026")!.click());
    await settle();

    expect(dialog().querySelector("h2")!.textContent).toBe("January 2026 Incidents");
    expect(dialog().textContent).toContain("Reported total2");
    expect(dialog().textContent).toContain("Documented records1");
    expect(dialog().textContent).toContain("Fewer records than the total");
    expect(dialog().textContent).toContain("ZZT-2026-001");
    expect(buttonLabelled("Edit ZZT-2026-001")).not.toBeNull();
    expect(buttonLabelled("View history ZZT-2026-001")).not.toBeNull();
    // No manage permission: no Void or Reclassify. Nothing is ever called Delete.
    expect(buttonLabelled("Void ZZT-2026-001")).toBeNull();
    expect(buttonLabelled("Reclassify ZZT-2026-001")).toBeNull();
    expect(dialog().textContent).not.toMatch(/delete/i);
    const register = [...dialog().querySelectorAll("a")].find((a) => a.textContent === "Open Incident Register")!;
    expect(register.getAttribute("href")).toBe(
      "/safety/incidents/dashboard?view=register&year=2026&month=1&eventType=incident",
    );
  });

  it("opens an empty month straight on the form and adds a record dated in it, refusing a blank description", async () => {
    await render();
    await act(async () => buttonLabelled("Add Incident record for February 2026")!.click());
    await settle();
    expect(dialog().textContent).toContain("Back to February 2026 Incidents");

    const date = dialog().querySelector<HTMLInputElement>('input[type="date"]')!;
    expect([date.min, date.max, date.value]).toEqual(["2026-02-01", "2026-02-28", "2026-02-28"]);
    expect(dialog().textContent).toContain("Event type");
    const save = [...dialog().querySelectorAll("button")].find((b) => b.textContent === "Save record")!;
    await act(async () => save.click());
    expect(dialog().textContent).toContain("Describe what happened.");
    expect(patches).toEqual([]);

    const description = dialog().querySelector("textarea")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(description, "Fixture text");
      description.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => save.click());
    await settle();

    expect(patches).toEqual([
      {
        path: "/api/v1/safety/incidents/records",
        body: {
          incidentNumber: null,
          incidentDate: "2026-02-28",
          description: "Fixture text",
          areaId: null,
          classificationCategoryId: null,
          eventType: "incident",
          reportingYear: 2026,
          reportingMonth: 2,
        },
      },
    ]);
    expect(dialog().textContent).toContain("Added ZZT-2026-001.");
  });
});

describe("Annual Behavior tagging", () => {
  const behaviorInput = (code: string) => container.querySelector<HTMLInputElement>(`#behavior-2026-${code}`)!;

  async function typeBehavior(code: string, value: string) {
    const element = behaviorInput(code);
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(element, value);
      element.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }

  const saveBehavior = () =>
    [...container.querySelectorAll("button")].find((b) => b.textContent === "Save behavior counts")!;

  it("has one annual input per category, with blank and zero kept apart", async () => {
    await render();
    const card = grid("Annual Behavior tagging, 2026");

    expect(card.textContent).toContain("not monthly values");
    expect(card.textContent).toContain("one behavior tag");
    const inputs = card.querySelectorAll("input");
    expect(inputs).toHaveLength(3);
    expect(card.textContent).not.toMatch(/\bJan\b|\bDec\b/);
    expect(behaviorInput("pre_post_job_inspection").value).toBe("9");
    expect(behaviorInput("housekeeping").value).toBe("");
    expect(behaviorInput("ppe_eye").value).toBe("0");
    expect(card.textContent).toContain("Behavior tags, 2026: 9");
    expect(saveBehavior().disabled).toBe(true);
  });

  it("saves annual counts without a month and clears to unreported, not zero", async () => {
    await render();

    await typeBehavior("housekeeping", "0");
    await typeBehavior("ppe_eye", "");
    expect(grid("Annual Behavior tagging, 2026").textContent).toContain("2 unsaved changes");
    await act(async () => saveBehavior().click());

    expect(patches).toEqual([
      {
        year: 2026,
        changes: [
          { categoryId: 9, value: 0, previousValue: null },
          { categoryId: 11, value: null, previousValue: 0 },
        ],
      },
    ]);
  });

  it("refuses invalid counts", async () => {
    await render();

    await typeBehavior("housekeeping", "1.5");
    expect(grid("Annual Behavior tagging, 2026").textContent).toContain("1 count is invalid");
    expect(saveBehavior().disabled).toBe(true);
  });

  it("guards leaving the page with unsaved Behavior counts", async () => {
    await render();
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);

    await typeBehavior("housekeeping", "2");
    const link = [...container.querySelectorAll("a")].find((a) => a.textContent?.includes("View dashboard"))!;
    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    await act(async () => link.dispatchEvent(click));

    expect(confirm).toHaveBeenCalledWith("Leave without saving your changes for 2026?");
    expect(click.defaultPrevented).toBe(true);
  });
});
