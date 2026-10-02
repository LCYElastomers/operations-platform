"use client";

import { ChevronRight, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { navigation } from "@/config/navigation";
import { containsActive, isNavItemActive, type NavItem } from "@/lib/navigation";
import { cn } from "@/lib/utils";

type AppSidebarProps = {
  open: boolean;
  onClose: () => void;
};

export function AppSidebar({ open, onClose }: AppSidebarProps) {
  const pathname = usePathname();
  // Explicit user toggles. Groups without an entry follow the active route.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const isExpanded = (item: NavItem) => expanded[item.id] ?? containsActive(item, pathname);
  const toggle = (item: NavItem) =>
    setExpanded((current) => ({ ...current, [item.id]: !isExpanded(item) }));

  const renderItems = (items: NavItem[], depth: number) => (
    <ul className={cn("space-y-0.5", depth > 0 && "mt-0.5")}>
      {items.map((item) => (
        <li key={item.id}>
          {item.children ? (
            <NavGroup
              item={item}
              depth={depth}
              open={isExpanded(item)}
              activeWithin={containsActive(item, pathname)}
              onToggle={() => toggle(item)}
            >
              {renderItems(item.children, depth + 1)}
            </NavGroup>
          ) : (
            <NavLink
              item={item}
              depth={depth}
              active={isNavItemActive(item, pathname)}
              onNavigate={onClose}
            />
          )}
        </li>
      ))}
    </ul>
  );

  return (
    <aside
      id="app-sidebar"
      aria-label="Primary"
      className={cn(
        "fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground",
        "transition-transform duration-200 ease-out lg:translate-x-0",
        open ? "translate-x-0 shadow-2xl" : "-translate-x-full",
      )}
    >
      <div className="flex h-14 shrink-0 items-center gap-3 border-b border-sidebar-border px-4">
        <div
          aria-hidden
          className="grid size-8 place-items-center rounded-md bg-brand text-sm font-bold text-brand-foreground"
        >
          OP
        </div>
        <div className="min-w-0 flex-1 leading-tight">
          <p className="truncate text-sm font-semibold text-sidebar-accent-foreground">
            Operations Platform
          </p>
          <p className="truncate text-[11px] tracking-wide text-sidebar-muted uppercase">LCY</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1.5 text-sidebar-muted hover:bg-sidebar-accent hover:text-sidebar-accent-foreground lg:hidden"
          aria-label="Close navigation"
        >
          <X className="size-4" />
        </button>
      </div>

      <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
        {navigation.map((section) => (
          <div key={section.id}>
            {section.label && (
              <p className="mb-2 px-3 text-[11px] font-semibold tracking-wider text-sidebar-muted uppercase">
                {section.label}
              </p>
            )}
            {renderItems(section.items, 0)}
          </div>
        ))}
      </nav>

      <div className="shrink-0 border-t border-sidebar-border px-4 py-3 text-[11px] text-sidebar-muted">
        Version 0.1.0
      </div>
    </aside>
  );
}

const itemBase =
  "group relative flex w-full items-center gap-3 rounded-md py-2 pr-2 text-sm transition-colors outline-none focus-visible:ring-2 focus-visible:ring-brand/60";

const depthPadding = ["pl-3", "pl-9", "pl-12"];

function NavLink({
  item,
  depth,
  active,
  onNavigate,
}: {
  item: NavItem;
  depth: number;
  active: boolean;
  onNavigate: () => void;
}) {
  const Icon = depth === 0 ? item.icon : undefined;

  return (
    <Link
      href={item.href!}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        itemBase,
        depthPadding[depth] ?? depthPadding.at(-1),
        active
          ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-brand"
          : "hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
      )}
    >
      {Icon && (
        <Icon
          className={cn(
            "size-4 shrink-0",
            active ? "text-brand" : "text-sidebar-muted group-hover:text-sidebar-foreground",
          )}
        />
      )}
      <span className="truncate">{item.label}</span>
      {item.status === "not-configured" && (
        <span
          aria-hidden
          title="Not configured"
          className="ml-auto size-1.5 shrink-0 rounded-full bg-sidebar-muted/50"
        />
      )}
    </Link>
  );
}

function NavGroup({
  item,
  depth,
  open,
  activeWithin,
  onToggle,
  children,
}: {
  item: NavItem;
  depth: number;
  open: boolean;
  activeWithin: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  const Icon = depth === 0 ? item.icon : undefined;
  const panelId = `nav-group-${item.id}`;

  return (
    <>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={panelId}
        className={cn(
          itemBase,
          depthPadding[depth] ?? depthPadding.at(-1),
          activeWithin
            ? "text-sidebar-accent-foreground"
            : "hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
        )}
      >
        {Icon && (
          <Icon
            className={cn(
              "size-4 shrink-0",
              activeWithin ? "text-brand" : "text-sidebar-muted group-hover:text-sidebar-foreground",
            )}
          />
        )}
        <span className="truncate">{item.label}</span>
        <ChevronRight
          aria-hidden
          className={cn(
            "ml-auto size-4 shrink-0 text-sidebar-muted transition-transform duration-150",
            open && "rotate-90",
          )}
        />
      </button>
      <div id={panelId} hidden={!open}>
        {children}
      </div>
    </>
  );
}
