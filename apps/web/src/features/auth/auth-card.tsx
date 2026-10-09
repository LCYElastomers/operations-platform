import { cn } from "@/lib/utils";

/** The centered card used by the sign-in and password setup pages. */
export function AuthCard({ title, description, children }: { title: string; description?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border bg-card p-6 shadow-sm sm:p-8">
      <div className="mb-6 flex items-center gap-3">
        <div aria-hidden className="grid size-9 place-items-center rounded-md bg-brand text-sm font-bold text-brand-foreground">
          OP
        </div>
        <div className="leading-tight">
          <p className="text-sm font-semibold">Operations Platform</p>
          <p className="text-[11px] tracking-wide text-muted-foreground uppercase">LCY</p>
        </div>
      </div>
      <h1 className="text-lg font-semibold">{title}</h1>
      {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      <div className="mt-5">{children}</div>
    </div>
  );
}

export function Field({
  label,
  hint,
  className,
  ...props
}: React.ComponentProps<"input"> & { label: string; hint?: string }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium">{label}</span>
      <input
        {...props}
        className={cn(
          "h-10 w-full rounded-md border bg-background px-3 text-sm shadow-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-60",
          className,
        )}
      />
      {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}

export function FormError({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
      {children}
    </p>
  );
}
