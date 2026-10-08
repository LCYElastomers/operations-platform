import { describe, expect, it } from "vitest";

import {
  DEFAULT_DISPLAY,
  isEmptyRow,
  parsePreferences,
  pick,
  visibleColumns,
  visibleRows,
} from "./display-controls";

describe("display preferences", () => {
  it("defaults to hiding empty rows and showing reported zeros", () => {
    expect(DEFAULT_DISPLAY).toEqual({
      hideEmptyRows: true,
      showReportedZeros: true,
      hideEmptyMonths: false,
      hiddenSeries: [],
    });
  });

  it("treats a row as empty only when every cell is null", () => {
    expect(isEmptyRow([null, null], DEFAULT_DISPLAY)).toBe(true);
    expect(isEmptyRow([null, 0], DEFAULT_DISPLAY)).toBe(false);
    expect(isEmptyRow([0, 0], DEFAULT_DISPLAY)).toBe(false);
    expect(isEmptyRow([null, null], { ...DEFAULT_DISPLAY, hideEmptyRows: false })).toBe(false);
  });

  it("hides rows of only reported zeros when zeros are not shown", () => {
    const noZeros = { ...DEFAULT_DISPLAY, showReportedZeros: false };
    expect(isEmptyRow([0, null], noZeros)).toBe(true);
    expect(isEmptyRow([0, 1], noZeros)).toBe(false);
  });

  it("counts hidden rows without changing them", () => {
    const rows = [
      { name: "a", values: [null, null] },
      { name: "b", values: [0, null] },
      { name: "c", values: [1, 2] },
    ];
    const shown = visibleRows(rows, (row) => row.values, DEFAULT_DISPLAY);
    expect(shown.rows.map((row) => row.name)).toEqual(["b", "c"]);
    expect(shown.hidden).toBe(1);
    expect(rows).toHaveLength(3);
  });

  it("hides months nobody reported, keeping months with a reported zero", () => {
    const rows = [
      [null, 0, null],
      [null, null, null],
    ];
    expect(visibleColumns(3, rows, DEFAULT_DISPLAY)).toEqual([0, 1, 2]);
    const columns = visibleColumns(3, rows, { ...DEFAULT_DISPLAY, hideEmptyMonths: true });
    expect(columns).toEqual([1]);
    expect(pick(["Jan", "Feb", "Mar"], columns)).toEqual(["Feb"]);
  });

  it("reads stored preferences defensively", () => {
    expect(parsePreferences(null)).toEqual(DEFAULT_DISPLAY);
    expect(parsePreferences("not json")).toEqual(DEFAULT_DISPLAY);
    expect(parsePreferences('{"hideEmptyRows":false,"hiddenSeries":["x",3]}')).toEqual({
      ...DEFAULT_DISPLAY,
      hideEmptyRows: false,
      hiddenSeries: ["x"],
    });
  });
});
