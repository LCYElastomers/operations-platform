import { describe, expect, it } from "vitest";

import type { MetricCategoryRow, MonthlyMetricsResponse } from "./api";
import {
  classificationBreakdown,
  findMetric,
  incidentsVsNearMisses,
  KPI_METRICS,
  reportedCaption,
  reportedPeriod,
} from "./dashboard-data";

const months = (values: Record<number, number>): (number | null)[] =>
  Array.from({ length: 12 }, (_, index) => values[index + 1] ?? null);

const row = (id: number, code: string, values: (number | null)[], ytd: number | null) =>
  ({ id, code, name: code, values, ytd }) satisfies MetricCategoryRow;

// Classifications deliberately sum to more than Incident: they are not mutually exclusive.
const metrics: MonthlyMetricsResponse = {
  metricSet: "incidents",
  year: 2026,
  canEdit: false,
  yearsWithData: [2026],
  sections: [
    {
      id: 1,
      code: "incident_near_miss_totals",
      name: "Incident & Near Miss Totals",
      categories: [
        row(21, "near_miss", months({ 1: 5 }), 5),
        row(22, "incident", months({ 1: 2, 2: 0 }), 2),
      ],
    },
    {
      id: 2,
      code: "incident_classification",
      name: "Incident Classification",
      categories: [
        { ...row(1, "first_aid", months({ 1: 2 }), 2), name: "First Aid" },
        { ...row(2, "fire", months({ 1: 1, 2: 0 }), 1), name: "Fire" },
        { ...row(3, "regulatory", months({}), null), name: "Regulatory" },
      ],
    },
  ],
};

describe("dashboard data", () => {
  it("defines the six KPI cards in order", () => {
    expect(KPI_METRICS.map((kpi) => kpi.label)).toEqual([
      "Incident YTD",
      "Near Miss YTD",
      "LOPC YTD",
      "Property / Equipment Damage YTD",
      "PIT YTD",
      "PSIF YTD",
    ]);
  });

  it("reads Incident and Near Miss YTD from the explicit metrics, not classifications", () => {
    const [incident, nearMiss] = KPI_METRICS.map((kpi) =>
      findMetric(metrics, kpi.sectionCode, kpi.categoryCode),
    );
    expect(incident?.ytd).toBe(2);
    expect(nearMiss?.ytd).toBe(5);
  });

  it("describes the months a YTD covers", () => {
    expect(reportedPeriod(row(1, "x", months({ 1: 0, 3: 2 }), 2), 2026)).toBe("Jan–Mar 2026");
    expect(reportedPeriod(row(1, "x", months({ 4: 1 }), 1), 2026)).toBe("Apr 2026");
    expect(reportedPeriod(row(1, "x", months({}), null), 2026)).toBe(
      "No months reported for 2026",
    );
    expect(reportedPeriod(undefined, 2026)).toBe("No months reported for 2026");
  });

  it("counts reported months, including reported zeros but not gaps", () => {
    expect(reportedCaption(row(1, "x", months({ 1: 0, 3: 2 }), 2), 2026)).toBe(
      "Jan–Mar 2026 · 2 months reported",
    );
    expect(reportedCaption(row(1, "x", months({ 4: 1 }), 1), 2026)).toBe(
      "Apr 2026 · 1 month reported",
    );
    expect(reportedCaption(row(1, "x", months({}), null), 2026)).toBe(
      "No months reported for 2026",
    );
  });

  it("charts the explicit Incident and Near Miss monthly values", () => {
    const [incidents, nearMisses] = incidentsVsNearMisses(metrics);
    expect(incidents.values.slice(0, 3)).toEqual([2, 0, null]);
    expect(nearMisses.values.slice(0, 2)).toEqual([5, null]);
  });

  it("keeps unreported months null when a metric is missing", () => {
    const [incidents] = incidentsVsNearMisses(undefined);
    expect(incidents.values).toEqual(Array(12).fill(null));
  });

  it("breaks down incident classification YTD, keeping null distinct from zero", () => {
    expect(classificationBreakdown(metrics)).toMatchObject({
      categories: ["First Aid", "Fire", "Regulatory"],
      series: [{ name: "YTD", values: [2, 1, null] }],
    });
  });
});
