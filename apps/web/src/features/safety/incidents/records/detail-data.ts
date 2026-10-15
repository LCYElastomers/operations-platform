import type {
  DamageDetails,
  DetailCode,
  DetailFields,
  DetailKind,
  IncidentRecord,
  LopcDetails,
  PitDetails,
  RecordOption,
  SeriousRiskDetails,
} from "./api";
import type { HistoryChange } from "./record-data";

/** "" is Unknown (not recorded): never No and never Not Applicable. */
export type Tri = "" | "yes" | "no";

export type LopcDraft = Record<Exclude<keyof LopcDetails, "isLopc" | "processSafetyIncident">, string> & {
  isLopc: Tri;
  processSafetyIncident: Tri;
};
export type DamageDraft = Record<Exclude<keyof DamageDetails, "outOfService" | "repairRequired">, string> & {
  outOfService: Tri;
  repairRequired: Tri;
};
export type PitDraft = Record<Exclude<keyof PitDetails, "damageOccurred">, string> & { damageOccurred: Tri };
/** isPsif "" is not assessed: no serious-risk detail. */
export type RiskDraft = Record<Exclude<keyof SeriousRiskDetails, "isPsif">, string> & { isPsif: Tri };

export type ConditionalKind = "lopc" | "damage" | "pit";

export type DetailDraft = {
  additional: number[];
  lopc: LopcDraft;
  damage: DamageDraft;
  pit: PitDraft;
  risk: RiskDraft;
  /** The user chose to remove a stored detail its classification no longer allows. */
  remove: Record<ConditionalKind, boolean>;
};

export const SECTIONS: Record<
  ConditionalKind,
  { field: "lopcDetails" | "damageDetails" | "pitDetails"; label: string; requires: string[]; requirement: string }
> = {
  lopc: {
    field: "lopcDetails",
    label: "Spill / Release / LOPC details",
    requires: ["spill_release"],
    requirement: "the Spill / Release classification",
  },
  damage: {
    field: "damageDetails",
    label: "Damage / failure details",
    requires: ["property_damage", "equipment_damage_failure"],
    requirement: "the Property Damage or Equipment Damage / Failure classification",
  },
  pit: {
    field: "pitDetails",
    label: "Powered industrial vehicle details",
    requires: ["pit_accident"],
    requirement: "the PIT Accident classification",
  },
};

export const DETAIL_LABELS: Record<DetailKind, string> = {
  classifications: "Further classifications",
  lopc: "LOPC details",
  damage: "Damage / failure details",
  pit: "PIT details",
  serious_risk: "Serious-risk details",
};

/** Damage kind -> the classification it needs. */
export const DAMAGE_KIND_CLASSIFICATION: Record<string, string> = {
  property_damage: "property_damage",
  equipment_damage: "equipment_damage_failure",
  equipment_failure: "equipment_damage_failure",
};

const LOPC_KEYS = [
  "isLopc",
  "materialName",
  "estimatedQuantity",
  "quantityUnitCode",
  "equipmentTag",
  "failureMechanismCode",
  "contributingFactorCode",
  "secondaryContainmentStatusCode",
  "processSafetyIncident",
  "notes",
] as const;
const DAMAGE_KEYS = [
  "damageKindCode",
  "assetOrPropertyName",
  "equipmentTag",
  "assetType",
  "damageDescription",
  "operationalImpact",
  "estimatedCost",
  "currencyCode",
  "workOrderReference",
  "outOfService",
  "repairRequired",
  "notes",
] as const;
const PIT_KEYS = [
  "vehicleIdentifier",
  "vehicleType",
  "ownershipTypeCode",
  "operatingCompany",
  "impactedAssetOrProperty",
  "damageOccurred",
  "notes",
] as const;
const TRI_KEYS = new Set(["isLopc", "processSafetyIncident", "outOfService", "repairRequired", "damageOccurred"]);

function triOf(value: boolean | null | undefined): Tri {
  return value === true ? "yes" : value === false ? "no" : "";
}

function triValue(value: Tri): boolean | null {
  return value === "yes" ? true : value === "no" ? false : null;
}

