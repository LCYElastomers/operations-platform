// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TrirCalculation, TrirExperience } from "./api";
import { monthCalculation, TrirExperiencePage } from "./trir-experience";

vi.mock("@/components/common/bar-chart", () => ({
  BarChart: ({ title, categories, series, lines }: { title: string; categories: string[]; series: { name: string; values: (number | null)[] }[]; lines?: { name: string; values: (number | null)[] }[] }) => (
    <div data-chart={title} data-categories={categories.join("|")} data-series={[...series, ...(lines ?? [])].map((s) => `${s.name}:${s.values.join(",")}`).join("|")} />
  ),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SOURCES = { numeratorSource: "Fixture numerator source.", denominatorSource: "Fixture denominator source." };

/** Test fixture, not production data. */
const calculation = (overrides: Partial<TrirCalculation>): TrirCalculation => ({
  year: 2003,
  basis: "safety_performance_monthly",
  fromYear: 2003,
  fromMonth: 1,
  throughMonth: 2,
  recordables: 1,
  hours: 300000,
  rate: "0.6666666666666666666666666667",
  display: "0.67",
  formula: "(1 × 200,000) ÷ 300,000",
  ...SOURCES,
  complete: true,
  missingMonths: [],
  unavailableReason: null,
  ...overrides,
});

/** Test fixture, not production data. */
const EXPERIENCE: TrirExperience = {
  year: 2003,
  status: { year: 2003, latestCompleteMonth: 2, throughMonth: 2, complete: true, historyYears: [2002] },
  current: calculation({}),
  comparison: {
    benchmarkYear: 2002,
    benchmark: "1.9",
    difference: "-1.2333333333333333333333333333",
    differenceDisplay: "-1.23",
    status: "below",
    statement: "Fixture statement: below the benchmark.",
  },
  rolling12: calculation({ fromYear: 2002, fromMonth: 3, throughMonth: 2, rate: "1", display: "1.00", formula: "(2 × 200,000) ÷ 400,000" }),
  incidentCount: 4,
  history: [
    {
      year: 2002,
      calculation: calculation({
        year: 2002,
        basis: "historical_annual",
        fromYear: null,
        fromMonth: null,
        throughMonth: null,
        recordables: 3,
        hours: 400000,
        rate: "1.5",
        display: "1.50",
        formula: "(3 × 200,000) ÷ 400,000",
      }),
      incidentCount: null,
      legacyTrir: "1.4",
      legacyTir: null,
      legacyDifference: "0.1",
      benchmark: { year: 2002, value: "1.9", source: "Fixture" },
      comparison: { benchmarkYear: 2002, benchmark: "1.9", difference: "-0.4", differenceDisplay: "-0.40", status: "below", statement: "Below." },
      partial: false,
      note: "Fixture note.",
    },
    {
      year: 2003,
      calculation: calculation({}),
      incidentCount: 4,
      legacyTrir: null,
      legacyTir: null,
      legacyDifference: null,
      benchmark: { year: 2002, value: "1.9", source: "Fixture" },
      comparison: { benchmarkYear: 2002, benchmark: "1.9", difference: null, differenceDisplay: null, status: "below", statement: "Below." },
      partial: true,
      note: null,
    },
  ],
  monthly: [
    { month: 1, state: "closed", recordables: 0, hours: 150000, ytdRecordables: 0, ytdHours: 150000, ytdRate: "0", ytdDisplay: "0.00" },
    { month: 2, state: "closed", recordables: 1, hours: 150000.5, ytdRecordables: 1, ytdHours: 300000.5, ytdRate: "0.66", ytdDisplay: "0.67" },
    { month: 3, state: "not_reported", recordables: null, hours: null, ytdRecordables: null, ytdHours: null, ytdRate: null, ytdDisplay: null },
  ],
  benchmarks: [{ year: 2002, value: "1.9", source: "Fixture" }],
  dataQuality: [{ year: 2002, check: "legacy_trir", status: "warning", message: "Fixture: recalculated 1.50, legacy 1.4." }],
  methodology: {
    formula: "TRIR = recordable cases × 200,000 ÷ hours worked",
    rateBase: 200000,
    numerator: "Fixture numerator.",
    denominator: "Fixture denominator.",
    contractorHours: "Fixture contractor note.",
    benchmark: "Fixture benchmark note.",
    cutoff: "Fixture cutoff.",
    rounding: "Fixture rounding.",
    comparisonTolerance: "Fixture tolerance.",
    historicalYears: "Fixture history.",
    unreportedMonths: "Fixture unreported.",
    legacyTir: "TIR is a legacy figure and is never used as TRIR.",
  },
};

let root: Root | null = null;
let container: HTMLDivElement;
let queryClient: QueryClient;
let requested: string[] = [];

beforeEach(() => {
  requested = [];
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  container = document.createElement("div");
  document.body.append(container);
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) => {
      requested.push(path);
      return Promise.resolve({ ok: true, status: 200, json: async () => EXPERIENCE });
    }),
  );
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  container.remove();
  queryClient.clear();
  window.localStorage.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function render() {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-03-10T15:00:00Z"));
  root = createRoot(container);
  await act(async () =>
    root!.render(
      <QueryClientProvider client={queryClient}>
        <TrirExperiencePage title="TRIR Experience" siteToday="2026-03-10" />
      </QueryClientProvider>,
    ),
  );
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

const button = (label: string) => container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!;

describe("TRIR Experience", () => {
  it("shows the live TRIR with its formula, the benchmark year it uses, and no editable hours", async () => {
    await render();

    expect(requested[0]).toBe("/api/v1/safety/trir/experience?year=2026");
    const kpis = container.querySelector('section[aria-label="TRIR"]')!.textContent;
    expect(kpis).toContain("LCY TRIR YTD0.67");
    expect(kpis).toContain("(1 × 200,000) ÷ 300,000, Jan–Feb 2003");
    expect(kpis).toContain("Industry benchmark (2002)1.9");
    expect(kpis).toContain("No 2003 benchmark; the 2002 value is shown.");
    expect(container.querySelectorAll("input:not([type=checkbox])")).toHaveLength(0);
  });

  it("explains a TRIR's numerator, denominator, source, cutoff and exact value", async () => {
    await render();
    await act(async () => button("View calculation for LCY TRIR, Jan–Feb 2003").click());

    const dialog = container.querySelector("dialog")!;
    expect(dialog.querySelector("h2")!.textContent).toBe("How LCY TRIR, Jan–Feb 2003 is calculated");
    const text = dialog.textContent;
    expect(text).toContain("(1 × 200,000) ÷ 300,000");
    expect(text).toContain("1 recordable case");
    expect(text).toContain("Fixture numerator source.");
    expect(text).toContain("300,000 hours");
    expect(text).toContain("Fixture denominator source.");
    expect(text).toContain("Jan–Feb 2003");
    expect(text).toContain("0.6666666666666666666666666667");
    expect(text).toContain("0.67 (rounded half-up to 2 decimals)");
  });

  it("names both years of a rolling 12-month period that starts in the previous year", async () => {
    await render();
    await act(async () => button("View calculation for Rolling 12-month TRIR").click());

    expect(container.querySelector("dialog")!.textContent).toContain("Mar 2002–Feb 2003");
  });

  it("offers a calculation for every TRIR in the history and monthly tables", async () => {
    await render();

    expect(button("View calculation for LCY TRIR 2002 (full year)")).not.toBeNull();
    expect(button("View calculation for LCY TRIR Jan–Feb 2003")).not.toBeNull();
    expect(button("View calculation for YTD TRIR through Feb 2003")).not.toBeNull();
    expect(button("View calculation for Rolling 12-month TRIR")).not.toBeNull();
    expect(container.textContent).toContain("differs by 0.1");
    expect(container.textContent).toContain("Fixture: recalculated 1.50, legacy 1.4.");
  });

  it("charts LCY TRIR against the benchmark, labelling a partial year", async () => {
    await render();

    const chart = container.querySelector('[data-chart="LCY TRIR vs Industry Benchmark by Year"]')!;
    expect(chart.getAttribute("data-categories")).toBe("2002|2003 (YTD)");
    expect(chart.getAttribute("data-series")).toBe("LCY TRIR:1.5,0.67|Industry benchmark:1.9,1.9");
  });

  it("hides unreported months by default and shows them on request", async () => {
    await render();
    const monthly = () => [...container.querySelectorAll("#trir-monthly ~ * tbody th, section[aria-labelledby='trir-monthly'] tbody th")].map((th) => th.textContent);

    expect(monthly()).toEqual(["Jan", "Feb"]);
    expect(container.textContent).toContain("1 unreported month hidden");
    const showAll = [...container.querySelectorAll("button")].find((b) => b.textContent === "Show all")!;
    await act(async () => showAll.click());
    expect(monthly()).toEqual(["Jan", "Feb", "Mar"]);
  });

  it("formats a month's formula as the API does", () => {
    expect(monthCalculation(EXPERIENCE, EXPERIENCE.monthly[1]).formula).toBe("(1 × 200,000) ÷ 300,000.50");
    expect(monthCalculation(EXPERIENCE, EXPERIENCE.monthly[0]).formula).toBe("(0 × 200,000) ÷ 150,000");
  });
});
