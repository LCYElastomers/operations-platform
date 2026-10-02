import { describe, expect, it } from "vitest";

import type { MoistureRecord } from "./api";
import { buildTrendSeries, formatMeasurement, formatSourceDate, MISSING } from "./format";

const record = (overrides: Partial<MoistureRecord>): MoistureRecord => ({
  date: "2026-09-01",
  campaignNo: "26101",
  lot: "A260901-01",
  location: "Silo 1",
  product: "PRD-A",
  avgMoisture: 0.4,
  avgColor: 40,
  avgCombinedBd: 0.7,
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

describe("buildTrendSeries", () => {
  it("creates one series per product, sorted by name", () => {
    const series = buildTrendSeries(
      [
        record({ product: "PRD-B", date: "2026-09-01" }),
        record({ product: "PRD-A", date: "2026-09-02" }),
        record({ product: "PRD-B", date: "2026-09-03" }),
      ],
      "avgMoisture",
    );
    expect(series.map((s) => s.name)).toEqual(["PRD-A", "PRD-B"]);
    expect(series[1].points.map(([date]) => date)).toEqual(["2026-09-01", "2026-09-03"]);
  });

  it("keeps zero values and keeps nulls as gaps", () => {
    const [series] = buildTrendSeries(
      [
        record({ date: "2026-09-01", avgColor: 0 }),
        record({ date: "2026-09-02", avgColor: null }),
        record({ date: "2026-09-03", avgColor: 41.5 }),
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
    const [series] = buildTrendSeries([record({ avgCombinedBd: 0.712233 })], "avgCombinedBd");
    expect(series.points).toEqual([["2026-09-01", 0.712233]]);
  });

  it("groups records without a product separately", () => {
    const series = buildTrendSeries([record({ product: null })], "avgMoisture");
    expect(series[0].name).toBe("(No product)");
  });

  it("returns no series for no points", () => {
    expect(buildTrendSeries([], "avgMoisture")).toEqual([]);
  });
});
