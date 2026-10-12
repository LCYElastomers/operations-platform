import { describe, expect, it } from "vitest";

import {
  addMonths,
  periodFromParams,
  periodRequest,
  periodToParams,
  rangeLabel,
  resolvePeriod,
  yearsSince,
  type PeriodValue,
} from "./period";

const ALL: PeriodValue = { mode: "all" };

const dates = (value: PeriodValue, today: string) => {
  const selection = resolvePeriod(value, today)!;
  return [selection.startDate, selection.endDate];
};

describe("period presets", () => {
  it("resolves This Month, Last Month and YTD on the site date", () => {
    expect(dates({ mode: "this-month" }, "2026-10-09")).toEqual(["2026-10-01", "2026-10-31"]);
    expect(dates({ mode: "last-month" }, "2026-10-09")).toEqual(["2026-09-01", "2026-09-30"]);
    expect(dates({ mode: "ytd" }, "2026-10-09")).toEqual(["2026-01-01", "2026-10-09"]);
    expect(dates({ mode: "this-year" }, "2026-10-09")).toEqual(["2026-01-01", "2026-12-31"]);
  });

  it("crosses the year boundary in January", () => {
    expect(dates({ mode: "last-month" }, "2026-01-01")).toEqual(["2025-12-01", "2025-12-31"]);
    expect(dates({ mode: "last-3-months" }, "2026-01-15")).toEqual(["2025-11-01", "2026-01-31"]);
    expect(dates({ mode: "last-6-months" }, "2026-02-28")).toEqual(["2025-09-01", "2026-02-28"]);
    expect(dates({ mode: "ytd" }, "2026-01-01")).toEqual(["2026-01-01", "2026-01-01"]);
  });

  it("ends December and February on their last day, including leap years", () => {
    expect(dates({ mode: "this-month" }, "2026-12-31")).toEqual(["2026-12-01", "2026-12-31"]);
    expect(dates({ mode: "month", year: 2024, month: 2 }, "2026-10-09")).toEqual(["2024-02-01", "2024-02-29"]);
    expect(dates({ mode: "month", year: 2026, month: 2 }, "2026-10-09")).toEqual(["2026-02-01", "2026-02-28"]);
    expect(dates({ mode: "last-month" }, "2024-03-31")).toEqual(["2024-02-01", "2024-02-29"]);
  });

  it("resolves a year, a year and month, and a custom range", () => {
    expect(dates({ mode: "year", year: 2025 }, "2026-10-09")).toEqual(["2025-01-01", "2025-12-31"]);
    expect(resolvePeriod({ mode: "month", year: 2026, month: 8 }, "2026-10-09")!.label).toBe("August 2026");
    expect(dates({ mode: "custom", from: "2025-11-15", to: "2026-01-10" }, "2026-10-09")).toEqual(["2025-11-15", "2026-01-10"]);
  });

  it("labels the period and its dates", () => {
    expect(resolvePeriod({ mode: "ytd" }, "2026-10-09")!.fullLabel).toBe("Year to Date · Jan 1 – Oct 9, 2026");
    expect(resolvePeriod({ mode: "this-month" }, "2026-10-09")!.fullLabel).toBe("This Month · October 2026");
    expect(resolvePeriod({ mode: "year", year: 2025 }, "2026-10-09")!.fullLabel).toBe("2025");
    expect(resolvePeriod(ALL, "2026-10-09")).toMatchObject({ startDate: null, endDate: null, label: "All dates" });
    expect(rangeLabel("2025-11-01", "2026-01-31")).toBe("Nov 1, 2025 – Jan 31, 2026");
  });

  it("rejects an incomplete or reversed choice instead of guessing", () => {
    expect(resolvePeriod({ mode: "custom", from: "2026-02-10", to: "2026-02-01" }, "2026-10-09")).toBeNull();
    expect(resolvePeriod({ mode: "custom", from: "2026-02-30", to: "2026-03-01" }, "2026-10-09")).toBeNull();
    expect(resolvePeriod({ mode: "month", year: 2026, month: 13 }, "2026-10-09")).toBeNull();
    expect(resolvePeriod({ mode: "year" }, "2026-10-09")).toBeNull();
  });

  it("shifts months across years", () => {
    expect(addMonths(2026, 1, -1)).toEqual([2025, 12]);
    expect(addMonths(2025, 12, 1)).toEqual([2026, 1]);
    expect(addMonths(2026, 3, -14)).toEqual([2025, 1]);
  });
});

describe("period in the URL", () => {
  const roundTrip = (value: PeriodValue, fallback: PeriodValue = ALL) => {
    const params = new URLSearchParams("status=open");
    periodToParams(params, value, fallback);
    return { query: params.toString(), back: periodFromParams(params, fallback) };
  };

  it("writes ?period=, ?year=&month= and ?from=&to=, and reads them back", () => {
    expect(roundTrip({ mode: "ytd" })).toEqual({ query: "status=open&period=ytd", back: { mode: "ytd" } });
    expect(roundTrip({ mode: "month", year: 2026, month: 8 })).toEqual({
      query: "status=open&year=2026&month=8",
      back: { mode: "month", year: 2026, month: 8 },
    });
    expect(roundTrip({ mode: "year", year: 2025 })).toEqual({ query: "status=open&year=2025", back: { mode: "year", year: 2025 } });
    expect(roundTrip({ mode: "custom", from: "2026-01-05", to: "2026-02-01" }).query).toBe(
      "status=open&from=2026-01-05&to=2026-02-01",
    );
  });

  it("leaves the URL clean for the page's default period", () => {
    expect(roundTrip(ALL).query).toBe("status=open");
    expect(roundTrip({ mode: "this-month" }, { mode: "this-month" }).query).toBe("status=open");
  });

  it("falls back to the default for unknown or invalid values", () => {
    const read = (query: string) => periodFromParams(new URLSearchParams(query), ALL);
    expect(read("period=decade")).toEqual(ALL);
    expect(read("year=1850")).toEqual(ALL);
    expect(read("year=2026&month=0")).toEqual(ALL);
    expect(read("from=2026-03-01&to=2026-02-01")).toEqual(ALL);
    expect(read("from=yesterday&to=today")).toEqual(ALL);
  });

  it("sends the API only the fields of the chosen mode", () => {
    expect(periodRequest({ mode: "ytd", year: 2020 })).toEqual({ mode: "ytd" });
    expect(periodRequest({ mode: "month", year: 2026, month: 8 })).toEqual({ mode: "month", year: 2026, month: 8 });
    expect(periodRequest({ mode: "custom", from: "2026-01-01", to: "2026-01-31" })).toEqual({
      mode: "custom",
      from: "2026-01-01",
      to: "2026-01-31",
    });
  });

  it("offers years from the first through the current, newest first", () => {
    expect(yearsSince(2023, "2026-10-09")).toEqual([2026, 2025, 2024, 2023]);
  });
});
