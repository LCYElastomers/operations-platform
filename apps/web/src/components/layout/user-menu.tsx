"use client";

import { ChevronDown, Inbox, LogOut, UserRound } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { initials, type SessionUser } from "@/features/auth/api";
import { usePermissions, useSignOut } from "@/features/auth/use-session";
import { cn } from "@/lib/utils";

export function UserAvatar({ user, className }: { user: Pick<SessionUser, "name" | "image">; className?: string }) {
  return user.image ? (
    // eslint-disable-next-line @next/next/no-img-element -- user-supplied image URL, not a bundled asset
    <img src={user.image} alt="" className={cn("size-8 rounded-full object-cover", className)} />
  ) : (
    <span
      aria-hidden
      className={cn(
        "grid size-8 place-items-center rounded-full bg-primary/10 text-xs font-semibold text-primary",
        className,
      )}
    >
      {initials(user.name)}
    </span>
  );
}

/** The signed-in user, their roles, and account links. */
export function UserMenu() {
  const { session, has } = usePermissions();
  const signOut = useSignOut();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!session) return null;
  const { user, roles } = session;
  const itemClass =
    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted focus-visible:bg-muted focus-visible:outline-none";

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account: ${user.name}`}
        className="flex items-center gap-2 rounded-md p-1 hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
      >
        <UserAvatar user={user} />
        <span className="hidden max-w-40 truncate text-sm font-medium md:inline">{user.name}</span>
        <ChevronDown aria-hidden className="hidden size-4 text-muted-foreground md:inline" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-50 mt-2 w-72 rounded-lg border bg-card p-1.5 shadow-lg">
          <div className="border-b px-2 pt-1 pb-2.5">
            <p className="truncate text-sm font-semibold">{user.name}</p>
            <p className="truncate text-xs text-muted-foreground">{user.email}</p>
            <p className="mt-1.5 text-xs text-muted-foreground">
              {roles.length === 0 ? "No roles assigned" : roles.map((role) => role.name).join(", ")}
            </p>
          </div>
          <div className="pt-1.5">
            <Link role="menuitem" href="/profile" className={itemClass} onClick={() => setOpen(false)}>
              <UserRound className="size-4 text-muted-foreground" />
              Profile
            </Link>
            {has("assignments.viewOwn") && (
              <Link role="menuitem" href="/my-assignments" className={itemClass} onClick={() => setOpen(false)}>
                <Inbox className="size-4 text-muted-foreground" />
                My Assignments
              </Link>
            )}
            <button
              type="button"
              role="menuitem"
              className={itemClass}
              disabled={signOut.isPending}
              onClick={() => signOut.mutate()}
            >
              <LogOut className="size-4 text-muted-foreground" />
              {signOut.isPending ? "Signing out…" : "Sign out"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
