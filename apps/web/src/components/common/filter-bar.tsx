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
      <div className="grid flex-1 grid-cols-1 gap-3 sm:grid-cols-[repeat(auto-fit,minmax(10rem,1fr))]">
        {children}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

const controlClasses = cn(
  "h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs",
  "outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40",
  "disabled:cursor-not-allowed disabled:opacity-60",
);

function controlId(label: string) {
  return `filter-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
}

type FilterInputProps = React.ComponentProps<"input"> & { label: string };

export function FilterInput({ label, id, className, ...props }: FilterInputProps) {
  const inputId = id ?? controlId(label);

  return (
    <label htmlFor={inputId} className="flex min-w-0 flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <input id={inputId} className={cn(controlClasses, className)} {...props} />
    </label>
  );
}

type FilterSelectOption = { value: string; label: string };

type FilterSelectProps = Omit<React.ComponentProps<"select">, "children"> & {
  label: string;
  options: FilterSelectOption[];
  /** Label of the empty "not filtered" option; false when a value is always required. */
  placeholder?: string | false;
};

export function FilterSelect({
  label,
  options,
  placeholder = "All",
  id,
  className,
  ...props
}: FilterSelectProps) {
  const selectId = id ?? controlId(label);

  return (
    <label htmlFor={selectId} className="flex min-w-0 flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <span className="relative">
        <select
          id={selectId}
          className={cn(controlClasses, "appearance-none pr-8", className)}
          {...props}
        >
          {placeholder !== false && <option value="">{placeholder}</option>}
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
