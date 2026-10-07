import { describe, expect, it } from "vitest";

import type { CategoryCount, ObservationCounts, ObservationDashboardResponse } from "./api";
import {
  actConditionBreakdown,
  categoriesWithObservations,
  categoryOverTime,
  categoryYearToDate,
  draftFromObservation,
  emptyDraft,
  formatObservedOn,
  formatShare,
  localIsoDate,
  MAX_AREA_LOCATION_LENGTH,
  MAX_NOTE_LENGTH,
  monthlySafeVsUnsafe,
  nextDraft,
  runningTotals,
  summaryTiles,
  toInput,
  validateDraft,
  type ObservationDraft,
} from "./observation-data";

const TODAY = "2026-10-07";

function draft(overrides: Partial<ObservationDraft> = {}): ObservationDraft {
  return {
    ...emptyDraft("2026-10-06"),
    outcome: "unsafe",
    kind: "condition",
    categoryId: 9,
    ...overrides,
  };
}

function counts(safe: [number, number], unsafe: [number, number]): ObservationCounts {
  return {
    total: safe[0] + safe[1] + unsafe[0] + unsafe[1],
    safe: safe[0] + safe[1],
    unsafe: unsafe[0] + unsafe[1],
    safeAct: safe[0],
    safeCondition: safe[1],
    unsafeAct: unsafe[0],
    unsafeCondition: unsafe[1],
  };
}

const DASHBOARD: ObservationDashboardResponse = {
  year: 2026,
  throughMonth: 10,
  counts: counts([2, 1], [1, 2]),
  unsafeShare: 0.5,
  months: Array.from({ length: 12 }, (_, index) => ({
    month: index + 1,
    counts:
      index === 0
        ? counts([2, 0], [0, 1])
        : index === 9
          ? counts([0, 1], [1, 1])
          : index < 10
            ? counts([0, 0], [0, 0])
            : null,
  })),
  categories: [
    { categoryId: 1, code: "housekeeping", name: "Housekeeping", total: 4, safe: 2, unsafe: 2,
      monthly: [2, 0, 0, 0, 0, 0, 0, 0, 0, 2, null, null] },
    { categoryId: 2, code: "fire", name: "Fire", total: 2, safe: 1, unsafe: 1,
      monthly: [1, 0, 0, 0, 0, 0, 0, 0, 0, 1, null, null] },
  ],
  yearsWithData: [2026],
};  // prettier-ignore

describe("draft validation", () => {
  it("accepts a complete draft", () => {
    expect(validateDraft(draft(), TODAY)).toEqual({});
  });

  it("requires date, outcome, kind, and category", () => {
    const errors = validateDraft(emptyDraft(""), TODAY);
    expect(Object.keys(errors).sort()).toEqual(["categoryId", "kind", "observedOn", "outcome"]);
  });

  it.each([
    ["2026-10-08", "The date cannot be in the future."],
    ["2026-02-30", "Enter a valid date."],
    ["10/06/2026", "Enter a valid date."],
    ["1999-12-31", "The date is too early."],
  ])("rejects the date %s", (observedOn, message) => {
    expect(validateDraft(draft({ observedOn }), TODAY).observedOn).toBe(message);
  });

  it("accepts today", () => {
    expect(validateDraft(draft({ observedOn: TODAY }), TODAY)).toEqual({});
  });

  it("limits text lengths like the API", () => {
    const errors = validateDraft(
      draft({
        areaLocation: "x".repeat(MAX_AREA_LOCATION_LENGTH + 1),
        description: "x".repeat(MAX_NOTE_LENGTH + 1),
        correctiveAction: "x".repeat(MAX_NOTE_LENGTH + 1),
      }),
      TODAY,
    );
    expect(Object.keys(errors).sort()).toEqual(["areaLocation", "correctiveAction", "description"]);
    expect(validateDraft(draft({ areaLocation: ` ${"x".repeat(200)} ` }), TODAY)).toEqual({});
  });
});

