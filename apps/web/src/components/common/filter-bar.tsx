import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

type FilterBarProps = {
  children: React.ReactNode;
  /** Right-aligned controls such as reset or export. */
  actions?: React.ReactNode;
  className?: string;
};

export function FilterBar({ children, actions, className }: FilterBarProps) {
  return (
    <div
      role="group"
      aria-label="Filters"
      className={cn(
        "flex flex-col gap-3 rounded-lg border bg-card p-3 md:flex-row md:items-end md:justify-between",
        className,
      )}
    >
      <div className="grid flex-1 grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">{children}</div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

type FilterSelectOption = { value: string; label: string };

type FilterSelectProps = Omit<React.ComponentProps<"select">, "children"> & {
  label: string;
  options: FilterSelectOption[];
  placeholder?: string;
};

export function FilterSelect({
  label,
  options,
  placeholder = "All",
  id,
  className,
  ...props
}: FilterSelectProps) {
  const selectId = id ?? `filter-${label.toLowerCase().replace(/\s+/g, "-")}`;

  return (
    <label htmlFor={selectId} className="flex min-w-0 flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <span className="relative">
        <select
          id={selectId}
          className={cn(
            "h-9 w-full appearance-none rounded-md border border-input bg-background pr-8 pl-3 text-sm shadow-xs",
            "outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40",
            "disabled:cursor-not-allowed disabled:opacity-60",
            className,
          )}
          {...props}
        >
          <option value="">{placeholder}</option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <ChevronDown
          aria-hidden
          className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-muted-foreground"
        />
      </span>
    </label>
  );
}
