"use client";

import { CircleAlert, CircleCheck, Info, X } from "lucide-react";
import { useEffect, useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";

type Tone = "success" | "error" | "info";

export type Toast = { id: number; tone: Tone; title: string; description?: string };

let toasts: Toast[] = [];
let nextId = 1;
const listeners = new Set<() => void>();
const EMPTY: Toast[] = [];

function emit() {
  for (const listener of listeners) listener();
}

/** Shows a short notification at the corner of the screen. */
export function toast(tone: Tone, title: string, description?: string): number {
  const id = nextId++;
  toasts = [...toasts, { id, tone, title, description }].slice(-4);
  emit();
  return id;
}

export function dismissToast(id: number) {
  toasts = toasts.filter((item) => item.id !== id);
  emit();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const ICONS = { success: CircleCheck, error: CircleAlert, info: Info } as const;
const TONE_LABEL = { success: "Success", error: "Error", info: "Notice" } as const;

/** Mounted once by the app shell. Errors stay until dismissed or replaced. */
export function Toaster() {
  const items = useSyncExternalStore(subscribe, () => toasts, () => EMPTY);
  return (
    <div
      role="region"
      aria-label="Notifications"
      className="pointer-events-none fixed inset-x-3 bottom-3 z-50 flex flex-col items-end gap-2 sm:inset-x-auto sm:right-4 sm:bottom-4 sm:w-96"
    >
      {items.map((item) => (
        <ToastItem key={item.id} item={item} />
      ))}
    </div>
  );
}

function ToastItem({ item }: { item: Toast }) {
  const Icon = ICONS[item.tone];
  useEffect(() => {
    if (item.tone === "error") return;
    const timer = window.setTimeout(() => dismissToast(item.id), 6000);
    return () => window.clearTimeout(timer);
  }, [item]);
  return (
    <div
      role={item.tone === "error" ? "alert" : "status"}
      className={cn(
        "pointer-events-auto flex w-full items-start gap-3 rounded-lg border bg-card p-3 text-sm shadow-lg",
        item.tone === "error" && "border-destructive/40",
      )}
    >
      <Icon
        aria-hidden
        className={cn(
          "mt-0.5 size-4 shrink-0",
          item.tone === "success" && "text-emerald-600",
          item.tone === "error" && "text-destructive",
          item.tone === "info" && "text-primary",
        )}
      />
      <div className="min-w-0 flex-1">
        <p className="font-medium">
          <span className="sr-only">{TONE_LABEL[item.tone]}: </span>
          {item.title}
        </p>
        {item.description && <p className="mt-0.5 break-words text-muted-foreground">{item.description}</p>}
      </div>
      <button
        type="button"
        aria-label="Dismiss notification"
        onClick={() => dismissToast(item.id)}
        className="-m-1 grid size-7 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-muted"
      >
        <X className="size-3.5" />
      </button>
    </div>
  );
}
