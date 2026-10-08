import { afterEach, describe, expect, it, vi } from "vitest";

import { monthOf, siteIsoDate, siteToday, siteYear, yearOf } from "./site-calendar";

const LAST_SECOND_OF_2026 = "2027-01-01T05:59:59Z"; // 23:59:59 CST, 31 December 2026
const BAYTOWN_NEW_YEAR = "2027-01-01T06:00:00Z"; // 00:00:00 CST, 1 January 2027
const UTC_MIDNIGHT = "2027-01-01T00:00:00Z"; // 18:00 CST, 31 December 2026

describe("site calendar", () => {
  it.each([
    [LAST_SECOND_OF_2026, "2026-12-31", 2026],
    [BAYTOWN_NEW_YEAR, "2027-01-01", 2027],
    [UTC_MIDNIGHT, "2026-12-31", 2026],
    ["2027-01-01T05:59:59.999Z", "2026-12-31", 2026],
    ["2027-01-01T06:00:00+09:00", "2026-12-31", 2026], // Tokyo already in 2027
    ["2026-12-31T22:00:00-08:00", "2027-01-01", 2027], // Los Angeles still in 2026
    ["2026-10-08T04:59:00Z", "2026-10-07", 2026], // 23:59 CDT
    ["2026-10-08T05:00:00Z", "2026-10-08", 2026], // midnight CDT
    ["2026-03-09T04:59:00Z", "2026-03-08", 2026], // daylight saving began 8 March
    ["2026-03-09T05:00:00Z", "2026-03-09", 2026],
  ])("at %s the Baytown date is %s", (instant, date, year) => {
    expect(siteIsoDate(new Date(instant))).toBe(date);
    expect(siteYear(new Date(instant))).toBe(year);
  });

  it("splits an ISO date without a time zone", () => {
    expect(yearOf("2027-01-01")).toBe(2027);
    expect(monthOf("2027-01-01")).toBe(1);
    expect(monthOf("2026-12-31")).toBe(12);
  });
});

describe("site calendar in other browser time zones", () => {
  const originalZone = process.env.TZ;

  afterEach(() => {
    vi.useRealTimers();
    process.env.TZ = originalZone;
  });

  it.each([
    // Browser zone, instant, the browser's own year, the Baytown date.
    ["America/Los_Angeles", BAYTOWN_NEW_YEAR, 2026, "2027-01-01"],
    ["America/Los_Angeles", "2027-01-01T07:30:00Z", 2026, "2027-01-01"],
    ["UTC", LAST_SECOND_OF_2026, 2027, "2026-12-31"],
    ["UTC", UTC_MIDNIGHT, 2027, "2026-12-31"],
    ["Asia/Tokyo", "2026-12-31T21:00:00Z", 2027, "2026-12-31"],
    ["Asia/Tokyo", LAST_SECOND_OF_2026, 2027, "2026-12-31"],
    ["America/Chicago", LAST_SECOND_OF_2026, 2026, "2026-12-31"],
    ["America/Chicago", BAYTOWN_NEW_YEAR, 2027, "2027-01-01"],
  ])("a browser in %s at %s still gets the Baytown date", (zone, instant, browserYear, date) => {
    process.env.TZ = zone;
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(instant));

    expect(new Date().getFullYear()).toBe(browserYear);
    expect(siteToday()).toBe(date);
    expect(yearOf(siteToday())).toBe(Number(date.slice(0, 4)));
  });
});
