import { describe, expect, it } from "vitest";

import { buildBarOption } from "@/components/common/bar-chart";

import {
  bars,
  classificationChart,
  combinedKpiCaption,
  formatCount,
  incompleteSeries,
  KPI_LABELS,
  kpiCaption,
  latestStartedMonth,
  monthLabels,
  monthList,
  NOTES,
  periodLabel,
  totalLabel,
} from "./analytics-data";
import type { AnalyticsKpi, AnalyticsSeries, IncidentAnalyticsResponse } from "./api";

function series(values: (number | null)[], overrides: Partial<AnalyticsSeries> = {}): AnalyticsSeries {
  const reported = values.filter((value): value is number => value !== null);
  const unreported = values.flatMap((value, index) => (value === null ? [index + 1] : []));
  return {
    section: "incident_classification",
    code: "code",
    name: "Name",
    values,
    total: reported.length ? reported.reduce((a, b) => a + b, 0) : null,
    monthsReported: reported.length,
    unreportedMonths: unreported,
    complete: values.length > 0 && unreported.length === 0,
    ...overrides,
  };
}

function kpi(overrides: Partial<AnalyticsKpi>): AnalyticsKpi {
  return { key: "incidents", value: 41, monthsReported: 9, throughMonth: 9, complete: true, parts: [], ...overrides };
}

function damage(property: number | null, equipment: number | null, overrides: Partial<AnalyticsKpi> = {}) {
  return kpi({
    key: "combined_damage",
    value: property === null && equipment === null ? null : (property ?? 0) + (equipment ?? 0),
    parts: [
      { code: "property_damage", name: "Property Damage", value: property, complete: true },
      { code: "equipment_damage_failure", name: "Equipment Damage / Failure", value: equipment, complete: true },
    ],
    ...overrides,
  });
}

describe("site calendar months", () => {
  it("runs a past year to December, the current year to this month, and a future year nowhere", () => {
    const today = { year: 2026, month: 10 };
    expect(latestStartedMonth(2025, today)).toBe(12);
    expect(latestStartedMonth(2026, today)).toBe(10);
    expect(latestStartedMonth(2027, today)).toBeNull();
  });

  it("labels the months January through the through month only", () => {
    expect(monthLabels(3)).toEqual(["Jan", "Feb", "Mar"]);
    expect(monthLabels(null)).toEqual([]);
    expect(periodLabel(2026, 9)).toBe("Jan–Sep 2026");
    expect(periodLabel(2027, 1)).toBe("Jan 2027");
    expect(monthList([2, 3])).toBe("Feb, Mar");
  });
});

describe("KPI captions", () => {
  it("states completeness without manufacturing it", () => {
    expect(kpiCaption(kpi({}), 2026)).toBe("Jan–Sep 2026 · all 9 months reported");
    expect(kpiCaption(kpi({ monthsReported: 9, throughMonth: 10, complete: false }), 2026)).toBe(
      "Jan–Oct 2026 · 9 of 10 months reported",
    );
    expect(kpiCaption(kpi({ value: null, monthsReported: 0, throughMonth: 1, complete: false }), 2027)).toBe(
      "No months reported, Jan 2027",
    );
    expect(kpiCaption(kpi({ value: null, monthsReported: 0, throughMonth: null, complete: false }), 2028)).toBe(
      "2028 has not started",
    );
  });

  it("composes the damage caption from its parts and never calls a partial total complete", () => {
    expect(combinedKpiCaption(damage(6, 8), 2026)).toBe("6 property · 8 equipment · Jan–Sep 2026, all 9 months reported");
    expect(combinedKpiCaption(damage(6, 8, { monthsReported: 1, complete: false }), 2026)).toBe(
      "6 property · 8 equipment · Jan–Sep 2026, partial, both reported in 1 of 9 months",
    );
    expect(combinedKpiCaption(damage(4, null, { monthsReported: 0, complete: false }), 2026)).toBe(
      "4 property · equipment not reported · Jan–Sep 2026, partial, both reported in 0 of 9 months",
    );
    expect(combinedKpiCaption(damage(0, 0, { throughMonth: 1, monthsReported: 1 }), 2026)).toBe(
      "0 property · 0 equipment · Jan 2026, reported",
    );
    expect(
      combinedKpiCaption(damage(null, null, { monthsReported: 0, throughMonth: 1, complete: false }), 2027),
    ).toBe("No months reported, Jan 2027");
    expect(
      combinedKpiCaption(damage(null, null, { monthsReported: 0, throughMonth: null, complete: false }), 2028),
    ).toBe("2028 has not started");
  });

  it("labels the six YTD cards", () => {
    expect(Object.values(KPI_LABELS)).toEqual([
      "Incidents YTD",
      "Near Misses YTD",
      "LOPC YTD",
      "PSIF YTD",
      "PIT Incidents YTD",
      "Property & Equipment Damage YTD",
    ]);
  });
});

