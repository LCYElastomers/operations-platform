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
  height?: number;
  emptyState?: React.ReactNode;
  className?: string;
};

export function TrendChart({
  title,
  description,
  series,
  unit,
  height = 280,
  emptyState,
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
      {hasData ? (
        <EChart series={series} unit={unit} height={height} />
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

function EChart({ series, unit, height }: { series: TrendSeries[]; unit?: string; height: number }) {
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
    chartRef.current?.setOption(buildOption(series, unit), { notMerge: true });
  }, [series, unit]);

  return <div ref={containerRef} style={{ height }} className="w-full px-2 py-3" />;
}

function buildOption(series: TrendSeries[], unit?: string): ChartOption {
  return {
    color: PALETTE,
    animation: false,
    grid: { left: 48, right: 16, top: series.length > 1 ? 36 : 16, bottom: 28 },
    legend: series.length > 1 ? { top: 0, icon: "roundRect", itemHeight: 8 } : undefined,
    tooltip: {
      trigger: "axis",
      valueFormatter: (value) =>
        value === null || value === undefined ? "No data" : `${value}${unit ? ` ${unit}` : ""}`,
    },
    xAxis: {
      type: "time",
      axisLine: { lineStyle: { color: GRID_COLOR } },
      axisLabel: { color: AXIS_COLOR },
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
      showSymbol: false,
      lineStyle: { width: 2 },
    })),
  };
}
