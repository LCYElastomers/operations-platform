import { describe, expect, it } from "vitest";

import type { MoistureLot } from "./api";
import {
  buildTrendSeries,
  formatDateRange,
  formatMeasurement,
  formatSourceDate,
  MISSING,
} from "./format";

const lot = (overrides: Partial<MoistureLot>): MoistureLot => ({
  product: "PRD-A",
  lot: "A260901-01",
  firstDate: "2026-09-01",
  lastDate: "2026-09-01",
  campaignNos: ["26101"],
  locations: ["Silo 1"],
  recordCount: 1,
  avgMoisture: 0.4,
  avgColor: 40,
  avgCombinedBd: 0.7,
  moistureValueCount: 1,
  colorValueCount: 1,
  combinedBdValueCount: 1,
  ...overrides,
});

describe("formatMeasurement", () => {
  it("renders zero as zero", () => {
    expect(formatMeasurement(0, 3)).toBe("0.000");
  });

  it("renders null as missing", () => {
    expect(formatMeasurement(null, 3)).toBe(MISSING);
  });

  it("rounds for display only", () => {
    expect(formatMeasurement(0.43333333333333335, 3)).toBe("0.433");
  });
});

describe("formatSourceDate", () => {
  it("does not shift dates across time zones", () => {
    expect(formatSourceDate("2026-09-01")).toBe("Sep 1, 2026");
    expect(formatSourceDate("2026-01-01")).toBe("Jan 1, 2026");
  });
});

describe("formatDateRange", () => {
  it("shows a single date when a lot was measured on one day", () => {
    expect(formatDateRange("2026-09-01", "2026-09-01")).toBe("Sep 1, 2026");
  });

  it("shows first and last measurement dates otherwise", () => {
    expect(formatDateRange("2026-09-01", "2026-09-03")).toBe("Sep 1, 2026 – Sep 3, 2026");
  });
});

describe("buildTrendSeries", () => {
  it("creates one series per product, sorted by name", () => {
    const series = buildTrendSeries(
      [
        lot({ product: "PRD-B", lastDate: "2026-09-01" }),
        lot({ product: "PRD-A", lastDate: "2026-09-02" }),
        lot({ product: "PRD-B", lastDate: "2026-09-03" }),
      ],
      "avgMoisture",
    );
    expect(series.map((s) => s.name)).toEqual(["PRD-A", "PRD-B"]);
    expect(series[1].points.map(([date]) => date)).toEqual(["2026-09-01", "2026-09-03"]);
  });

  it("plots one point per lot at its latest measurement date", () => {
    const [series] = buildTrendSeries(
      [lot({ firstDate: "2026-09-01", lastDate: "2026-09-04", avgMoisture: 0.35 })],
      "avgMoisture",
    );
    expect(series.points).toEqual([["2026-09-04", 0.35]]);
  });

  it("keeps zero values and keeps nulls as gaps", () => {
    const [series] = buildTrendSeries(
      [
        lot({ lastDate: "2026-09-01", avgColor: 0 }),
        lot({ lastDate: "2026-09-02", avgColor: null }),
        lot({ lastDate: "2026-09-03", avgColor: 41.5 }),
      ],
      "avgColor",
    );
    expect(series.points).toEqual([
      ["2026-09-01", 0],
      ["2026-09-02", null],
      ["2026-09-03", 41.5],
    ]);
  });

  it("selects only the requested measurement", () => {
    const [series] = buildTrendSeries([lot({ avgCombinedBd: 0.712233 })], "avgCombinedBd");
    expect(series.points).toEqual([["2026-09-01", 0.712233]]);
  });

  it("groups lots without a product separately", () => {
    const series = buildTrendSeries([lot({ product: null })], "avgMoisture");
    expect(series[0].name).toBe("(No product)");
  });

  it("returns no series for no lots", () => {
    expect(buildTrendSeries([], "avgMoisture")).toEqual([]);
  });

  it("orders products identically for every measurement so chart colors match", () => {
    const lots = [
      lot({ product: "PRD-C", avgColor: null }),
      lot({ product: "PRD-A", avgCombinedBd: null }),
      lot({ product: "PRD-B", avgMoisture: null }),
    ];
    const names = (["avgMoisture", "avgColor", "avgCombinedBd"] as const).map((measurement) =>
      buildTrendSeries(lots, measurement).map((s) => s.name),
    );
    expect(names).toEqual([
      ["PRD-A", "PRD-B", "PRD-C"],
      ["PRD-A", "PRD-B", "PRD-C"],
      ["PRD-A", "PRD-B", "PRD-C"],
    ]);
  });
});
