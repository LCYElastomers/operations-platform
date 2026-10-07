import { describe, expect, it } from "vitest";

import type { PerformanceDashboardResponse, PerformanceMonth, RateResult } from "./api";
import {
  annualTrirChart,
  checkDraft,
  draftFromMonth,
  formatRate,
  hoursSeries,
  parseHours,
  rateCaption,
  rateTrendSeries,
  throughLabel,
  unavailableReason,
  type HoursDraft,
} from "./performance-data";

const NO_COUNTS = {
  trir: null,
  firstAid: null,
  lopc: null,
  propertyEquipmentDamage: null,
  recordableInjury: null,
  occupationalIllness: null,
  propertyDamage: null,
  equipmentDamageFailure: null,
};

function month(overrides: Partial<PerformanceMonth> = {}): PerformanceMonth {
  return {
    month: 8,
    status: "not_reported",
    hours: null,
    counts: NO_COUNTS,
    countsConfirmed: false,
    eligible: false,
    ineligibleReason: "not_reported",
    canEnter: true,
    canClose: true,
    ...overrides,
  };
}

const SAVED = month({
  status: "closed",
  hours: {
    totalHours: 18031,
    hourlyHours: null,
    salaryHours: null,
    monthClosed: true,
    updatedAt: "2026-10-06T12:00:00Z",
    updatedBy: "tester",
  },
});

function draft(overrides: Partial<HoursDraft> = {}): HoursDraft {
  return { total: "", hourly: "", salary: "", breakdown: false, closed: false, ...overrides };
}

describe("parseHours", () => {
  it.each([
    ["", null],
    ["  ", null],
    ["0", 0],
    ["18031", 18031],
    ["18,031.5", 18031.5],
    ["1000000", 1_000_000],
  ])("accepts %j", (text, value) => {
    expect(parseHours(text)).toEqual({ ok: true, value });
  });

  it.each(["-1", "1.234", "abc", "1e3", "1000000.01", "12 000"])("rejects %j", (text) => {
    expect(parseHours(text).ok).toBe(false);
  });
});

describe("checkDraft", () => {
  it("builds a create request with no expected timestamp", () => {
    const check = checkDraft(draft({ total: "17000", closed: true }), month());
    expect(check.errors).toEqual([]);
    expect(check.dirty).toBe(true);
    expect(check.request).toEqual({
      totalHours: 17000,
      hourlyHours: null,
      salaryHours: null,
      monthClosed: true,
      expectedUpdatedAt: null,
    });
  });

  it("sends the loaded timestamp for conflict protection", () => {
    const check = checkDraft({ ...draftFromMonth(SAVED), total: "18000" }, SAVED);
    expect(check.request?.expectedUpdatedAt).toBe("2026-10-06T12:00:00Z");
    expect(check.dirty).toBe(true);
  });

  it("is clean when the draft equals the stored month", () => {
    expect(checkDraft(draftFromMonth(SAVED), SAVED).dirty).toBe(false);
    expect(checkDraft(draftFromMonth(month()), month()).dirty).toBe(false);
  });

  it("requires total hours; blank is not zero", () => {
    const check = checkDraft(draft({ closed: true }), month());
    expect(check.request).toBeNull();
    expect(check.errors[0]).toMatch(/Enter total hours/);
  });

  it("checks the breakdown in cents", () => {
    const ok = checkDraft(draft({ total: "100.3", breakdown: true, hourly: "60.1", salary: "40.2" }), month());
    expect(ok.errors).toEqual([]);
    const bad = checkDraft(draft({ total: "100", breakdown: true, hourly: "60", salary: "30" }), month());
    expect(bad.errors).toEqual(["Hourly and salary hours must add up to total hours."]);
    const partial = checkDraft(draft({ total: "100", breakdown: true, hourly: "60" }), month());
    expect(partial.request?.hourlyHours).toBe(60);
    expect(partial.request?.salaryHours).toBeNull();
  });

  it("ignores hidden breakdown inputs", () => {
    const check = checkDraft(draft({ total: "100", hourly: "1", salary: "1" }), month());
    expect(check.request?.hourlyHours).toBeNull();
  });

  it("refuses to close a month that has not ended", () => {
    const check = checkDraft(draft({ total: "100", closed: true }), month({ canClose: false }));
    expect(check.request).toBeNull();
    expect(check.errors).toContain("A month can be closed only after it has ended.");
  });
});

