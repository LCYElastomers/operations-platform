"use client";

import { AlertTriangle, ShieldOff } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { Button, buttonVariants } from "@/components/ui/button";
import { accountNavigation, navigation } from "@/config/navigation";
import { errorMessage } from "@/features/auth/api";
import { useSession } from "@/features/auth/use-session";
import { isPublicPath } from "@/lib/api-client";
import { canOpen } from "@/lib/navigation";

import { AppHeader } from "./app-header";
import { AppSidebar } from "./app-sidebar";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (isPublicPath(pathname)) {
    return (
      <main className="grid min-h-screen place-items-center bg-muted/40 px-4 py-10">
        <div className="w-full max-w-md">{children}</div>
      </main>
    );
  }
  return <SignedInShell pathname={pathname}>{children}</SignedInShell>;
}

function SignedInShell({ pathname, children }: { pathname: string; children: React.ReactNode }) {
  // Only meaningful below the lg breakpoint; on desktop the sidebar is always visible.
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const session = useSession();

  useEffect(() => {
    if (!sidebarOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSidebarOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [sidebarOpen]);

  let content: React.ReactNode;
  if (session.isPending) {
    content = <p className="py-10 text-sm text-muted-foreground">Loading…</p>;
  } else if (session.isError) {
    content = (
      <EmptyState
        icon={AlertTriangle}
        title="Your session could not be loaded"
        description={errorMessage(session.error, "Sign in again to continue.")}
        action={
          <Button variant="outline" onClick={() => void session.refetch()}>
            Try again
          </Button>
        }
      />
    );
  } else if (!canOpen([...navigation, ...accountNavigation], pathname, session.data.permissions)) {
    content = <AccessDenied />;
  } else {
    content = children;
  }

  return (
    <div className="min-h-full">
      <AppSidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      {sidebarOpen && (
        <div
          aria-hidden
          onClick={() => setSidebarOpen(false)}
          className="fixed inset-0 z-30 bg-slate-950/50 backdrop-blur-[1px] lg:hidden"
        />
      )}

      <div className="flex min-h-screen flex-col lg:pl-64">
        <AppHeader sidebarOpen={sidebarOpen} onOpenSidebar={() => setSidebarOpen(true)} />
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto w-full max-w-7xl">{content}</div>
        </main>
      </div>
    </div>
  );
}

/** Shown in place of a page the user's roles do not cover. Names no one who could open it. */
export function AccessDenied() {
  return (
    <EmptyState
      icon={ShieldOff}
      title="You do not have access to this page"
      description="Your roles do not include the permissions this page needs. If you need access, ask a platform administrator."
      action={
        <Link href="/" className={buttonVariants({ variant: "outline" })}>
          Go to Overview
        </Link>
      }
    />
  );
}
