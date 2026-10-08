"use client";

import {
  BarChart as EBarChart,
  type BarSeriesOption,
  LineChart as ELineChart,
  type LineSeriesOption,
} from "echarts/charts";
import {
  GridComponent,
  type GridComponentOption,
  LegendComponent,
  type LegendComponentOption,
  TooltipComponent,
  type TooltipComponentOption,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { ChartColumn } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import { EmptyState } from "./empty-state";
import { ChartLegend, PALETTE } from "./trend-chart";

echarts.use([
  EBarChart,
  ELineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
]);

type ChartOption = echarts.ComposeOption<
  | BarSeriesOption
  | LineSeriesOption
  | GridComponentOption
  | LegendComponentOption
  | TooltipComponentOption
>;

/** One value per category. null means "not reported" and draws no bar; 0 is a value. */
export type BarSeries = {
  name: string;
  values: (number | null)[];
  /** Defaults to the shared palette by position. */
  color?: string;
  /** Series with the same stack id are stacked on one bar. */
  stack?: string;
};

/**
 * A line drawn over the bars (vertical charts only). null leaves a gap in the
 * line; 0 is a point.
 */
export type LineSeries = {
  name: string;
  values: (number | null)[];
  color?: string;
  /** "right" plots against a second value axis, e.g. a cumulative total. */
  axis?: "left" | "right";
  dashed?: boolean;
};

const AXIS_LABEL_COLOR = "#64748b";
/** Categories with no reported value in any series. */
const UNREPORTED_LABEL_COLOR = "#b6c0cd";
const AXIS_LINE_COLOR = "#cbd5e1";
const GRID_COLOR = "#e2e8f0";
const NO_LINES: LineSeries[] = [];

type BarChartProps = {
  title: string;
  description?: string;
  /** Category axis labels, in display order. */
  categories: string[];
  series: BarSeries[];
  /** Lines over the bars; ignored for horizontal charts. */
  lines?: LineSeries[];
  /** Name of the right value axis, shown when a line uses it. */
  rightAxisName?: string;
  /** "vertical" bars rise from the x axis; "horizontal" bars suit long category labels. */
  orientation?: "vertical" | "horizontal";
  /** Height of the plot area in pixels. */
  height?: number;
  /** Print each value on its bar. A reported 0 is labelled; an unreported value draws nothing. */
  showValues?: boolean;
  emptyState?: React.ReactNode;
  loading?: boolean;
  /** Below the plot, e.g. a data table alternative to the chart. */
  footer?: React.ReactNode;
  className?: string;
};

export function BarChart({
  title,
  description,
  categories,
  series,
  lines = NO_LINES,
  rightAxisName,
  orientation = "vertical",
  height = 280,
  showValues = false,
  emptyState,
  loading = false,
  footer,
  className,
}: BarChartProps) {
  const hasData = [...series, ...lines].some((s) => s.values.some((value) => value !== null));

  return (
    <section
      className={cn("flex flex-col rounded-lg border bg-card text-card-foreground", className)}
    >
      <header className="flex items-start justify-between gap-4 border-b px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">{title}</h2>
          {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
        </div>
      </header>
      {loading ? (
        <div style={{ height }} className="p-4" aria-busy>
          <div className="size-full animate-pulse rounded-md bg-muted/70" />
        </div>
      ) : hasData ? (
        <BarChartBody
          title={title}
          categories={categories}
          series={series}
          lines={orientation === "vertical" ? lines : NO_LINES}
          rightAxisName={rightAxisName}
          orientation={orientation}
          height={height}
          showValues={showValues}
        />
      ) : (
        <div className="flex flex-1 items-center justify-center">
          {emptyState ?? (
            <EmptyState
              variant="plain"
              icon={ChartColumn}
              title="No data to chart"
              className="py-0"
              description="Values will appear here once they are reported."
            />
          )}
        </div>
      )}
      {footer && !loading && <div className="border-t px-4 py-2">{footer}</div>}
    </section>
  );
}

function BarChartBody({
  title,
  categories,
  series,
  lines,
  rightAxisName,
  orientation,
  height,
  showValues,
}: {
  title: string;
  categories: string[];
  series: BarSeries[];
  lines: LineSeries[];
  rightAxisName?: string;
  orientation: "vertical" | "horizontal";
  height: number;
  showValues: boolean;
}) {
  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => new Set());
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  const toggle = (name: string) =>
    setHidden((current) => {
      const next = new Set(current);
      if (!next.delete(name)) next.add(name);
      return next;
    });

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const chart = echarts.init(element, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element);

    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(
      buildBarOption(categories, series, { hidden, orientation, showValues, lines, rightAxisName }),
      { notMerge: true },
    );
  }, [categories, series, lines, rightAxisName, hidden, orientation, showValues]);

  const legend = [...series, ...lines];
  return (
    <div className="flex flex-1 flex-col gap-2 px-4 pt-3 pb-2">
      {legend.length > 1 && (
        <ChartLegend series={legend} hidden={hidden} onToggle={toggle} label="Series" />
      )}
      <div ref={containerRef} role="img" aria-label={`${title} chart`} style={{ height }} className="w-full" />
    </div>
  );
}

function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

type TooltipParam = { name?: string; marker?: unknown; seriesName?: string; value?: unknown };

