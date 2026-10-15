import { describe, expect, it } from "vitest";

import type { IncidentRecord, RecordOption } from "./api";
import {
  allowedDamageKinds,
  classificationCodes,
  detailDraftOf,
  detailFieldsOf,
  detailHistoryChanges,
  detailProblems,
  visibleSections,
} from "./detail-data";
import { daysSinceText, drillLabel, parseDrill, ytdText } from "./insights-data";

/** Test fixtures, not production data. */
const OPTIONS: RecordOption[] = [
  { id: 1, code: "spill_release", name: "Spill / Release", active: true },
  { id: 2, code: "pit_accident", name: "PIT Accident", active: true },
  { id: 3, code: "property_damage", name: "Property Damage", active: true },
  { id: 4, code: "equipment_damage_failure", name: "Equipment Damage / Failure", active: true },
];
const STAMP = { updatedAt: "2026-01-01T00:00:00Z", updatedBy: "fixture" };

function stored(extra: Partial<IncidentRecord>): IncidentRecord {
  return { additionalClassifications: [], ...extra } as IncidentRecord;
}

describe("record detail drafts", () => {
  it("shows a section only for a classification that allows it", () => {
    expect(visibleSections(classificationCodes(1, [], OPTIONS))).toEqual({ lopc: true, damage: false, pit: false });
    expect(visibleSections(classificationCodes(2, [3], OPTIONS))).toEqual({ lopc: false, damage: true, pit: true });
    expect(allowedDamageKinds(classificationCodes(4, [], OPTIONS))).toEqual(["equipment_damage", "equipment_failure"]);
  });

  it("keeps Unknown distinct from No and sends blank text as not recorded", () => {
    const draft = detailDraftOf(null);
    draft.lopc.isLopc = "no";
    draft.lopc.materialName = "  ";
    const fields = detailFieldsOf(draft, classificationCodes(1, [], OPTIONS), null);
    expect(fields.lopcDetails).toMatchObject({ isLopc: false, processSafetyIncident: null, materialName: null });
  });

  it("sends nothing for an untouched section and no serious-risk detail when not assessed", () => {
    const fields = detailFieldsOf(detailDraftOf(null), classificationCodes(1, [], OPTIONS), null);
    expect(fields).toEqual({});
  });

  it("keeps a hidden section's values in the draft but does not send them", () => {
    const draft = detailDraftOf(null);
    draft.lopc.materialName = "Fixture solvent";
    expect(detailFieldsOf(draft, classificationCodes(2, [], OPTIONS), null)).toEqual({});
    expect(draft.lopc.materialName).toBe("Fixture solvent");
  });

  it("removes a stored detail only when asked, or when every value was cleared", () => {
    const lopc = {
      isLopc: true,
      materialName: "Fixture",
      estimatedQuantity: null,
      quantityUnitCode: null,
      equipmentTag: null,
      failureMechanismCode: null,
      contributingFactorCode: null,
      secondaryContainmentStatusCode: null,
      processSafetyIncident: null,
      notes: null,
      ...STAMP,
    };
    const record = stored({ lopcDetails: lopc });
    const draft = detailDraftOf(record);
    const pit = classificationCodes(2, [], OPTIONS);
    expect(detailFieldsOf(draft, pit, record)).toEqual({});
    expect(detailFieldsOf({ ...draft, remove: { ...draft.remove, lopc: true } }, pit, record)).toEqual({ lopcDetails: null });

    const cleared = detailDraftOf(record);
    cleared.lopc.isLopc = "";
    cleared.lopc.materialName = "";
    expect(detailFieldsOf(cleared, classificationCodes(1, [], OPTIONS), record)).toEqual({ lopcDetails: null });
  });

  it("sends severity and category only for a PSIF", () => {
    const draft = detailDraftOf(null);
    draft.risk = { isPsif: "no", potentialSeverityCode: "fatality", seriousRiskCategoryCode: "line_of_fire", rationale: "" };
    expect(detailFieldsOf(draft, new Set(), null).seriousRiskDetails).toEqual({
      isPsif: false,
      potentialSeverityCode: null,
      seriousRiskCategoryCode: null,
      rationale: null,
    });
    draft.risk.isPsif = "yes";
    expect(detailFieldsOf(draft, new Set(), null).seriousRiskDetails).toMatchObject({
      potentialSeverityCode: "fatality",
      seriousRiskCategoryCode: "line_of_fire",
    });
  });

  it("sends further classifications only when they changed", () => {
    const record = stored({ additionalClassifications: [{ id: 2, code: "pit_accident", name: "PIT Accident" }] });
    const draft = detailDraftOf(record);
    expect(detailFieldsOf(draft, new Set(), record).additionalClassificationIds).toBeUndefined();
    expect(detailFieldsOf({ ...draft, additional: [] }, new Set(), record).additionalClassificationIds).toEqual([]);
  });

  it("checks pairs and numbers in shown sections only", () => {
    const draft = detailDraftOf(null);
    draft.lopc.estimatedQuantity = "1.2345";
    draft.damage.currencyCode = "USD";
    draft.damage.damageKindCode = "equipment_damage";
    expect(detailProblems(draft, classificationCodes(2, [], OPTIONS))).toEqual({});
    expect(detailProblems(draft, classificationCodes(1, [3], OPTIONS))).toEqual({
      "lopcDetails.estimatedQuantity": "Enter a number of 0 or more, with up to 3 decimal places.",
      "damageDetails.estimatedCost": "Enter the cost for this currency.",
      "damageDetails.damageKindCode": "This damage kind does not match the chosen classifications.",
    });
    draft.lopc.estimatedQuantity = "0";
    expect(detailProblems(draft, classificationCodes(1, [], OPTIONS))).toEqual({
      "lopcDetails.quantityUnitCode": "Choose the unit of the quantity.",
    });
  });

  it("describes detail history with Unknown for not recorded, never 0 or No", () => {
    const names = { classifications: new Map([[2, "PIT Accident"]]), codes: new Map([["gal", "Gallons"]]) };
    expect(
      detailHistoryChanges(
        { is_lopc: null, quantity_unit_code: null, estimated_quantity: null },
        { is_lopc: false, quantity_unit_code: "gal", estimated_quantity: "0" },
        names,
      ),
    ).toEqual([
      { label: "Is LOPC", from: "Unknown", to: "No" },
      { label: "Quantity unit", from: "Unknown", to: "Gallons" },
      { label: "Estimated quantity", from: "Unknown", to: "0" },
    ]);
    expect(detailHistoryChanges(null, { classification_category_ids: [2] }, names)).toEqual([
      { label: "Classification category", from: "", to: "PIT Accident" },
    ]);
  });
});

