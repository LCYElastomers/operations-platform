import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api-client";

import { describeSafetyError, editConflicts, type MonthlyMetricsResponse } from "./api";
import {
  cellKey,
  cellState,
  parseCount,
  defaultReportingYear,
  FIRST_REPORTING_YEAR,
  reportingYearOptions,
  summarizeDraft,
  total,
} from "./grid";

const months = (values: Record<number, number>): (number | null)[] =>
  Array.from({ length: 12 }, (_, index) => values[index + 1] ?? null);

const metrics: MonthlyMetricsResponse = {
  metricSet: "incidents",
  year: 2026,
  canEdit: true,
  yearsWithData: [2026],
  sections: [
    {
      id: 1,
      code: "incident_classification",
      name: "Incident Classification",
      categories: [
        { id: 11, code: "first_aid", name: "First Aid", values: months({ 1: 2, 2: 0 }), ytd: 2 },
        { id: 12, code: "fire", name: "Fire", values: months({}), ytd: null },
      ],
    },
  ],
};

describe("parseCount", () => {
  it("treats blank as unreported, not zero", () => {
    expect(parseCount("")).toEqual({ ok: true, value: null });
    expect(parseCount("  ")).toEqual({ ok: true, value: null });
    expect(parseCount("0")).toEqual({ ok: true, value: 0 });
  });

  it("accepts whole non-negative counts", () => {
    expect(parseCount(" 12 ")).toEqual({ ok: true, value: 12 });
    expect(parseCount("100000")).toEqual({ ok: true, value: 100000 });
  });

  it.each(["-1", "1.5", "1e3", "abc", "1,000", "100001", "+3"])("rejects %s", (text) => {
    expect(parseCount(text)).toEqual({ ok: false });
  });
});

describe("total", () => {
  it("is null when nothing is reported and counts reported zeros", () => {
    expect(total([null, null])).toBeNull();
    expect(total([0, null])).toBe(0);
    expect(total([1, null, 2])).toBe(3);
  });
});

describe("cellState", () => {
  it("shows the stored value when not edited", () => {
    expect(cellState(0, undefined)).toEqual({ text: "0", value: 0, dirty: false, invalid: false });
    expect(cellState(null, undefined)).toEqual({ text: "", value: null, dirty: false, invalid: false });
  });

  it("is dirty only when the parsed value differs", () => {
    expect(cellState(2, "2").dirty).toBe(false);
    expect(cellState(2, " 2 ").dirty).toBe(false);
    expect(cellState(2, "").dirty).toBe(true);
    expect(cellState(null, "0").dirty).toBe(true);
  });

  it("flags invalid text and keeps the stored value for totals", () => {
    expect(cellState(2, "-4")).toEqual({ text: "-4", value: 2, dirty: true, invalid: true });
  });
});

describe("summarizeDraft", () => {
  it("sends only real changes with the value they were based on", () => {
    const summary = summarizeDraft(metrics, {
      [cellKey(11, 1)]: "3",
      [cellKey(11, 2)]: "",
      [cellKey(11, 3)]: "",
      [cellKey(12, 1)]: "0",
    });
    expect(summary.invalidCount).toBe(0);
    expect(summary.changes).toEqual([
      { categoryId: 11, month: 1, value: 3, previousValue: 2 },
      { categoryId: 11, month: 2, value: null, previousValue: 0 },
      { categoryId: 12, month: 1, value: 0, previousValue: null },
    ]);
  });

  it("counts invalid cells and never sends them", () => {
    const summary = summarizeDraft(metrics, { [cellKey(11, 1)]: "x", [cellKey(12, 1)]: "1" });
    expect(summary.invalidCount).toBe(1);
    expect(summary.changes).toEqual([{ categoryId: 12, month: 1, value: 1, previousValue: null }]);
  });
});

describe("reportingYearOptions", () => {
  it("starts at the first reporting year", () => {
    expect(FIRST_REPORTING_YEAR).toBe(2026);
    expect(reportingYearOptions(2026, [2025, 2026])).toEqual([2026]);
  });

  it("offers recent years and years with data, newest first, without duplicates", () => {
    expect(reportingYearOptions(2026, [2019, 2026], 2018)).toEqual([
      2026, 2025, 2024, 2023, 2022, 2019,
    ]);
  });

  it("exposes later years as they arrive", () => {
    expect(reportingYearOptions(2028, [2026])).toEqual([2028, 2027, 2026]);
    expect(reportingYearOptions(2026, [2027])).toEqual([2027, 2026]);
  });

  it("defaults to the current year, but never before the first reporting year", () => {
    expect(defaultReportingYear(2025)).toBe(2026);
    expect(defaultReportingYear(2029)).toBe(2029);
  });
});

describe("Safety API errors", () => {
  it("extracts edit conflicts", () => {
    const conflicts = [{ categoryId: 11, month: 1, currentValue: 4 }];
    const error = new ApiError(409, "x", { error: "edit_conflict", conflicts });
    expect(editConflicts(error)).toEqual(conflicts);
    expect(editConflicts(new ApiError(422, "x", { error: "validation_error" }))).toBeNull();
    expect(editConflicts(new Error("x"))).toBeNull();
  });

  it("explains authorization and availability failures", () => {
    expect(describeSafetyError(new ApiError(401, "x"))).toContain("Sign-in is required");
    expect(describeSafetyError(new ApiError(403, "x"))).toContain("permission");
    expect(describeSafetyError(new ApiError(503, "x"))).toContain("database");
    expect(describeSafetyError(new TypeError("fetch failed"))).toBe("The API could not be reached.");
  });
});
