"use client";

import { CalendarRange, ChevronDown, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  isIsoDate,
  MONTH_NAMES,
  PRESET_LABELS,
  resolvePeriod,
  type PeriodConfig,
  type PeriodValue,
} from "@/lib/period";
import { cn } from "@/lib/utils";

type PeriodFilterProps = {
  value: PeriodValue;
  onChange: (value: PeriodValue) => void;
  /** The site date (YYYY-MM-DD) the presets are resolved against. */
  today: string;
  config: PeriodConfig;
  label?: string;
  /** What the period applies to, e.g. "Request date". */
  hint?: string;
  className?: string;
};

const fieldClasses =
  "h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 pointer-coarse:h-11";

/**
 * The global period picker: a compact trigger showing the chosen period, and a
 * panel (a popover on desktop, a bottom sheet on small screens) with quick
 * presets, browsing by year / month and a custom date range. The resolved
 * dates are always shown under the trigger.
 */
export function PeriodFilter({ value, onChange, today, config, label = "Period", hint, className }: PeriodFilterProps) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const selection = resolvePeriod(value, today);

  const close = (refocus = true) => {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  };

  useEffect(() => {
    if (!open) return;
    panel.current?.querySelector<HTMLElement>("button, select, input")?.focus();
    const onPointer = (event: PointerEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open]);

  const choose = (next: PeriodValue) => {
    onChange(next);
    close();
  };

  return (
    <div ref={root} className={cn("relative flex min-w-0 flex-col gap-1", className)}>
      <span id={`${id}-label`} className="text-xs font-medium text-muted-foreground">
        {label}
      </span>
      <button
        ref={trigger}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? `${id}-panel` : undefined}
        aria-labelledby={`${id}-label ${id}-value`}
        onClick={() => setOpen((current) => !current)}
        className={cn(fieldClasses, "flex items-center gap-2 text-left")}
      >
        <CalendarRange aria-hidden className="size-4 shrink-0 text-muted-foreground" />
        <span id={`${id}-value`} className="min-w-0 flex-1 truncate font-medium">
          {selection?.label ?? "Choose a period"}
        </span>
        <ChevronDown aria-hidden className="size-4 shrink-0 text-muted-foreground" />
      </button>
      <span className="truncate text-xs text-muted-foreground" data-testid="period-range">
        {selection ? selection.rangeLabel || "Every date" : ""}
        {hint && selection ? ` · ${hint}` : ""}
      </span>
      {open && (
        <>
          <div aria-hidden className="fixed inset-0 z-30 bg-slate-950/40 sm:hidden" onClick={() => close(false)} />
          <div
            ref={panel}
            id={`${id}-panel`}
            role="dialog"
            aria-label={`Choose ${label.toLowerCase()}`}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.stopPropagation();
                close();
              }
            }}
            className={cn(
              "z-40 space-y-4 border bg-popover bg-card p-4 text-sm shadow-lg",
              "fixed inset-x-0 bottom-0 max-h-[85dvh] overflow-y-auto rounded-t-xl",
              "sm:absolute sm:inset-x-auto sm:top-full sm:bottom-auto sm:left-0 sm:mt-1 sm:w-[24rem] sm:rounded-lg",
            )}
          >
            <div className="flex items-center justify-between sm:hidden">
              <p className="font-semibold">Choose {label.toLowerCase()}</p>
              <button
                type="button"
                aria-label="Close"
                onClick={() => close()}
                className="grid size-11 place-items-center rounded-md text-muted-foreground hover:bg-muted"
              >
                <X className="size-4" />
              </button>
            </div>
            <PanelBody value={value} today={today} config={config} onChoose={choose} />
          </div>
        </>
      )}
    </div>
  );
}

function PanelBody({
  value,
  today,
  config,
  onChoose,
}: {
  value: PeriodValue;
  today: string;
  config: PeriodConfig;
  onChoose: (value: PeriodValue) => void;
}) {
  const id = useId();
  const currentYear = Number(today.slice(0, 4));
  const [year, setYear] = useState(value.year ?? config.years[0] ?? currentYear);
  const [month, setMonth] = useState<number | "">(value.mode === "month" ? (value.month ?? "") : "");
  const [from, setFrom] = useState(value.mode === "custom" ? (value.from ?? "") : "");
  const [to, setTo] = useState(value.mode === "custom" ? (value.to ?? "") : "");
  const customError =
    from && to && isIsoDate(from) && isIsoDate(to) && to < from
      ? "The To date is before the From date."
      : null;
  const customReady = isIsoDate(from) && isIsoDate(to) && !customError;

  return (
    <>
      {config.presets.length > 0 && (
        <section aria-labelledby={`${id}-quick`} className="space-y-2">
          <h3 id={`${id}-quick`} className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            Quick select
          </h3>
          <div className="grid grid-cols-2 gap-2">
            {config.presets.map((mode) => {
              const active = value.mode === mode;
              return (
                <button
                  key={mode}
                  type="button"
                  aria-pressed={active}
                  onClick={() => onChoose({ mode })}
                  className={cn(
                    "rounded-md border px-3 py-2 text-left text-sm hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none pointer-coarse:py-3",
                    active && "border-primary bg-primary/5 font-semibold",
                  )}
                >
                  {active && <span className="sr-only">Selected: </span>}
                  {PRESET_LABELS[mode]}
                </button>
              );
            })}
          </div>
        </section>
      )}
      {config.browse && config.years.length > 0 && (
        <section aria-labelledby={`${id}-browse`} className="space-y-2">
          <h3 id={`${id}-browse`} className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            Browse
          </h3>
          <div className="flex items-end gap-2">
            <label className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="text-xs text-muted-foreground">Year</span>
              <select className={fieldClasses} value={year} onChange={(event) => setYear(Number(event.target.value))}>
                {config.years.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            {config.browse === "year-month" && (
              <label className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="text-xs text-muted-foreground">Month</span>
                <select
                  className={fieldClasses}
                  value={month}
                  onChange={(event) => setMonth(event.target.value ? Number(event.target.value) : "")}
                >
                  <option value="">Whole year</option>
                  {MONTH_NAMES.map((name, index) => (
                    <option key={name} value={index + 1}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <Button
              size="sm"
              className="h-9 pointer-coarse:h-11"
              onClick={() => onChoose(month === "" ? { mode: "year", year } : { mode: "month", year, month })}
            >
              Apply
            </Button>
          </div>
        </section>
      )}
      {config.custom && (
        <section aria-labelledby={`${id}-custom`} className="space-y-2">
          <h3 id={`${id}-custom`} className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            Custom range
          </h3>
          <div className="flex items-end gap-2">
            <label className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="text-xs text-muted-foreground">From</span>
              <input type="date" className={fieldClasses} value={from} max={to || undefined} onChange={(event) => setFrom(event.target.value)} />
            </label>
            <label className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="text-xs text-muted-foreground">To</span>
              <input type="date" className={fieldClasses} value={to} min={from || undefined} onChange={(event) => setTo(event.target.value)} />
            </label>
            <Button
              size="sm"
              className="h-9 pointer-coarse:h-11"
              disabled={!customReady}
              onClick={() => onChoose({ mode: "custom", from, to })}
            >
              Apply
            </Button>
          </div>
          {customError && (
            <p role="alert" className="text-xs text-destructive">
              {customError}
            </p>
          )}
        </section>
      )}
    </>
  );
}