describe("counts", () => {
  it("shows a reported zero as 0 and an unreported value as Not reported", () => {
    expect(formatCount(0)).toBe("0");
    expect(formatCount(null)).toBe("Not reported");
  });

  it("marks a partial total and an unreported component", () => {
    expect(totalLabel(series([1, 2], { name: "Property Damage" }))).toBe("Property Damage · 3 YTD");
    expect(totalLabel(series([1, null], { name: "Property Damage" }))).toBe("Property Damage · 1 YTD (partial)");
    expect(totalLabel(series([null], { name: "Equipment Damage / Failure" }))).toBe(
      "Equipment Damage / Failure · not reported",
    );
  });

  it("keeps null months null in chart series", () => {
    expect(bars(series([null, 0, 2]), "PSIF", "#000").values).toEqual([null, 0, 2]);
    expect(bars(undefined, "PSIF", "#000").values).toEqual([]);
  });
});

describe("chart tooltips", () => {
  it("name the month and series, with the count or Not reported", () => {
    const option = buildBarOption(["Jan", "Feb"], [bars(series([null, 0]), "Near Misses", "#0d9488")]);
    const formatter = (option.tooltip as { formatter: (p: unknown) => string }).formatter;

    const unreported = formatter([{ name: "Jan", seriesName: "Near Misses", value: null }]);
    expect(unreported).toContain("Jan");
    expect(unreported).toContain("Near Misses");
    expect(unreported).toContain("Not reported");

    const zero = formatter([{ name: "Feb", seriesName: "Near Misses", value: 0 }]);
    expect(zero).toContain(">0<");
    expect(zero).not.toContain("Not reported");

    expect(formatter([{ name: "Mar", seriesName: "Near Misses", value: Number.NaN }])).toContain("Not reported");
  });
});

describe("classification chart", () => {
  it("uses the configured labels, keeps unreported categories null, and adds nothing up", () => {
    const data = {
      classifications: [
        series([1, null], { code: "first_aid", name: "First Aid" }),
        series([null, null], { code: "fire", name: "Fire" }),
        series([0, 0], { code: "regulatory", name: "Regulatory" }),
        series([2, null], { section: "psif", code: "psif", name: "PSIF" }),
      ],
    } as IncidentAnalyticsResponse;

    const chart = classificationChart(data);

    expect(chart.categories).toEqual(["First Aid", "Fire", "Regulatory", "PSIF"]);
    expect(chart.series).toHaveLength(1);
    expect(chart.series[0].values).toEqual([1, null, 0, 2]);
  });

  it("states that classifications overlap", () => {
    expect(NOTES.classification).toBe(
      "An incident may have more than one classification, so classification counts may exceed the number of incidents.",
    );
    expect(NOTES.damage).toBe(
      "Combined damage is the sum of Property Damage and Equipment Damage classifications. One incident may carry more than one classification.",
    );
  });
});

describe("data completeness", () => {
  it("lists only series with unreported months", () => {
    const complete = series([1, 1]);
    const data = {
      incidents: complete,
      nearMisses: series([1, null]),
      lopc: complete,
      pit: complete,
      propertyDamage: { ...complete, name: "Property Damage" },
      equipmentDamage: { ...complete, name: "Equipment Damage / Failure" },
      psif: series([null, null]),
    } as IncidentAnalyticsResponse;

    expect(incompleteSeries(data)).toEqual([
      { label: "Near Misses", months: [2] },
      { label: "PSIF", months: [1, 2] },
    ]);
  });
});
