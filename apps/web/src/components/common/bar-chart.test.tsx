import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { BarChart, buildBarOption } from "./bar-chart";

describe("buildBarOption", () => {
  it("keeps unreported values null instead of zero", () => {
    const option = buildBarOption(["Jan", "Feb"], [{ name: "Incidents", values: [0, null] }]);
    const [series] = option.series as { data: (number | null)[] }[];
    expect(series.data).toEqual([0, null]);
  });

  it("labels bars only when asked and applies series colors", () => {
    const plain = buildBarOption(["Jan"], [{ name: "A", values: [0] }]);
    expect((plain.series as { label: { show: boolean } }[])[0].label.show).toBe(false);
    const labelled = buildBarOption(["Jan", "Feb"], [{ name: "A", color: "#123456", values: [0, null] }], {
      showValues: true,
    });
    const [series] = labelled.series as {
      data: (number | null)[];
      label: { show: boolean };
      itemStyle: { color?: string };
    }[];
    expect(series.label.show).toBe(true);
    expect(series.data).toEqual([0, null]);
    expect(series.itemStyle.color).toBe("#123456");
  });

  it("dims category labels only where no series is reported", () => {
    const option = buildBarOption(
      ["Jan", "Feb", "Mar"],
      [
        { name: "A", values: [0, null, null] },
        { name: "B", values: [null, 2, null] },
      ],
    );
    const color = (option.xAxis as { axisLabel: { color: (v: string, i: number) => string } })
      .axisLabel.color;
    expect(color("Jan", 0)).toBe(color("Feb", 1));
    expect(color("Mar", 2)).not.toBe(color("Jan", 0));
  });

  it("puts categories on the y axis for horizontal charts", () => {
    const option = buildBarOption(["First Aid"], [{ name: "YTD", values: [1] }], {
      orientation: "horizontal",
    });
    expect(option.yAxis).toMatchObject({ type: "category", data: ["First Aid"], inverse: true });
    expect(option.xAxis).toMatchObject({ type: "value", minInterval: 1 });
  });

  it("applies hidden series through the legend selection", () => {
    const option = buildBarOption(
      ["Jan"],
      [
        { name: "A", values: [1] },
        { name: "B", values: [2] },
      ],
      { hidden: new Set(["B"]) },
    );
    expect(option.legend).toMatchObject({ show: false, selected: { A: true, B: false } });
  });

  it("escapes names in tooltips and labels unreported values", () => {
    const option = buildBarOption(["<i>Jan</i>"], [{ name: "<b>A</b>", values: [null] }]);
    const formatter = (option.tooltip as { formatter: (p: unknown) => string }).formatter;
    const html = formatter([{ name: "<i>Jan</i>", seriesName: "<b>A</b>", value: null }]);
    expect(html).toContain("&lt;i&gt;Jan&lt;/i&gt;");
    expect(html).toContain("&lt;b&gt;A&lt;/b&gt;");
    expect(html).toContain("Not reported");
  });

  it("leaves existing charts without stacks, lines or a second axis", () => {
    const option = buildBarOption(["Jan"], [{ name: "A", values: [1] }]);
    const [series] = option.series as { type: string; stack?: string }[];
    expect((option.series as unknown[]).length).toBe(1);
    expect(series.type).toBe("bar");
    expect(series.stack).toBeUndefined();
    expect(Array.isArray(option.yAxis)).toBe(false);
  });

  it("stacks series that share a stack id and labels only non-zero segments", () => {
    const option = buildBarOption(
      ["Jan", "Feb"],
      [
        { name: "A", values: [1, 0], stack: "s" },
        { name: "B", values: [null, 2], stack: "s" },
      ],
      { showValues: true },
    );
    const series = option.series as {
      stack?: string;
      data: (number | null)[];
      label: { formatter: (p: { value: unknown }) => string };
    }[];
    expect(series.map((s) => s.stack)).toEqual(["s", "s"]);
    expect(series[1].data).toEqual([null, 2]);
    expect(series[0].label.formatter({ value: 0 })).toBe("");
    expect(series[0].label.formatter({ value: 1 })).toBe("1");
  });

  it("draws lines on a named right axis, keeping gaps for unreported months", () => {
    const option = buildBarOption(["Jan", "Feb", "Mar"], [{ name: "A", values: [1, null, 2] }], {
      lines: [{ name: "Cumulative", values: [1, null, 3], axis: "right", color: "#0f172a" }],
      rightAxisName: "Cumulative",
    });
    const series = option.series as { type: string; data: (number | null)[]; yAxisIndex?: number; connectNulls?: boolean }[];
    expect(series.map((s) => s.type)).toEqual(["bar", "line"]);
    expect(series[1]).toMatchObject({ data: [1, null, 3], yAxisIndex: 1, connectNulls: false });
    expect(option.yAxis).toMatchObject([{ type: "value" }, { type: "value", name: "Cumulative" }]);
    expect(option.legend).toMatchObject({ data: ["A", "Cumulative"] });
  });

  it("fixes a percent right axis at 0–100% and formats its line as percentages", () => {
    const option = buildBarOption(["A", "B"], [{ name: "Count", values: [3, 1] }], {
      lines: [{ name: "Cumulative %", values: [75, 100], axis: "right" }],
      rightAxisPercent: true,
      labelRotate: 30,
    });
    const [left, right] = option.yAxis as { min?: number; max?: number; axisLabel?: { formatter?: string } }[];
    expect(left.max).toBeUndefined();
    expect(right).toMatchObject({ min: 0, max: 100, axisLabel: { formatter: "{value}%" } });
    expect((option.xAxis as { axisLabel: object }).axisLabel).toMatchObject({ rotate: 30, interval: 0 });
    const formatter = (option.tooltip as { formatter: (p: unknown) => string }).formatter;
    const html = formatter([
      { name: "A", seriesName: "Count", value: 3 },
      { name: "A", seriesName: "Cumulative %", value: 75 },
    ]);
    expect(html).toContain("<strong style=\"font-variant-numeric:tabular-nums\">3</strong>");
    expect(html).toContain("75.0%");
  });

  it("ignores lines on horizontal charts", () => {
    const option = buildBarOption(["A"], [{ name: "YTD", values: [1] }], {
      orientation: "horizontal",
      lines: [{ name: "L", values: [1] }],
    });
    expect((option.series as { type: string }[]).map((s) => s.type)).toEqual(["bar"]);
  });
});

