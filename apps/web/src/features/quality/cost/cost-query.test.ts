import { describe, expect, it } from "vitest";

import {
  costDashboardFromParams,
  costQueryParams,
  costRegisterFromRecord,
  costRegisterParams,
  costRegisterReportContext,
  costReportContext,
  EMPTY_COST_DASHBOARD,
  EMPTY_COST_REGISTER,
  recordQueryOf,
  summaryQueryOf,
} from "./cost-query";
import type { CostSummary } from "./api";

const TODAY = "2026-10-09";

describe("COPQ / COQ Matrix period", () => {
  const months = (period: Parameters<typeof summaryQueryOf>[0]["period"]) => {
    const { year, from, through } = summaryQueryOf({ ...EMPTY_COST_DASHBOARD, period }, TODAY, true);
    return { year, from, through };
  };

  it("maps each period to the summary's year and months", () => {
    expect(months(null)).toEqual({ year: null, from: null, through: null });
    expect(months({ mode: "this-month" })).toEqual({ year: 2026, from: 10, through: 10 });
    expect(months({ mode: "ytd" })).toEqual({ year: 2026, from: 1, through: 10 });
    expect(months({ mode: "this-year" })).toEqual({ year: 2026, from: null, through: null });
    expect(months({ mode: "year", year: 2025 })).toEqual({ year: 2025, from: null, through: null });
    expect(months({ mode: "month", year: 2025, month: 6 })).toEqual({ year: 2025, from: 6, through: 6 });
  });

  it("takes last month from the previous year in January", () => {
    const { year, from, through } = summaryQueryOf({ ...EMPTY_COST_DASHBOARD, period: { mode: "last-month" } }, "2026-01-05", false);
    expect({ year, from, through }).toEqual({ year: 2025, from: 12, through: 12 });
  });

  it("keeps the filters in the URL and drops periods the summary cannot show", () => {
    const query = { ...EMPTY_COST_DASHBOARD, period: { mode: "ytd" as const }, areaId: 3, coqClass: "internal_failure" as const };
    const params = costQueryParams(query);
    expect(params.toString()).toBe("period=ytd&areaId=3&coqClass=internal_failure");
    expect(costDashboardFromParams(Object.fromEntries(params))).toEqual(query);
    expect(costDashboardFromParams({ period: "last-3-months", coqClass: "bogus", areaId: "-2" })).toEqual(EMPTY_COST_DASHBOARD);
    expect(costQueryParams(EMPTY_COST_DASHBOARD).toString()).toBe("");
  });

  it("exports the default as the latest year the screen shows", () => {
    const data = { year: 2025 } as CostSummary;
    expect(costReportContext(EMPTY_COST_DASHBOARD, data)).toEqual({
      period: { mode: "year", year: 2025 },
      filters: { areaId: null, coqClass: null, category: null, product: null, owner: null, financialStatus: null },
    });
  });
});

describe("Quality Cost Register period", () => {
  it("resolves the item-date period for the records API", () => {
    const query = recordQueryOf({ ...EMPTY_COST_REGISTER, period: { mode: "last-month" } }, TODAY);
    expect([query.from, query.to]).toEqual(["2026-09-01", "2026-09-30"]);
    expect(recordQueryOf(EMPTY_COST_REGISTER, TODAY)).toMatchObject({ from: "", to: "" });
  });

  it("round-trips the URL and sends the same criteria to the export", () => {
    const query = { ...EMPTY_COST_REGISTER, period: { mode: "custom" as const, from: "2026-01-01", to: "2026-02-15" }, status: "open" as const, search: "drum" };
    const params = costRegisterParams(query);
    expect(params.toString()).toBe("from=2026-01-01&to=2026-02-15&status=open&search=drum");
    expect(costRegisterFromRecord(Object.fromEntries(params))).toEqual(query);
    expect(costRegisterReportContext(query)).toEqual({
      period: query.period,
      filters: {
        areaId: null,
        coqClass: null,
        category: null,
        product: null,
        owner: null,
        financialStatus: null,
        status: "open",
        search: "drum",
      },
    });
  });
});
