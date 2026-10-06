"use client";

import { LineChart, type LineSeriesOption } from "echarts/charts";
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
import { LineChart as LineChartIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import { EmptyState } from "./empty-state";

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

type ChartOption = echarts.ComposeOption<
  LineSeriesOption | GridComponentOption | LegendComponentOption | TooltipComponentOption
>;

/** [timestamp, value]. A null value is a gap in the line, not zero. */
export type TrendPoint = [time: string | number, value: number | null];

export type TrendSeries = {
  name: string;
  points: TrendPoint[];
};

/** Fixed visible y-axis scale. Data is unchanged; points outside the range are clipped. */
export type YAxisRange = {
  min: number;
  max: number;
  interval: number;
  /** Fraction digits for tick labels. */
  labelDigits: number;
};

// Canvas rendering needs concrete colors. The first five mirror the --chart-*
// tokens; the rest keep more products distinguishable before colors repeat.
export const PALETTE = [
  "#2563eb",
  "#f59e0b",
  "#0d9488",
  "#dc2626",
  "#64748b",
  "#7c3aed",
  "#db2777",
  "#65a30d",
  "#92400e",
  "#0f172a",
];
const AXIS_LABEL_COLOR = "#64748b";
const AXIS_LINE_COLOR = "#cbd5e1";
const GRID_COLOR = "#e2e8f0";
const DAY_MS = 24 * 60 * 60 * 1000;
// Roughly one date label per this many pixels of plot width.
const PIXELS_PER_DATE_LABEL = 110;

/** Series color by position. Callers keep series order stable so colors match across charts. */
export function seriesColor(index: number): string {
  return PALETTE[index % PALETTE.length];
}

type TrendChartProps = {
  title: string;
  description?: string;
  series: TrendSeries[];
  unit?: string;
  /** Fraction digits for tooltip values. Source values are not modified. */
  precision?: number;
  /** Height of the plot area in pixels. */
  height?: number;
  /** Fixed y-axis scale; when omitted the axis fits the data. */
  yAxisRange?: YAxisRange;
  emptyState?: React.ReactNode;
  loading?: boolean;
  className?: string;
};

export function TrendChart({
  title,
  description,
  series,
  unit,
  precision,
  height = 280,
  yAxisRange,
  emptyState,
  loading = false,
  className,
}: TrendChartProps) {
  const hasData = series.some((s) => s.points.some(([, value]) => value !== null));

  return (
    <section
      className={cn("flex flex-col rounded-lg border bg-card text-card-foreground", className)}
    >
      <header className="flex items-start justify-between gap-4 border-b px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">{title}</h2>
          {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
        </div>
        {unit && <span className="shrink-0 text-xs text-muted-foreground">{unit}</span>}
      </header>
      {loading ? (
        <div style={{ height }} className="p-4" aria-busy>
          <div className="size-full animate-pulse rounded-md bg-muted/70" />
        </div>
      ) : hasData ? (
        <ChartBody
          series={series}
          unit={unit}
          precision={precision}
          height={height}
          yAxisRange={yAxisRange}
        />
      ) : (
        <div className="flex flex-1 items-center justify-center">
          {emptyState ?? (
            <EmptyState
              variant="plain"
              icon={LineChartIcon}
              title="No data to chart"
              className="py-0"
              description="Trend data will appear here once records are available."
            />
          )}
        </div>
      )}
    </section>
  );
}

function ChartBody({
  series,
  unit,
  precision,
  height,
  yAxisRange,
}: {
  series: TrendSeries[];
  unit?: string;
  precision?: number;
  height: number;
  yAxisRange?: YAxisRange;
}) {
  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => new Set());

  const toggle = (name: string) =>
    setHidden((current) => {
      const next = new Set(current);
      if (!next.delete(name)) next.add(name);
      return next;
    });

  return (
    <div className="flex flex-1 flex-col gap-2 px-4 pt-3 pb-2">
      {series.length > 1 && <ChartLegend series={series} hidden={hidden} onToggle={toggle} />}
      <EChart
        series={series}
        hidden={hidden}
        unit={unit}
        precision={precision}
        height={height}
        yAxisRange={yAxisRange}
      />
    </div>
  );
}

export function ChartLegend({
  series,
  hidden,
  onToggle,
  label = "Products",
}: {
  series: { name: string }[];
  hidden: ReadonlySet<string>;
  onToggle: (name: string) => void;
  label?: string;
}) {
  return (
    <ul aria-label={label} className="flex flex-wrap gap-x-4 gap-y-1.5">
      {series.map((s, index) => {
        const visible = !hidden.has(s.name);
        return (
          <li key={s.name}>
            <button
              type="button"
              aria-pressed={visible}
              title={visible ? `Hide ${s.name}` : `Show ${s.name}`}
              onClick={() => onToggle(s.name)}
              className={cn(
                "flex items-center gap-1.5 rounded-sm text-xs font-medium transition-opacity focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                !visible && "opacity-40",
              )}
            >
              <span
                aria-hidden
                className="inline-block h-2 w-3 rounded-sm"
                style={{ backgroundColor: seriesColor(index) }}
              />
              {s.name}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function EChart({
  series,
  hidden,
  unit,
  precision,
  height,
  yAxisRange,
}: {
  series: TrendSeries[];
  hidden: ReadonlySet<string>;
  unit?: string;
  precision?: number;
  height: number;
  yAxisRange?: YAxisRange;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const chart = echarts.init(element, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    const observer = new ResizeObserver(() => {
      chart.resize();
      setWidth(element.clientWidth);
    });
    observer.observe(element);

    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(
      buildOption(series, { hidden, unit, precision, width, yAxisRange }),
      { notMerge: true },
    );
  }, [series, hidden, unit, precision, width, yAxisRange]);

  return <div ref={containerRef} style={{ height }} className="w-full" />;
}

/** Filled markers that shrink as a series gets denser, so dense stretches stay legible. */
export function markerSize(pointCount: number): number {
  if (pointCount <= 60) return 6;
  if (pointCount <= 200) return 4;
  return 3;
}

export function dateLabelCount(width: number): number {
  return Math.max(2, Math.floor(width / PIXELS_PER_DATE_LABEL));
}

function formatTooltipDate(value: unknown): string {
  const date = new Date(value as number | string);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

type TooltipParam = { axisValue?: unknown; marker?: unknown; seriesName?: string; value?: unknown };

type OptionSettings = {
  hidden?: ReadonlySet<string>;
  unit?: string;
  precision?: number;
  /** Plot width in pixels; 0 before the first measurement. */
  width?: number;
  yAxisRange?: YAxisRange;
};

export function buildOption(
  series: TrendSeries[],
  { hidden = new Set(), unit, precision, width = 0, yAxisRange }: OptionSettings = {},
): ChartOption {
  const formatValue = (value: unknown) => {
    if (typeof value !== "number") return "No data";
    const text =
      precision === undefined
        ? String(value)
        : value.toLocaleString(undefined, {
            minimumFractionDigits: precision,
            maximumFractionDigits: precision,
          });
    return unit ? `${text} ${unit}` : text;
  };

  return {
    color: PALETTE,
    animation: false,
    grid: { left: 4, right: 20, top: 12, bottom: 4, containLabel: true },
    // The visible legend is rendered in HTML above the plot so it can wrap;
    // this hidden legend only applies which series are shown.
    legend: {
      show: false,
      data: series.map((s) => s.name),
      selected: Object.fromEntries(series.map((s) => [s.name, !hidden.has(s.name)])),
    },
    tooltip: {
      trigger: "axis",
      confine: true,
      padding: [8, 12],
      textStyle: { fontSize: 12, color: "#0f172a" },
      axisPointer: { type: "line", lineStyle: { color: AXIS_LINE_COLOR } },
      // Tooltip content is HTML; series names can come from source data, so escape them.
      formatter: (raw) => {
        const params = (Array.isArray(raw) ? raw : [raw]) as TooltipParam[];
        if (params.length === 0) return "";
        const header = escapeHtml(formatTooltipDate(params[0].axisValue));
        const rows = params.map((param) => {
          const value = Array.isArray(param.value) ? param.value[1] : param.value;
          const marker = typeof param.marker === "string" ? param.marker : "";
          return `<div style="display:flex;justify-content:space-between;gap:16px;line-height:1.6">
            <span>${marker}${escapeHtml(param.seriesName ?? "")}</span>
            <strong style="font-variant-numeric:tabular-nums">${escapeHtml(formatValue(value))}</strong></div>`;
        });
        return `<div style="margin-bottom:4px;font-weight:600">${header}</div>${rows.join("")}`;
      },
    },
    xAxis: {
      type: "time",
      // Source values are daily; never subdivide a day into hourly ticks.
      minInterval: DAY_MS,
      splitNumber: width > 0 ? dateLabelCount(width) : undefined,
      axisLine: { lineStyle: { color: AXIS_LINE_COLOR } },
      axisTick: { show: true, lineStyle: { color: AXIS_LINE_COLOR } },
      axisLabel: {
        color: AXIS_LABEL_COLOR,
        fontSize: 12,
        margin: 10,
        hideOverlap: true,
        formatter: { year: "{yyyy}", month: "{MMM} {yyyy}", day: "{MMM} {d}" },
      },
      splitLine: { show: false },
    },
    yAxis: yAxisRange
      ? {
          type: "value",
          min: yAxisRange.min,
          max: yAxisRange.max,
          interval: yAxisRange.interval,
          axisLabel: {
            color: AXIS_LABEL_COLOR,
            fontSize: 12,
            formatter: (value: number) => value.toFixed(yAxisRange.labelDigits),
          },
          splitLine: { lineStyle: { color: GRID_COLOR } },
        }
      : {
          type: "value",
          scale: true,
          axisLabel: { color: AXIS_LABEL_COLOR, fontSize: 12 },
          splitLine: { lineStyle: { color: GRID_COLOR } },
        },
    series: series.map((s) => ({
      type: "line",
      name: s.name,
      data: s.points,
      connectNulls: false,
      clip: true,
      showSymbol: true,
      symbol: "circle",
      symbolSize: markerSize(s.points.length),
      itemStyle: { borderColor: "#ffffff", borderWidth: 1 },
      lineStyle: { width: 2 },
      emphasis: { scale: 1.6 },
    })),
  };
}