describe("BarChart", () => {
  it("shows the empty state when every value is unreported", () => {
    const html = renderToStaticMarkup(
      <BarChart title="T" categories={["Jan"]} series={[{ name: "A", values: [null] }]} />,
    );
    expect(html).toContain("No data to chart");
  });

  it("labels the plot for assistive technology and renders a footer", () => {
    const html = renderToStaticMarkup(
      <BarChart
        title="PSIF by Month"
        categories={["Jan"]}
        series={[{ name: "PSIF", values: [0] }]}
        footer={<table data-testid="alternative" />}
      />,
    );
    expect(html).toContain('role="img"');
    expect(html).toContain('aria-label="PSIF by Month chart"');
    expect(html).toContain('data-testid="alternative"');
  });

  it("renders a legend only for multiple series", () => {
    const two = renderToStaticMarkup(
      <BarChart
        title="T"
        categories={["Jan"]}
        series={[
          { name: "Incidents", values: [1] },
          { name: "Near Misses", values: [0] },
        ]}
      />,
    );
    expect(two).toContain('aria-label="Series"');
    const one = renderToStaticMarkup(
      <BarChart title="T" categories={["Jan"]} series={[{ name: "YTD", values: [1] }]} />,
    );
    expect(one).not.toContain('aria-label="Series"');
  });
});