function draftFrom<K extends string>(keys: readonly K[], stored: Partial<Record<K, unknown>> | null | undefined) {
  return Object.fromEntries(
    keys.map((key) => {
      const value = stored?.[key];
      if (TRI_KEYS.has(key)) return [key, triOf(value as boolean | null | undefined)];
      return [key, value === null || value === undefined ? "" : String(value)];
    }),
  );
}

export function detailDraftOf(record: IncidentRecord | null): DetailDraft {
  const risk = record?.seriousRiskDetails;
  return {
    additional: (record?.additionalClassifications ?? []).map((c) => c.id),
    lopc: draftFrom(LOPC_KEYS, record?.lopcDetails) as LopcDraft,
    damage: draftFrom(DAMAGE_KEYS, record?.damageDetails) as DamageDraft,
    pit: draftFrom(PIT_KEYS, record?.pitDetails) as PitDraft,
    risk: {
      isPsif: triOf(risk?.isPsif),
      potentialSeverityCode: risk?.potentialSeverityCode ?? "",
      seriousRiskCategoryCode: risk?.seriousRiskCategoryCode ?? "",
      rationale: risk?.rationale ?? "",
    },
    remove: { lopc: false, damage: false, pit: false },
  };
}

/** The codes of the chosen primary and additional classifications. */
export function classificationCodes(
  primaryId: number | null,
  additional: number[],
  options: RecordOption[] | undefined,
): Set<string> {
  const byId = new Map((options ?? []).map((option) => [option.id, option.code]));
  const ids = primaryId === null ? additional : [primaryId, ...additional];
  return new Set(ids.map((id) => byId.get(id)).filter((code): code is string => code !== undefined));
}

export function visibleSections(codes: Set<string>): Record<ConditionalKind, boolean> {
  const has = (kind: ConditionalKind) => SECTIONS[kind].requires.some((code) => codes.has(code));
  return { lopc: has("lopc"), damage: has("damage"), pit: has("pit") };
}

/** Damage kinds the chosen classifications allow. */
export function allowedDamageKinds(codes: Set<string>): string[] {
  return Object.entries(DAMAGE_KIND_CLASSIFICATION)
    .filter(([, classification]) => codes.has(classification))
    .map(([kind]) => kind);
}

function values<K extends string>(keys: readonly K[], draft: Record<K, string>) {
  return Object.fromEntries(
    keys.map((key) => {
      const value = draft[key];
      if (TRI_KEYS.has(key)) return [key, triValue(value as Tri)];
      const text = value.trim();
      return [key, text === "" ? null : text];
    }),
  );
}

function blank(object: Record<string, unknown>): boolean {
  return Object.values(object).every((value) => value === null);
}

const QUANTITY = /^\d{1,11}(\.\d{1,3})?$/;
const COST = /^\d{1,12}(\.\d{1,2})?$/;

/** Code -> name across every detail taxonomy. */
export function codeNames(detailCodes: Record<string, DetailCode[]> | undefined): Map<string, string> {
  return new Map(Object.values(detailCodes ?? {}).flatMap((codes) => codes.map((c) => [c.code, c.name] as const)));
}

/** "Yes", "No", or "Unknown" for a not-recorded answer. */
export function yesNo(value: boolean | null | undefined): string {
  return value === true ? "Yes" : value === false ? "No" : "Unknown";
}

