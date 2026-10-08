"use client";

import { useId, useRef } from "react";

import { cn } from "@/lib/utils";

export type TabItem<T extends string> = { value: T; label: string };

type TabsProps<T extends string> = {
  /** Names the tab list for assistive technology. */
  label: string;
  items: TabItem<T>[];
  value: T;
  onValueChange: (value: T) => void;
  /** The panel of the selected tab. */
  children: React.ReactNode;
  className?: string;
};

/**
 * WAI-ARIA tabs with automatic activation: arrow keys, Home and End move
 * between tabs and select them. Only the selected panel is rendered.
 */
export function Tabs<T extends string>({
  label,
  items,
  value,
  onValueChange,
  children,
  className,
}: TabsProps<T>) {
  const id = useId();
  const listRef = useRef<HTMLDivElement>(null);
  const tabId = (item: T) => `${id}-tab-${item}`;
  const panelId = `${id}-panel`;

  const select = (index: number) => {
    const item = items[(index + items.length) % items.length];
    onValueChange(item.value);
    listRef.current?.querySelector<HTMLButtonElement>(`#${CSS.escape(tabId(item.value))}`)?.focus();
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    const moves: Record<string, number> = {
      ArrowRight: index + 1,
      ArrowLeft: index - 1,
      Home: 0,
      End: items.length - 1,
    };
    if (!(event.key in moves)) return;
    event.preventDefault();
    select(moves[event.key]);
  };

  return (
    <div className={className}>
      <div
        ref={listRef}
        role="tablist"
        aria-label={label}
        className="flex max-w-full gap-1 overflow-x-auto shadow-[inset_0_-1px_0_var(--color-border)]"
      >
        {items.map((item, index) => {
          const selected = item.value === value;
          return (
            <button
              key={item.value}
              id={tabId(item.value)}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={panelId}
              tabIndex={selected ? 0 : -1}
              onClick={() => onValueChange(item.value)}
              onKeyDown={(event) => handleKeyDown(event, index)}
              className={cn(
                "shrink-0 border-b-2 px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors pointer-coarse:min-h-11",
                "focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none focus-visible:ring-inset",
                selected
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:border-border hover:text-foreground",
              )}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      <div id={panelId} role="tabpanel" aria-labelledby={tabId(value)} className="pt-5">
        {children}
      </div>
    </div>
  );
}
