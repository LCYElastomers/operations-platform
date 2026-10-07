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
});

describe("BarChart", () => {
  it("shows the empty state when every value is unreported", () => {
    const html = renderToStaticMarkup(
      <BarChart title="T" categories={["Jan"]} series={[{ name: "A", values: [null] }]} />,
    );
    expect(html).toContain("No data to chart");
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