function humanize(key: string): string {
  const words = key.replace(/_ids?$/, "").replace(/_code$/, "").split("_");
  const text = words.join(" ").replace(/\blopc\b/, "LOPC").replace(/\bpsif\b/, "PSIF");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Field-by-field differences of a detail audit event; a missing value is "Unknown", never 0 or No. */
export function detailHistoryChanges(
  oldValue: Record<string, unknown> | null,
  newValue: Record<string, unknown> | null,
  names: { classifications: Map<number, string>; codes: Map<string, string> },
): HistoryChange[] {
  const label = (key: string, value: unknown): string => {
    if (value === null || value === undefined) return "Unknown";
    if (typeof value === "boolean") return yesNo(value);
    if (Array.isArray(value))
      return value.length === 0
        ? "None"
        : value.map((id) => names.classifications.get(Number(id)) ?? `#${id}`).join(", ");
    if (key.endsWith("_code")) return names.codes.get(String(value)) ?? String(value);
    return String(value);
  };
  const keys = [...new Set([...Object.keys(oldValue ?? {}), ...Object.keys(newValue ?? {})])];
  return keys.flatMap((key) => {
    const before = oldValue?.[key];
    const after = newValue?.[key];
    if (oldValue && newValue && JSON.stringify(before ?? null) === JSON.stringify(after ?? null)) return [];
    if (!oldValue && (after === null || after === undefined)) return [];
    return [
      {
        label: humanize(key),
        from: oldValue ? label(key, before) : "",
        to: newValue ? label(key, after) : "Removed",
      },
    ];
  });
}

/** Problems the browser can see, keyed by the API's field names; only for shown sections. */
export function detailProblems(draft: DetailDraft, codes: Set<string>): Record<string, string> {
  const shown = visibleSections(codes);
  const problems: Record<string, string> = {};
  if (shown.lopc) {
    const { estimatedQuantity: quantity, quantityUnitCode: unit } = draft.lopc;
    if (quantity.trim() && !QUANTITY.test(quantity.trim()))
      problems["lopcDetails.estimatedQuantity"] = "Enter a number of 0 or more, with up to 3 decimal places.";
    else if (quantity.trim() && !unit) problems["lopcDetails.quantityUnitCode"] = "Choose the unit of the quantity.";
    else if (!quantity.trim() && unit) problems["lopcDetails.estimatedQuantity"] = "Enter the quantity for this unit.";
  }
  if (shown.damage) {
    const { estimatedCost: cost, currencyCode: currency, damageKindCode: kind } = draft.damage;
    if (cost.trim() && !COST.test(cost.trim()))
      problems["damageDetails.estimatedCost"] = "Enter an amount of 0 or more, with up to 2 decimal places.";
    else if (cost.trim() && !currency) problems["damageDetails.currencyCode"] = "Choose the currency of the cost.";
    else if (!cost.trim() && currency) problems["damageDetails.estimatedCost"] = "Enter the cost for this currency.";
    if (kind && !allowedDamageKinds(codes).includes(kind))
      problems["damageDetails.damageKindCode"] = "This damage kind does not match the chosen classifications.";
  }
  return problems;
}

/**
 * What to send with the record. A shown section is sent when it has a value (or
 * null when its stored values were all cleared); a hidden section is sent only
 * as null when the user chose to remove its stored detail. Draft values of a
 * hidden section are kept, not sent, so re-selecting the classification restores them.
 */
export function detailFieldsOf(draft: DetailDraft, codes: Set<string>, record: IncidentRecord | null): DetailFields {
  const shown = visibleSections(codes);
  const out: DetailFields = {};
  const before = (record?.additionalClassifications ?? []).map((c) => c.id).sort();
  const after = [...draft.additional].sort();
  if (JSON.stringify(before) !== JSON.stringify(after)) out.additionalClassificationIds = draft.additional;

  const conditional = (kind: ConditionalKind, keys: readonly string[], section: Record<string, string>) => {
    const field = SECTIONS[kind].field;
    const stored = record?.[field] ?? null;
    if (!shown[kind]) {
      if (stored && draft.remove[kind]) out[field] = null;
      return;
    }
    const value = values(keys, section);
    if (!blank(value)) out[field] = value as never;
    else if (stored) out[field] = null;
  };
  conditional("lopc", LOPC_KEYS, draft.lopc);
  conditional("damage", DAMAGE_KEYS, draft.damage);
  conditional("pit", PIT_KEYS, draft.pit);

  const risk = draft.risk;
  if (risk.isPsif === "") {
    if (record?.seriousRiskDetails) out.seriousRiskDetails = null;
  } else {
    const psif = risk.isPsif === "yes";
    out.seriousRiskDetails = {
      isPsif: psif,
      // Given only for a PSIF; kept in the draft (not sent) while No is chosen.
      potentialSeverityCode: (psif && risk.potentialSeverityCode) || null,
      seriousRiskCategoryCode: (psif && risk.seriousRiskCategoryCode) || null,
      rationale: risk.rationale.trim() || null,
    };
  }
  return out;
}
