"use client";

import { ChevronRight, Menu } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { ApiStatusIndicator } from "@/components/system/api-status";
import { navigation } from "@/config/navigation";
import { findNavTrail } from "@/lib/navigation";

type AppHeaderProps = {
  sidebarOpen: boolean;
  onOpenSidebar: () => void;
};

export function AppHeader({ sidebarOpen, onOpenSidebar }: AppHeaderProps) {
  const pathname = usePathname();
  const trail = findNavTrail(navigation, pathname);

  return (
    <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-3 border-b bg-card/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-card/80 sm:px-6">
      <button
        type="button"
        onClick={onOpenSidebar}
        className="-ml-1.5 rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground lg:hidden"
        aria-label="Open navigation"
        aria-controls="app-sidebar"
        aria-expanded={sidebarOpen}
      >
        <Menu className="size-5" />
      </button>

      <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
        <ol className="flex items-center gap-1.5 text-sm">
          {trail.length === 0 ? (
            <li className="font-medium">Operations Platform</li>
          ) : (
            trail.map((item, index) => {
              const last = index === trail.length - 1;
              return (
                <li key={item.id} className="flex min-w-0 items-center gap-1.5">
                  {index > 0 && (
                    <ChevronRight aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
                  )}
                  {last ? (
                    <span aria-current="page" className="truncate font-medium">
                      {item.label}
                    </span>
                  ) : item.href ? (
                    <Link
                      href={item.href}
                      className="truncate text-muted-foreground hover:text-foreground"
                    >
                      {item.label}
                    </Link>
                  ) : (
                    <span className="truncate text-muted-foreground">{item.label}</span>
                  )}
                </li>
              );
            })
          )}
        </ol>
      </nav>

      <ApiStatusIndicator />
    </header>
  );
}
