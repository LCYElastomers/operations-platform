import { cn } from "@/lib/utils";

/** Shared bordered surface recipe for panels, tables, and section shells. */
export const panelClassName = "rounded-lg border bg-card text-card-foreground";

/**
 * Hover/focus treatment for surfaces that are actually clickable
 * (links, buttons, selectable cards). Do not apply to static KPI panels.
 */
export const interactiveSurfaceClassName = "interactive-surface";

/** Pale blue selected treatment; pair with aria-pressed / aria-current when applicable. */
export const selectedSurfaceClassName = "selected-surface";

type PanelProps = React.ComponentProps<"div">;

/** Visual-only panel shell. Prefer this over ad-hoc `rounded-lg border bg-card`. */
export function Panel({ className, ...props }: PanelProps) {
  return <div className={cn(panelClassName, className)} {...props} />;
}
