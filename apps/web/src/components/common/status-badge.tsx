import { cn } from "@/lib/utils";

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger" | "pending";

const toneClasses: Record<StatusTone, { badge: string; dot: string }> = {
  neutral: { badge: "border-border bg-muted text-muted-foreground", dot: "bg-muted-foreground/60" },
  info: { badge: "border-info/25 bg-info/10 text-info", dot: "bg-info" },
  success: { badge: "border-success/25 bg-success/10 text-success", dot: "bg-success" },
  warning: {
    badge: "border-warning/30 bg-warning/15 text-amber-700 dark:text-warning",
    dot: "bg-warning",
  },
  danger: { badge: "border-destructive/25 bg-destructive/10 text-destructive", dot: "bg-destructive" },
  pending: { badge: "border-border bg-muted text-muted-foreground", dot: "bg-warning" },
};

type StatusBadgeProps = {
  tone?: StatusTone;
  /** Animate the dot, e.g. while a check is in flight. */
  pulse?: boolean;
  className?: string;
  children: React.ReactNode;
};

export function StatusBadge({ tone = "neutral", pulse, className, children }: StatusBadgeProps) {
  const classes = toneClasses[tone];

  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        classes.badge,
        className,
      )}
    >
      <span aria-hidden className={cn("size-1.5 rounded-full", classes.dot, pulse && "animate-pulse")} />
      {children}
    </span>
  );
}
