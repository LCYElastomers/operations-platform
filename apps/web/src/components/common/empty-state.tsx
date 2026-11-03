import { Inbox } from "lucide-react";

import { cn } from "@/lib/utils";

type EmptyStateProps = {
  title: string;
  description?: React.ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
  action?: React.ReactNode;
  /** "card" draws its own border; "plain" is for use inside another container. */
  variant?: "card" | "plain";
  className?: string;
};

export function EmptyState({
  title,
  description,
  icon: Icon = Inbox,
  action,
  variant = "card",
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center px-5 py-8 text-center",
        variant === "card" && "rounded-lg border border-dashed bg-card",
        className,
      )}
    >
      <div className="grid size-9 place-items-center rounded-md border bg-muted">
        <Icon className="size-4 text-muted-foreground" />
      </div>
      <h3 className="mt-3 text-sm font-semibold">{title}</h3>
      {description && (
        <p className="mt-1 max-w-md text-sm text-muted-foreground">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
