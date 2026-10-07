import { LoaderCircle, MapPin, Pencil, Trash2 } from "lucide-react";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { Observation } from "./api";
import { formatObservedOn, KIND_LABELS, OUTCOME_LABELS } from "./observation-data";

const actionClasses = "h-11 min-w-24 px-4";

type ObservationCardProps = {
  observation: Observation;
  canEdit: boolean;
  /** Just saved on this device; marked so it is easy to find. */
  highlighted?: boolean;
  confirmingDelete?: boolean;
  deleting?: boolean;
  onEdit?: () => void;
  onRequestDelete?: () => void;
  onConfirmDelete?: () => void;
  onCancelDelete?: () => void;
};

export function ObservationCard({
  observation,
  canEdit,
  highlighted = false,
  confirmingDelete = false,
  deleting = false,
  onEdit,
  onRequestDelete,
  onConfirmDelete,
  onCancelDelete,
}: ObservationCardProps) {
  const label = `${OUTCOME_LABELS[observation.outcome]} ${KIND_LABELS[observation.kind]}`;
  const deleteRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const wasConfirming = useRef(confirmingDelete);

  useEffect(() => {
    if (confirmingDelete && !wasConfirming.current) cancelRef.current?.focus();
    if (!confirmingDelete && wasConfirming.current) deleteRef.current?.focus();
    wasConfirming.current = confirmingDelete;
  }, [confirmingDelete]);

  return (
    <article
      aria-label={`${label}, ${observation.categoryName}, ${formatObservedOn(observation.observedOn)}`}
      className={cn(
        "rounded-lg border bg-card p-4",
        highlighted && "border-primary/50 ring-2 ring-primary/20",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "rounded-md border px-2 py-0.5 text-xs font-semibold",
                observation.outcome === "safe"
                  ? "border-chart-1/30 bg-chart-1/10 text-chart-1"
                  : "border-chart-2/40 bg-chart-2/15 text-amber-800 dark:text-chart-2",
              )}
            >
              {label}
            </span>
            <span className="text-sm font-semibold">{observation.categoryName}</span>
            {highlighted && (
              <span className="text-xs font-medium text-primary">Just added</span>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            <time dateTime={observation.observedOn}>{formatObservedOn(observation.observedOn)}</time>
            {observation.areaLocation && (
              <>
                <span aria-hidden> · </span>
                <MapPin aria-hidden className="inline size-3 align-[-1px]" />{" "}
                {observation.areaLocation}
              </>
            )}
          </p>
        </div>
        {canEdit && !confirmingDelete && (
          <div className="flex gap-2">
            <Button variant="outline" className={actionClasses} onClick={onEdit}>
              <Pencil aria-hidden />
              Edit
            </Button>
            <Button
              ref={deleteRef}
              variant="outline"
              className={actionClasses}
              onClick={onRequestDelete}
            >
              <Trash2 aria-hidden />
              Delete
            </Button>
          </div>
        )}
      </div>

      {(observation.description || observation.correctiveAction) && (
        <dl className="mt-3 space-y-2 text-sm">
          {observation.description && (
            <div>
              <dt className="sr-only">Description</dt>
              <dd className="break-words whitespace-pre-line">{observation.description}</dd>
            </div>
          )}
          {observation.correctiveAction && (
            <div className="rounded-md bg-muted/60 px-3 py-2">
              <dt className="text-xs font-medium text-muted-foreground">Corrective action</dt>
              <dd className="break-words whitespace-pre-line">{observation.correctiveAction}</dd>
            </div>
          )}
        </dl>
      )}

      {canEdit && confirmingDelete && (
        <div
          role="alertdialog"
          aria-label="Confirm delete"
          className="mt-3 flex flex-col gap-3 rounded-md border border-destructive/30 bg-destructive/5 p-3 sm:flex-row sm:items-center sm:justify-between"
        >
          <p className="text-sm">Delete this observation? This cannot be undone.</p>
          <div className="flex gap-2">
            <Button
              ref={cancelRef}
              variant="outline"
              className={actionClasses}
              onClick={onCancelDelete}
              disabled={deleting}
            >
              Cancel
            </Button>
            <Button
              className={cn(actionClasses, "bg-destructive text-white hover:bg-destructive/90")}
              onClick={onConfirmDelete}
              disabled={deleting}
            >
              {deleting && <LoaderCircle className="animate-spin" aria-hidden />}
              Delete
            </Button>
          </div>
        </div>
      )}
    </article>
  );
}
