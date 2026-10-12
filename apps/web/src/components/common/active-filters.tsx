import { X } from "lucide-react";

import { Button } from "@/components/ui/button";

export type FilterChip = { key: string; label: string; onRemove: () => void };

/** The filters in effect, each removable, with "Clear all". Renders nothing when none apply. */
export function ActiveFilters({ chips, onClearAll }: { chips: FilterChip[]; onClearAll: () => void }) {
  if (chips.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2" aria-label="Active filters" role="group">
      <span className="text-xs font-medium text-muted-foreground">Filtered by</span>
      <ul className="flex flex-wrap gap-2">
        {chips.map((chip) => (
          <li key={chip.key}>
            <button
              type="button"
              onClick={chip.onRemove}
              aria-label={`Remove filter ${chip.label}`}
              className="inline-flex items-center gap-1 rounded-full border bg-muted/60 py-1 pr-2 pl-3 text-xs font-medium hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none pointer-coarse:py-2"
            >
              {chip.label}
              <X aria-hidden className="size-3.5 text-muted-foreground" />
            </button>
          </li>
        ))}
      </ul>
      <Button variant="ghost" size="sm" onClick={onClearAll}>
        Clear all
      </Button>
    </div>
  );
}
