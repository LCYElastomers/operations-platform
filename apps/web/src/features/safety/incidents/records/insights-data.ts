import type { DrillFilter, EventType } from "./api";
import type { CompletenessStatus, ExperienceCategory } from "./insights-api";

/** Event Experience category names by stable code (the API sends them too). */
export const CATEGORY_NAMES: Record<string, string> = {
  recordable_injury: "Recordable Injury",
  first_aid: "First Aid",
  lost_time_injury: "Lost Time Injury",
  spill_release_lopc: "Spill / Release / LOPC",
  equipment_damage: "Equipment Damage",
  equipment_failure: "Equipment Failure",
  property_damage: "Property Damage",
  pit: "Powered Industrial Vehicle Accident",
  fire: "Fire",
  hazardous_condition: "Hazardous Condition",
  psif: "PSIF",
};

export const STATUS_TEXT: Record<CompletenessStatus, { label: string; tone: "success" | "neutral" | "warning" | "danger" }> = {
  complete: { label: "Complete", tone: "success" },
  no_event_in_scope: { label: "No event this year", tone: "neutral" },
  insufficient_classification_data: { label: "Incomplete classification", tone: "warning" },
  source_unavailable: { label: "No records on file", tone: "neutral" },
};

const DRILL_LABELS: Record<keyof DrillFilter, string> = {
  category: "Category",
  failureMechanism: "Failure mechanism",
  containment: "Secondary containment",
  contributingFactor: "Contributing factor",
  quantityUnit: "Quantity unit",
  processSafety: "Process safety",
  material: "Material",
  equipmentTag: "Equipment tag",
};

export const UNKNOWN_LABEL = "Unknown / not recorded";

/** e.g. "Failure mechanism: Corrosion" or "Category: PSIF". */
export function drillLabel(key: keyof DrillFilter, value: string, codes: Map<string, string>): string {
  const shown =
    value === "unknown"
      ? UNKNOWN_LABEL
      : key === "category"
        ? (CATEGORY_NAMES[value] ?? value)
        : key === "processSafety"
          ? value === "yes"
            ? "Yes"
            : "No"
          : key === "material" || key === "equipmentTag"
            ? value
            : (codes.get(value) ?? value);
  return `${DRILL_LABELS[key]}: ${shown}`;
}

const CODE = /^[A-Za-z0-9_]{1,60}$/;

/** Drill-through filters from `?category=` etc.; anything malformed is dropped. */
export function parseDrill(params: Record<string, string | string[] | undefined>): DrillFilter {
  const one = (key: string) => {
    const value = params[key];
    const text = (Array.isArray(value) ? value[0] : value)?.trim();
    return text ? text : undefined;
  };
  const code = (key: string) => {
    const text = one(key);
    return text && CODE.test(text) ? text : undefined;
  };
  const category = one("category");
  const processSafety = one("processSafety");
  const material = one("material");
  const equipmentTag = one("equipmentTag");
  const drill: DrillFilter = {
    category: category && category in CATEGORY_NAMES ? category : undefined,
    failureMechanism: code("failureMechanism"),
    containment: code("containment"),
    contributingFactor: code("contributingFactor"),
    quantityUnit: code("quantityUnit"),
    processSafety:
      processSafety === "yes" || processSafety === "no" || processSafety === "unknown" ? processSafety : undefined,
    material: material && material.length <= 200 ? material : undefined,
    equipmentTag: equipmentTag && equipmentTag.length <= 100 ? equipmentTag : undefined,
  };
  return Object.fromEntries(Object.entries(drill).filter(([, value]) => value !== undefined)) as DrillFilter;
}

/** Days since, with "today" for 0; null when no event is known (never 0). */
export function daysSinceText(days: number | null): string | null {
  if (days === null) return null;
  if (days === 0) return "Today";
  return `${days.toLocaleString()} ${days === 1 ? "day" : "days"}`;
}

/** The register event types a category covers. */
export function categoryEventTypes(code: string, includesNearMisses: boolean): EventType | undefined {
  return code === "psif" && includesNearMisses ? undefined : "incident";
}

/** YTD events, marked as a minimum when classification is incomplete. */
export function ytdText(category: Pick<ExperienceCategory, "ytdEvents" | "ytdEventsComplete" | "status">): string {
  if (category.status === "source_unavailable") return "Unavailable";
  return category.ytdEventsComplete ? String(category.ytdEvents) : `At least ${category.ytdEvents}`;
}
