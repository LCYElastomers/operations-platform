import { cn } from "@/lib/utils";

/** Shared bordered surface recipe for panels, tables, and section shells. */
export const panelClassName = "rounded-lg border bg-card text-card-foreground";

type PanelProps = React.ComponentProps<"div">;

/** Visual-only panel shell. Prefer this over ad-hoc `rounded-lg border bg-card`. */
export function Panel({ className, ...props }: PanelProps) {
  return <div className={cn(panelClassName, className)} {...props} />;
}
