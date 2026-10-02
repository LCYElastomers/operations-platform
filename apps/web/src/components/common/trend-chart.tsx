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
import { useEffect, useRef } from "react";

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

// Canvas rendering needs concrete colors; these mirror the --chart-* tokens.
const PALETTE = ["#2563eb", "#f59e0b", "#0d9488", "#dc2626", "#64748b"];
const AXIS_COLOR = "#94a3b8";
const GRID_COLOR = "#e2e8f0";

type TrendChartProps = {
  title: string;
  description?: string;
  series: TrendSeries[];
  unit?: string;
  /** Fraction digits for tooltip values. Source values are not modified. */
  precision?: number;
  height?: number;
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
  emptyState,
  loading = false,
  className,
}: TrendChartProps) {
  const hasData = series.some((s) => s.points.some(([, value]) => value !== null));

  return (
    <section className={cn("rounded-lg border bg-card text-card-foreground", className)}>
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
        <EChart series={series} unit={unit} precision={precision} height={height} />
      ) : (
        (emptyState ?? (
          <EmptyState
            variant="plain"
            icon={LineChartIcon}
            title="No data to chart"
            className="py-0"
            description="Trend data will appear here once records are available."
          />
        ))
      )}
    </section>
  );
}

function EChart({
  series,
  unit,
  precision,
  height,
}: {
  series: TrendSeries[];
  unit?: string;
  precision?: number;
  height: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

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
    chartRef.current?.setOption(buildOption(series, unit, precision), { notMerge: true });
  }, [series, unit, precision]);

  return <div ref={containerRef} style={{ height }} className="w-full px-2 py-3" />;
}

const SYMBOL_THRESHOLD = 60;

function formatAxisDate(value: unknown, withYear: boolean): string {
  const date = new Date(value as number | string);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    ...(withYear ? { year: "numeric" } : {}),
  });
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

function buildOption(series: TrendSeries[], unit?: string, precision?: number): ChartOption {
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
    grid: { left: 48, right: 16, top: series.length > 1 ? 36 : 16, bottom: 28 },
    legend: series.length > 1 ? { top: 0, icon: "roundRect", itemHeight: 8 } : undefined,
    tooltip: {
      trigger: "axis",
      // Tooltip content is HTML; series names can come from source data, so escape them.
      formatter: (raw) => {
        const params = (Array.isArray(raw) ? raw : [raw]) as TooltipParam[];
        if (params.length === 0) return "";
        const header = escapeHtml(formatAxisDate(params[0].axisValue, true));
        const rows = params.map((param) => {
          const value = Array.isArray(param.value) ? param.value[1] : param.value;
          const marker = typeof param.marker === "string" ? param.marker : "";
          return `<div style="display:flex;justify-content:space-between;gap:16px">
            <span>${marker}${escapeHtml(param.seriesName ?? "")}</span>
            <strong>${escapeHtml(formatValue(value))}</strong></div>`;
        });
        return `<div style="margin-bottom:4px">${header}</div>${rows.join("")}`;
      },
    },
    xAxis: {
      type: "time",
      axisLine: { lineStyle: { color: GRID_COLOR } },
      axisLabel: {
        color: AXIS_COLOR,
        hideOverlap: true,
        formatter: (value: number) => formatAxisDate(value, false),
      },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: AXIS_COLOR },
      splitLine: { lineStyle: { color: GRID_COLOR } },
    },
    series: series.map((s) => ({
      type: "line",
      name: s.name,
      data: s.points,
      connectNulls: false,
      showSymbol: s.points.length <= SYMBOL_THRESHOLD,
      symbolSize: 5,
      lineStyle: { width: 2 },
    })),
  };
}
