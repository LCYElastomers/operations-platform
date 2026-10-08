"use client";

import { X } from "lucide-react";
import { useEffect, useId, useRef } from "react";

import { cn } from "@/lib/utils";

type DialogProps = {
  open: boolean;
  /** Called on Escape, the close button, or a click on the backdrop. */
  onClose: () => void;
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  /** Pinned under the scrolling body, e.g. the form buttons. */
  footer?: React.ReactNode;
  className?: string;
};

/**
 * Modal dialog on the native <dialog> element: the browser keeps focus inside,
 * makes the page behind inert and closes it with Escape. Full screen on small
 * screens, a centred panel from `sm` up. Focus returns to the opener on close.
 */
export function Dialog({ open, onClose, title, description, children, footer, className }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement as HTMLElement | null;
      // jsdom has no showModal; the open attribute is enough there.
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    } else if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      opener.current?.focus?.();
    }
  }, [open]);

  useEffect(() => () => opener.current?.focus?.(), []);

  return (
    <dialog
      ref={ref}
      aria-labelledby={`${id}-title`}
      aria-describedby={description ? `${id}-description` : undefined}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      className={cn(
        "m-0 hidden h-dvh max-h-none w-full max-w-none flex-col open:flex bg-background p-0 text-foreground shadow-xl backdrop:bg-slate-950/50",
        "sm:m-auto sm:h-auto sm:max-h-[90dvh] sm:w-[min(48rem,calc(100vw-2rem))] sm:rounded-lg sm:border",
        className,
      )}
    >
      {open && (
        <>
          <header className="flex items-start gap-3 border-b px-4 py-3 sm:px-5">
            <div className="min-w-0 flex-1">
              <h2 id={`${id}-title`} className="text-base font-semibold">
                {title}
              </h2>
              {description && (
                <div id={`${id}-description`} className="mt-0.5 text-sm text-muted-foreground">
                  {description}
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="-mr-1 grid size-9 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none pointer-coarse:size-11"
            >
              <X className="size-4" />
            </button>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-5">{children}</div>
          {footer && <footer className="border-t px-4 py-3 sm:px-5">{footer}</footer>}
        </>
      )}
    </dialog>
  );
}