describe("Event Experience text and drill-through", () => {
  it("never turns an unknown day count into 0", () => {
    expect(daysSinceText(null)).toBeNull();
    expect(daysSinceText(0)).toBe("Today");
    expect(daysSinceText(1)).toBe("1 day");
    expect(ytdText({ ytdEvents: 2, ytdEventsComplete: false, status: "insufficient_classification_data" })).toBe(
      "At least 2",
    );
    expect(ytdText({ ytdEvents: 0, ytdEventsComplete: true, status: "source_unavailable" })).toBe("Unavailable");
  });

  it("parses drill-through parameters and drops malformed ones", () => {
    expect(
      parseDrill({
        category: "psif",
        failureMechanism: "unknown",
        containment: "bad value!",
        processSafety: "maybe",
        material: " cyclohexane ",
        equipmentTag: "x".repeat(101),
      }),
    ).toEqual({ category: "psif", failureMechanism: "unknown", material: "cyclohexane" });
    expect(parseDrill({ category: "not_a_category" })).toEqual({});
  });

  it("labels drill filters by name", () => {
    const codes = new Map([["corrosion", "Corrosion"]]);
    expect(drillLabel("failureMechanism", "corrosion", codes)).toBe("Failure mechanism: Corrosion");
    expect(drillLabel("containment", "unknown", codes)).toBe("Secondary containment: Unknown / not recorded");
    expect(drillLabel("category", "spill_release_lopc", codes)).toBe("Category: Spill / Release / LOPC");
  });
});
