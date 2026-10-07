import { LoaderCircle, Plus, Undo2 } from "lucide-react";
import type { Ref } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { Supervisor } from "./api";
import type { TallyTile } from "./contact-data";

type SupervisorTileProps = {
  tile: TallyTile;
  /** Contacts in the counted month; undefined while loading. */
  count: number | undefined;
  countLabel: string;
  canEdit: boolean;
  /** A +1 for this supervisor is being saved. */
  pending?: boolean;
  /** +1 is blocked for every tile, e.g. the contact date is invalid. */
  blocked?: boolean;
  onAdd?: (supervisor: Supervisor) => void;
};

export function SupervisorTile({
  tile,
  count,
  countLabel,
  canEdit,
  pending = false,
  blocked = false,
  onAdd,
}: SupervisorTileProps) {
  const { supervisor, unavailable } = tile;
  return (
    <article
      aria-label={supervisor.displayName}
      className="flex h-full min-w-0 flex-col justify-between gap-3 rounded-lg border bg-card p-3 sm:p-4"
    >
      <div className="min-w-0 space-y-1">
        <h3 className="text-base leading-snug font-semibold break-words">{supervisor.displayName}</h3>
        <p className="text-sm text-muted-foreground">
          {countLabel}:{" "}
          {count === undefined ? (
            <span className="inline-block h-4 w-6 animate-pulse rounded bg-muted align-middle" />
          ) : (
            <span className="font-semibold text-foreground tabular-nums">{count}</span>
          )}
        </p>
        {unavailable && <p className="text-xs text-muted-foreground">{unavailable}</p>}
      </div>
      {canEdit && (
        <Button
          className="h-12 w-full text-base"
          aria-label={`+1 Contact for ${supervisor.displayName}`}
          aria-busy={pending || undefined}
          disabled={pending || blocked || unavailable !== null}
          onClick={() => onAdd?.(supervisor)}
        >
          {pending ? <LoaderCircle className="animate-spin" aria-hidden /> : <Plus aria-hidden />}
          +1 Contact
        </Button>
      )}
    </article>
  );
}

type TallyBoardProps = {
  tiles: TallyTile[];
  counts: ReadonlyMap<number, number> | undefined;
  countLabel: string;
  canEdit: boolean;
  pendingIds: ReadonlySet<number>;
  blocked: boolean;
  onAdd: (supervisor: Supervisor) => void;
};

/** Active supervisors in alphabetical order; each tile records exactly one contact per tap. */
export function TallyBoard({
  tiles,
  counts,
  countLabel,
  canEdit,
  pendingIds,
  blocked,
  onAdd,
}: TallyBoardProps) {
  return (
    <ul
      aria-label="Active supervisors"
      className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4 min-[1600px]:grid-cols-5"
    >
      {tiles.map((tile) => (
        <li key={tile.supervisor.id} className="min-w-0">
          <SupervisorTile
            tile={tile}
            count={counts === undefined ? undefined : (counts.get(tile.supervisor.id) ?? 0)}
            countLabel={countLabel}
            canEdit={canEdit}
            pending={pendingIds.has(tile.supervisor.id)}
            blocked={blocked}
            onAdd={onAdd}
          />
        </li>
      ))}
    </ul>
  );
}

type AddedFeedbackProps = {
  message: string | null;
  tone?: "success" | "error";
  /** Shown only for the contact just added. */
  onUndo?: () => void;
  undoing?: boolean;
  /** Focus target once the Undo button disappears. */
  messageRef?: Ref<HTMLParagraphElement>;
};

/** Announces each save; the Undo deletes the contact just added (an audited delete). */
export function AddedFeedback({
  message,
  tone = "success",
  onUndo,
  undoing = false,
  messageRef,
}: AddedFeedbackProps) {
  return (
    <div
      className={cn(
        "flex min-h-14 flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-lg border px-4 py-2",
        !message && "border-dashed",
        message && tone === "success" && "border-primary/40 bg-primary/5",
        message && tone === "error" && "border-destructive/40 bg-destructive/5",
      )}
    >
      <p
        ref={messageRef}
        role="status"
        aria-live="polite"
        tabIndex={-1}
        className={cn(
          "min-w-0 text-sm font-medium outline-none",
          tone === "error" ? "text-destructive" : "text-primary",
          !message && "font-normal text-muted-foreground",
        )}
      >
        {message ?? "Tap +1 Contact to record a contact for the date above."}
      </p>
      {message && onUndo && (
        <Button variant="outline" className="h-11 min-w-24 px-4" onClick={onUndo} disabled={undoing}>
          {undoing ? <LoaderCircle className="animate-spin" aria-hidden /> : <Undo2 aria-hidden />}
          Undo
        </Button>
      )}
    </div>
  );
}
