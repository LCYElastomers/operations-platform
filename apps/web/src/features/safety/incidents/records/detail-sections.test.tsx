/** @vitest-environment jsdom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { RecordOptionsResponse } from "./api";
import { classificationCodes, detailDraftOf, detailProblems } from "./detail-data";
import { DetailSections } from "./detail-sections";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/** Test fixture, not production data. */
const OPTIONS: RecordOptionsResponse = {
  areas: [],
  classifications: [
    { id: 1, code: "first_aid", name: "First Aid", active: true },
    { id: 2, code: "spill_release", name: "Spill / Release", active: true },
    { id: 3, code: "property_damage", name: "Property Damage", active: true },
    { id: 4, code: "equipment_damage_failure", name: "Equipment Damage / Failure", active: true },
    { id: 5, code: "pit_accident", name: "PIT Accident", active: true },
  ],
  injuryCauses: [
    { id: 21, code: "struck_by", name: "Struck By", active: true },
    { id: 22, code: "contact_with", name: "Contact With", active: true },
  ],
  bodyParts: [
    { id: 31, code: "hand", name: "Hand", active: true },
    { id: 32, code: "fingers", name: "Fingers", active: true },
  ],
  eventCauses: [
    { id: 41, code: "human_performance", name: "Human Performance", active: true },
    { id: 42, code: "procedures", name: "Procedures", active: true },
  ],
  detailCodes: {
    lopc_contributing_factor: [
      { code: "mechanical_integrity", name: "Mechanical Integrity", active: true },
      { code: "human_error", name: "Human Error", active: true },
      { code: "other", name: "Other", active: true },
    ],
  },
};

let root: Root | null = null;
let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  container.remove();
});

async function render(primaryId: number, additional: number[] = []) {
  const draft = detailDraftOf(null);
  draft.additional = additional;
  const codes = classificationCodes(primaryId, additional, OPTIONS.classifications);
  if (!root) root = createRoot(container);
  await act(async () => {
    root!.render(
      <DetailSections
        draft={draft}
        onChange={() => {}}
        primaryId={primaryId}
        codes={codes}
        options={OPTIONS}
        record={null}
        problems={detailProblems(draft, codes)}
      />,
    );
  });
  return { draft, codes };
}

const text = () => container.textContent ?? "";

describe("DetailSections selection groups", () => {
  it("shows Injury Cause and Body Part only when First Aid is selected", async () => {
    await render(1);
    expect(text()).toContain("Injury cause");
    expect(text()).toContain("Body part");
    expect(text()).toContain("Choose at least one injury cause.");
    expect(text()).toContain("Choose at least one body part.");
    expect(text()).toContain("Event cause");

    await render(2);
    expect(text()).not.toContain("Injury cause");
    expect(text()).not.toContain("Body part");
    expect(text()).toContain("Event cause");
  });

  it("keeps LOPC contributing factor as a single select, not multi-select checkboxes", async () => {
    await render(2);
    const factor = container.querySelector<HTMLSelectElement>("select[id*='contributingFactorCode']");
    expect(factor).not.toBeNull();
    expect([...factor!.options].map((o) => o.textContent)).toEqual(
      expect.arrayContaining(["Mechanical Integrity", "Human Error", "Other"]),
    );
    // No checkbox grid for LOPC contributing factors.
    const factorChecks = [...container.querySelectorAll("input[type='checkbox']")].filter((el) =>
      (el.parentElement?.textContent ?? "").match(/Mechanical Integrity|Human Error/),
    );
    expect(factorChecks).toHaveLength(0);
  });

  it("does not add Property Damage, Equipment Damage, PIT, or PSIF category-selection groups", async () => {
    await render(1, [3, 4, 5]);
    // Classifications appear only as Additional classifications checkboxes.
    expect(text()).toContain("Additional classifications");
    expect(text()).toContain("Property Damage");
    expect(text()).toContain("Equipment Damage / Failure");
    expect(text()).toContain("PIT Accident");
    const legends = [...container.querySelectorAll("legend")].map((el) => el.textContent ?? "");
    expect(legends.some((l) => /^Property Damage/.test(l))).toBe(false);
    expect(legends.some((l) => /^Equipment Damage/.test(l))).toBe(false);
    expect(legends.some((l) => /^PIT/.test(l))).toBe(false);
    expect(legends.some((l) => l === "PSIF" || /^PSIF categor/.test(l))).toBe(false);
    // PSIF remains the existing serious-risk detail workflow.
    expect(text()).toContain("Serious risk (PSIF)");
    expect(text()).toContain("Potential serious injury or fatality (PSIF)");
  });
});