export function buildBarOption(
  categories: string[],
  series: BarSeries[],
  {
    hidden = new Set(),
    orientation = "vertical",
    showValues = false,
    lines = NO_LINES,
    rightAxisName,
  }: {
    hidden?: ReadonlySet<string>;
    orientation?: "vertical" | "horizontal";
    showValues?: boolean;
    lines?: LineSeries[];
    rightAxisName?: string;
  } = {},
): ChartOption {
  const plotted = orientation === "vertical" ? lines : NO_LINES;
  const unreported = categories.map((_, index) =>
    [...series, ...plotted].every((s) => s.values[index] === null || s.values[index] === undefined),
  );
  const rightAxis = plotted.some((line) => line.axis === "right");
  const stacked = series.some((s) => s.stack !== undefined);
  const categoryAxis = {
    type: "category" as const,
    data: categories,
    // Horizontal charts list the first category at the top.
    inverse: orientation === "horizontal",
    axisLine: { lineStyle: { color: AXIS_LINE_COLOR } },
    axisTick: { show: false },
    axisLabel: {
      fontSize: 12,
      color: (_value?: string | number, index?: number) =>
        index !== undefined && unreported[index] ? UNREPORTED_LABEL_COLOR : AXIS_LABEL_COLOR,
    },
  };
  const valueAxis = {
    type: "value" as const,
    // Counts: never subdivide into fractional ticks.
    minInterval: 1,
    axisLabel: { color: AXIS_LABEL_COLOR, fontSize: 12 },
    splitLine: { lineStyle: { color: GRID_COLOR } },
  };

  return {
    color: PALETTE,
    animation: false,
    // Extra room on the value side so labels on the longest bar are not clipped.
    grid: {
      left: 4,
      right: showValues && orientation === "horizontal" ? 32 : 20,
      top: showValues && orientation === "vertical" ? 22 : 12,
      bottom: 4,
      containLabel: true,
    },
    legend: {
      show: false,
      data: [...series, ...plotted].map((s) => s.name),
      selected: Object.fromEntries(
        [...series, ...plotted].map((s) => [s.name, !hidden.has(s.name)]),
      ),
    },
    tooltip: {
      trigger: "axis",
      confine: true,
      padding: [8, 12],
      textStyle: { fontSize: 12, color: "#0f172a" },
      axisPointer: { type: "shadow" },
      // Tooltip content is HTML; category and series names are escaped.
      formatter: (raw) => {
        const params = (Array.isArray(raw) ? raw : [raw]) as TooltipParam[];
        if (params.length === 0) return "";
        const header = escapeHtml(params[0].name ?? "");
        const rows = params.map((param) => {
          const value =
            typeof param.value === "number" && Number.isFinite(param.value)
              ? param.value.toLocaleString()
              : "Not reported";
          const marker = typeof param.marker === "string" ? param.marker : "";
          return `<div style="display:flex;justify-content:space-between;gap:16px;line-height:1.6">
            <span>${marker}${escapeHtml(param.seriesName ?? "")}</span>
            <strong style="font-variant-numeric:tabular-nums">${escapeHtml(value)}</strong></div>`;
        });
        return `<div style="margin-bottom:4px;font-weight:600">${header}</div>${rows.join("")}`;
      },
    },
    xAxis: orientation === "horizontal" ? valueAxis : categoryAxis,
    yAxis:
      orientation === "horizontal"
        ? categoryAxis
        : rightAxis
          ? [
              valueAxis,
              {
                ...valueAxis,
                name: rightAxisName,
                nameTextStyle: { color: AXIS_LABEL_COLOR, fontSize: 11 },
                splitLine: { show: false },
              },
            ]
          : valueAxis,
    series: [
      ...series.map(
        (s): BarSeriesOption => ({
          type: "bar",
          name: s.name,
          // null stays null: ECharts draws no bar, distinct from a zero-height bar.
          data: s.values,
          barMaxWidth: 28,
          ...(s.stack !== undefined && { stack: s.stack }),
          itemStyle: {
            // Stacked segments are square so the stack reads as one bar.
            borderRadius: stacked ? 0 : orientation === "horizontal" ? [0, 3, 3, 0] : [3, 3, 0, 0],
            ...(s.color && { color: s.color }),
          },
          label: {
            show: showValues,
            position: stacked ? "inside" : orientation === "horizontal" ? "right" : "top",
            color: stacked ? "#ffffff" : "#334155",
            fontSize: 11,
            fontWeight: 600,
            // A stacked zero has no height to hold a label.
            ...(stacked && { formatter: (p: { value?: unknown }) => (p.value ? String(p.value) : "") }),
          },
        }),
      ),
      ...plotted.map(
        (line): LineSeriesOption => ({
          type: "line",
          name: line.name,
          // null leaves a gap; the line never invents a value for an unreported month.
          data: line.values,
          connectNulls: false,
          yAxisIndex: line.axis === "right" ? 1 : 0,
          symbol: "circle",
          symbolSize: 6,
          lineStyle: { width: 2, ...(line.dashed && { type: "dashed" as const }) },
          ...(line.color && { itemStyle: { color: line.color }, color: line.color }),
          z: 3,
        }),
      ),
    ],
  };
}