function rate(overrides: Partial<RateResult> = {}): RateResult {
  return {
    measure: "trir",
    start: { year: 2026, month: 1 },
    end: { year: 2026, month: 8 },
    available: true,
    ineligibleMonths: [],
    events: 1,
    hours: 145194,
    rate: 1.3774673884595783,
    propertyDamage: null,
    equipmentDamageFailure: null,
    ...overrides,
  };
}

describe("rate labels", () => {
  it("labels the KPI period", () => {
    expect(throughLabel(2026, 8)).toBe("Through August 2026");
    expect(throughLabel(2026, null)).toBe("No closed months in 2026");
  });

  it("formats rates to two decimals and keeps null distinct from zero", () => {
    expect(formatRate(1.3774673884595783)).toBe("1.38");
    expect(formatRate(0)).toBe("0.00");
    expect(formatRate(null)).toBeNull();
  });

  it("shows the window, events and hours", () => {
    expect(rateCaption(rate())).toBe("Jan 2026 – Aug 2026 · 1 event ÷ 145,194 h");
    expect(
      rateCaption(rate({ measure: "property_equipment_damage", events: 13, propertyDamage: 6, equipmentDamageFailure: 7 })),
    ).toBe("Jan 2026 – Aug 2026 · 13 events (property 6, equipment 7) ÷ 145,194 h");
  });

  it("names the months that make a rate unavailable", () => {
    const result = rate({
      available: false,
      events: null,
      hours: null,
      rate: null,
      ineligibleMonths: [
        { year: 2025, month: 9, reason: "not_reported" },
        { year: 2025, month: 10, reason: "open" },
        { year: 2025, month: 11, reason: "zero_hours" },
        { year: 2025, month: 12, reason: "not_reported" },
        { year: 2026, month: 1, reason: "not_reported" },
      ],
    });
    expect(unavailableReason(result)).toBe(
      "Unavailable: Sep 2025 not reported; Oct 2025 not closed; Nov 2025 zero hours; 2 more",
    );
    expect(rateCaption(result)).toBe(unavailableReason(result));
    const blank = rate({
      available: false,
      events: null,
      hours: null,
      rate: null,
      ineligibleMonths: [
        { year: 2025, month: 9, reason: "count_not_confirmed" },
        { year: 2025, month: 11, reason: "count_not_confirmed" },
      ],
    });
    expect(unavailableReason(blank)).toBe(
      "Unavailable: Sep 2025 count not confirmed; Nov 2025 count not confirmed",
    );
  });
});

const DASHBOARD: PerformanceDashboardResponse = {
  year: 2026,
  countSource: "incidents",
  throughMonth: 8,
  kpis: [],
  ytdHours: 145194,
  months: [SAVED, month({ month: 9 })],
  trends: [
    {
      measure: "trir",
      ytd: [0, 0, 0, 0, 0, 0, 0, 1.3774673884595783, null, null, null, null],
      rolling: [null, null, null, null, null, null, null, 0.9495143234235689, null, null, null, null],
    },
  ],
  annualTrir: [
    { year: 2021, basis: "annual_legacy", partial: false, throughMonth: null, events: 1, hours: 172301, rate: 1.1607593687790553 },
    { year: 2022, basis: null, partial: false, throughMonth: null, events: null, hours: null, rate: null },
    { year: 2026, basis: "monthly", partial: true, throughMonth: 8, events: 1, hours: 145194, rate: 1.3774673884595783 },
  ],
  yearsWithData: [2026, 2025],
};

describe("chart series", () => {
  it("plots rates at month ends and skips unavailable months", () => {
    const [ytd, rolling] = rateTrendSeries(DASHBOARD, [
      { measure: "trir", window: "ytd", name: "TRIR YTD" },
      { measure: "trir", window: "rolling", name: "TRIR 12MRA" },
    ]);
    expect(ytd.points).toHaveLength(8);
    expect(ytd.points[1]).toEqual(["2026-02-28", 0]);
    expect(rolling.points).toEqual([["2026-08-31", 0.9495143234235689]]);
  });

  it("shows unreported hours as gaps", () => {
    expect(hoursSeries(DASHBOARD)[0].values).toEqual([18031, null]);
  });

  it("marks partial years as YTD and leaves years without figures empty", () => {
    const chart = annualTrirChart(DASHBOARD);
    expect(chart.categories).toEqual(["2021", "2022", "2026 YTD (Jan–Aug)"]);
    expect(chart.series[0].values).toEqual([1.16, null, 1.38]);
  });

  it("is empty without data", () => {
    expect(annualTrirChart(undefined)).toEqual({ categories: [], series: [] });
    expect(rateTrendSeries(undefined, [])).toEqual([]);
  });
});