describe("request body", () => {
  it("trims text and sends blank optional text as null", () => {
    expect(
      toInput(draft({ areaLocation: "  Dock 3 ", description: "   ", correctiveAction: "" })),
    ).toEqual({
      observedOn: "2026-10-06",
      outcome: "unsafe",
      kind: "condition",
      categoryId: 9,
      areaLocation: "Dock 3",
      description: null,
      correctiveAction: null,
    });
  });

  it("refuses an incomplete draft", () => {
    expect(() => toInput(emptyDraft(TODAY))).toThrow();
  });

  it("keeps only the date for the next observation", () => {
    const next = nextDraft(draft({ areaLocation: "Dock 3", description: "x" }));
    expect(next).toEqual(emptyDraft("2026-10-06"));
    expect(next.outcome).toBeNull();
    expect(next.categoryId).toBeNull();
  });

  it("edits start from the stored values", () => {
    const edit = draftFromObservation({
      id: 1,
      observedOn: "2026-10-01",
      outcome: "safe",
      kind: "act",
      categoryId: 3,
      categoryCode: "ppe",
      categoryName: "PPE",
      areaLocation: null,
      description: "Worn correctly",
      correctiveAction: null,
      createdAt: "",
      createdBy: "",
      updatedAt: "",
      updatedBy: "",
    });
    expect(edit).toMatchObject({ outcome: "safe", areaLocation: "", description: "Worn correctly" });
  });
});

describe("dates", () => {
  it("uses the local calendar date", () => {
    expect(localIsoDate(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
  });

  it("formats a date without shifting it through a time zone", () => {
    expect(formatObservedOn("2026-10-06")).toBe("Tue, Oct 6, 2026");
  });
});

describe("month summary", () => {
  it("lists every count in order, all from the same records", () => {
    const tiles = summaryTiles(counts([1, 2], [3, 4]));
    expect(tiles.map((t) => [t.label, t.value])).toEqual([
      ["Total", 10],
      ["Safe", 3],
      ["Unsafe", 7],
      ["Safe Act", 1],
      ["Safe Condition", 2],
      ["Unsafe Act", 3],
      ["Unsafe Condition", 4],
    ]);
  });

  it("shows categories with observations, most first", () => {
    const category = (categoryId: number, total: number): CategoryCount => ({
      categoryId,
      code: `c${categoryId}`,
      name: `C${categoryId}`,
      total,
      safe: total,
      unsafe: 0,
    });
    const shown = categoriesWithObservations([category(1, 1), category(2, 0), category(3, 4), category(4, 1)]);
    expect(shown.map((c) => c.categoryId)).toEqual([3, 1, 4]);
  });
});

describe("dashboard series", () => {
  it("leaves months that have not started empty, not zero", () => {
    const [safe, unsafe] = monthlySafeVsUnsafe(DASHBOARD);
    expect(safe.values).toEqual([2, 0, 0, 0, 0, 0, 0, 0, 0, 1, null, null]);
    expect(unsafe.values).toEqual([1, 0, 0, 0, 0, 0, 0, 0, 0, 2, null, null]);
  });

  it("has no values before data loads", () => {
    expect(monthlySafeVsUnsafe(undefined)[0].values.every((v) => v === null)).toBe(true);
    expect(runningTotals(undefined, TODAY)).toEqual([]);
  });

  it("splits Safe and Unsafe by Act and Condition", () => {
    expect(actConditionBreakdown(DASHBOARD)).toMatchObject({
      categories: ["Act", "Condition"],
      series: [
        { name: "Safe", values: [2, 1] },
        { name: "Unsafe", values: [1, 2] },
      ],
    });
  });

  it("charts categories in display order", () => {
    const chart = categoryYearToDate(DASHBOARD);
    expect(chart.categories).toEqual(["Housekeeping", "Fire"]);
    expect(chart.series.map((s) => s.values)).toEqual([
      [2, 1],
      [2, 1],
    ]);
  });

  it("accumulates running totals through each started month", () => {
    const [safe, unsafe] = runningTotals(DASHBOARD, TODAY);
    expect(safe.points).toHaveLength(10);
    expect(safe.points[0]).toEqual(["2026-01-31", 2]);
    expect(safe.points[1]).toEqual(["2026-02-28", 2]);
    expect(safe.points.at(-1)).toEqual([TODAY, 3]);
    expect(unsafe.points.at(-1)).toEqual([TODAY, 3]);
  });

  it("charts one category over time", () => {
    const [series] = categoryOverTime(DASHBOARD, "fire");
    expect(series.name).toBe("Fire");
    expect(series.values).toEqual([1, 0, 0, 0, 0, 0, 0, 0, 0, 1, null, null]);
    expect(categoryOverTime(DASHBOARD, "missing")[0].values.every((v) => v === null)).toBe(true);
  });

  it("formats the unsafe share, with no share when there are no observations", () => {
    expect(formatShare(0.5)).toBe("50%");
    expect(formatShare(1 / 3)).toBe("33%");
    expect(formatShare(0)).toBe("0%");
    expect(formatShare(null)).toBeNull();
  });
});
