import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  buildOption,
  dateLabelCount,
  markerSize,
  PALETTE,
  seriesColor,
  TrendChart,
  type TrendSeries,
} from "./trend-chart";

const series = (name: string, count = 3): TrendSeries => ({
  name,
  points: Array.from({ length: count }, (_, i) => [`2026-09-${String(i + 1).padStart(2, "0")}`, i]),
});

type LineOption = { symbolSize: number; showSymbol: boolean; name: string };

function lines(option: ReturnType<typeof buildOption>): LineOption[] {
  return option.series as LineOption[];
}

describe("buildOption", () => {
  it("keeps the existing product colors first", () => {
    expect(PALETTE.slice(0, 5)).toEqual(["#2563eb", "#f59e0b", "#0d9488", "#dc2626", "#64748b"]);
    expect(buildOption([series("A")]).color).toBe(PALETTE);
    expect(seriesColor(0)).toBe("#2563eb");
    expect(seriesColor(PALETTE.length)).toBe(seriesColor(0));
  });

  it("uses one independent, data-fitted value axis", () => {
    const yAxis = buildOption([series("A")]).yAxis as { type: string; scale: boolean };
    expect(Array.isArray(yAxis)).toBe(false);
    expect(yAxis).toMatchObject({ type: "value", scale: true });
  });

  it("applies a fixed 0.0 to 1.0 axis without changing the data", () => {
    const outlier: TrendSeries = { name: "A", points: [["2026-09-01", 1.8], ["2026-09-02", 0.4]] };
    const option = buildOption([outlier], {
      yAxisRange: { min: 0, max: 1, interval: 0.2, labelDigits: 1 },
    });
    const yAxis = option.yAxis as {
      min: number;
      max: number;
      interval: number;
      scale?: boolean;
      axisLabel: { formatter: (value: number) => string };
    };
    expect([yAxis.min, yAxis.max, yAxis.interval, yAxis.scale]).toEqual([0, 1, 0.2, undefined]);
    expect([0, 0.2, 0.4, 0.6, 0.8, 1].map(yAxis.axisLabel.formatter)).toEqual([
      "0.0",
      "0.2",
      "0.4",
      "0.6",
      "0.8",
      "1.0",
    ]);
    const [line] = option.series as { data: TrendSeries["points"]; clip: boolean }[];
    expect(line.data).toEqual([["2026-09-01", 1.8], ["2026-09-02", 0.4]]);
    expect(line.clip).toBe(true);
  });

  it("always shows markers and shrinks them on dense series", () => {
    const option = buildOption([series("sparse", 30), series("dense", 400)]);
    const [sparse, dense] = lines(option);
    expect(sparse.showSymbol && dense.showSymbol).toBe(true);
    expect(sparse.symbolSize).toBeGreaterThan(dense.symbolSize);
    expect([markerSize(60), markerSize(61), markerSize(201)]).toEqual([6, 4, 3]);
  });

  it("applies hidden products through the legend selection", () => {
    const option = buildOption([series("A"), series("B")], { hidden: new Set(["B"]) });
    expect(option.legend).toMatchObject({ show: false, selected: { A: true, B: false } });
  });

  it("spaces date labels by plot width and never below one day", () => {
    const xAxis = buildOption([series("A")], { width: 1100 }).xAxis as {
      splitNumber: number;
      minInterval: number;
      axisLabel: { hideOverlap: boolean };
    };
    expect(xAxis.splitNumber).toBe(10);
    expect(xAxis.minInterval).toBe(24 * 60 * 60 * 1000);
    expect(xAxis.axisLabel.hideOverlap).toBe(true);
    expect(dateLabelCount(120)).toBe(2);
  });

  it("escapes series names in tooltips and shows missing values as no data", () => {
    const option = buildOption([series("<b>x</b>")], { precision: 2 });
    const formatter = (option.tooltip as { formatter: (p: unknown) => string }).formatter;
    const html = formatter([
      { axisValue: "2026-09-01", seriesName: "<b>x</b>", value: ["2026-09-01", null] },
      { axisValue: "2026-09-01", seriesName: "zero", value: ["2026-09-01", 0] },
    ]);
    expect(html).toContain("&lt;b&gt;x&lt;/b&gt;");
    expect(html).toContain("No data");
    expect(html).toContain("0.00");
  });
});

describe("TrendChart", () => {
  it("renders a wrapping legend above the plot, colored in series order", () => {
    const html = renderToStaticMarkup(
      <TrendChart title="Moisture Trend" series={[series("PRD-A"), series("PRD-B")]} height={340} />,
    );
    expect(html).toContain('aria-label="Products"');
    expect(html).toContain("flex-wrap");
    expect(html.indexOf("PRD-A")).toBeLessThan(html.indexOf("height:340px"));
    expect(html.indexOf(PALETTE[0])).toBeLessThan(html.indexOf(PALETTE[1]));
    expect(html).toContain('aria-pressed="true"');
  });

  it("omits the legend for a single product", () => {
    const html = renderToStaticMarkup(<TrendChart title="T" series={[series("PRD-A")]} />);
    expect(html).not.toContain('aria-label="Products"');
  });

  it("accepts card sizing from the caller", () => {
    const html = renderToStaticMarkup(
      <TrendChart title="T" series={[]} className="w-full min-h-[375px]" />,
    );
    expect(html).toContain("min-h-[375px]");
    expect(html).toContain("No data to chart");
  });
});
