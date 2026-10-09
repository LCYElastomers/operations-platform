"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { passwordLinkUrl, type PasswordLink, type PermissionInfo } from "./api";

const DATE_TIME = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" });

export function formatDateTime(value: string | null): string {
  return value === null ? "Never" : DATE_TIME.format(new Date(value));
}

export const inputClass =
  "h-9 w-full rounded-md border bg-background px-3 text-sm shadow-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-60 pointer-coarse:h-11";

export function TextField({
  label,
  hint,
  error,
  ...props
}: React.ComponentProps<"input"> & { label: string; hint?: string; error?: string | null }) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium">{label}</span>
      <input {...props} aria-invalid={error ? true : undefined} className={cn(inputClass, error && "border-destructive")} />
      {error ? (
        <span className="block text-xs text-destructive">{error}</span>
      ) : (
        hint && <span className="block text-xs text-muted-foreground">{hint}</span>
      )}
    </label>
  );
}

export function Notice({ tone, children }: { tone: "success" | "error"; children: React.ReactNode }) {
  return (
    <p
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "rounded-md border px-3 py-2 text-sm",
        tone === "error"
          ? "border-destructive/30 bg-destructive/10 text-destructive"
          : "border-emerald-600/30 bg-emerald-600/10 text-emerald-800 dark:text-emerald-300",
      )}
    >
      {children}
    </p>
  );
}

export function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border p-4">
      <h3 className="text-sm font-semibold">{title}</h3>
      {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

/**
 * A one-time password link, shown once to the administrator who issued it so
 * they can send it to the user. It is not stored anywhere readable.
 */
export function PasswordLinkPanel({ link, name }: { link: PasswordLink; name: string }) {
  const url = passwordLinkUrl(link);
  const [copied, setCopied] = useState(false);
  return (
    <div className="space-y-2 rounded-lg border border-amber-500/40 bg-amber-500/5 p-4">
      <p className="text-sm font-semibold">One-time password link for {name}</p>
      <p className="text-xs text-muted-foreground">
        Send this link to {name} directly. It works once and expires {formatDateTime(link.expiresAt)}. It will not be shown again;
        if it is lost, issue a new one.
      </p>
      <div className="flex gap-2">
        <input readOnly value={url} aria-label="Password link" className={cn(inputClass, "font-mono text-xs")} onFocus={(e) => e.currentTarget.select()} />
        <Button
          variant="outline"
          onClick={() => {
            void navigator.clipboard?.writeText(url).then(() => setCopied(true));
          }}
        >
          {copied ? <Check /> : <Copy />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </div>
  );
}

const MODULE_LABELS: Record<string, string> = {
  app: "Platform",
  users: "Users",
  roles: "Roles",
  audit: "Audit",
  quality: "Quality",
  qualityCost: "Quality Cost",
  car: "Corrective Action Reports",
  qualityDashboard: "Dashboards",
  safety: "Safety",
  safetyRecord: "Safety records",
  incident: "Incidents",
  nearMiss: "Near misses",
  safetyObservation: "Safety observations",
  safetyAction: "Safety actions",
  safetyInvestigation: "Safety investigations",
  safetyDashboard: "Dashboards",
  assignments: "Assignments",
  attachments: "Attachments",
  comments: "Comments",
};

export function permissionGroup(code: string): string {
  const prefix = code.split(".", 1)[0];
  return MODULE_LABELS[prefix] ?? prefix;
}

/** Permissions grouped by area, as plain lists or as checkboxes. */
export function PermissionGroups({
  codes,
  catalog,
  selected,
  onToggle,
  disabled,
}: {
  codes: string[];
  catalog?: PermissionInfo[];
  selected?: ReadonlySet<string>;
  onToggle?: (code: string) => void;
  disabled?: boolean;
}) {
  const descriptions = new Map(catalog?.map((p) => [p.code, p.description]));
  const groups = new Map<string, string[]>();
  for (const code of codes) {
    const group = permissionGroup(code);
    groups.set(group, [...(groups.get(group) ?? []), code]);
  }
  if (codes.length === 0) return <p className="text-sm text-muted-foreground">No permissions.</p>;
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {[...groups].map(([group, items]) => (
        <fieldset key={group} className="min-w-0">
          <legend className="mb-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{group}</legend>
          <ul className="space-y-1">
            {items.map((code) => (
              <li key={code}>
                {onToggle ? (
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="mt-0.5 size-4"
                      checked={selected?.has(code) ?? false}
                      onChange={() => onToggle(code)}
                      disabled={disabled}
                    />
                    <span className="min-w-0">
                      <span className="font-mono text-xs">{code}</span>
                      {descriptions.get(code) && (
                        <span className="block text-xs text-muted-foreground">{descriptions.get(code)}</span>
                      )}
                    </span>
                  </label>
                ) : (
                  <span className="text-sm" title={descriptions.get(code)}>
                    <span className="font-mono text-xs">{code}</span>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </fieldset>
      ))}
    </div>
  );
}
