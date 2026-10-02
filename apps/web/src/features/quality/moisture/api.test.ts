import { describe, expect, it } from "vitest";

import {
  EMPTY_FILTERS,
  hasActiveFilters,
  isDateRangeInvalid,
  moistureKeys,
  toQueryString,
  type MoistureFilters,
} from "./api";

const filters = (overrides: Partial<MoistureFilters>): MoistureFilters => ({
  ...EMPTY_FILTERS,
  ...overrides,
});

describe("toQueryString", () => {
  it("omits unset filters", () => {
    expect(toQueryString(EMPTY_FILTERS)).toBe("");
  });

  it("sends product and location verbatim, without normalizing", () => {
    const query = new URLSearchParams(
      toQueryString(filters({ product: "PRD-A", location: "SILO 1" })),
    );
    expect(query.get("product")).toBe("PRD-A");
    expect(query.get("location")).toBe("SILO 1");
  });

  it("trims the lot/campaign search and drops it when blank", () => {
    expect(toQueryString(filters({ search: "  A2609 " }))).toBe("search=A2609");
    expect(toQueryString(filters({ search: "   " }))).toBe("");
  });

  it("uses the API's date parameter names", () => {
    const query = new URLSearchParams(
      toQueryString(filters({ startDate: "2026-09-01", endDate: "2026-09-30" })),
    );
    expect(query.get("startDate")).toBe("2026-09-01");
    expect(query.get("endDate")).toBe("2026-09-30");
  });

  it("encodes special characters", () => {
    expect(toQueryString(filters({ location: "Bay 1 & 2" }))).toBe("location=Bay+1+%26+2");
  });
});

describe("filter state helpers", () => {
  it("detects active filters", () => {
    expect(hasActiveFilters(EMPTY_FILTERS)).toBe(false);
    expect(hasActiveFilters(filters({ product: "PRD-A" }))).toBe(true);
    expect(hasActiveFilters(filters({ search: "  " }))).toBe(false);
  });

  it("flags inverted date ranges only when both ends are set", () => {
    expect(isDateRangeInvalid(filters({ startDate: "2026-09-05", endDate: "2026-09-01" }))).toBe(
      true,
    );
    expect(isDateRangeInvalid(filters({ startDate: "2026-09-01", endDate: "2026-09-01" }))).toBe(
      false,
    );
    expect(isDateRangeInvalid(filters({ startDate: "2026-09-05" }))).toBe(false);
  });

  it("keys queries by their filter query string", () => {
    expect(moistureKeys.recent("product=A")).not.toEqual(moistureKeys.recent("product=B"));
    expect(moistureKeys.recent("")).not.toEqual(moistureKeys.trends(""));
  });
});
