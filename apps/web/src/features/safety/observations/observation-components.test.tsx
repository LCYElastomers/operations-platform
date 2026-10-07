import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { Observation, ObservationCategory } from "./api";
import { MonthSummary } from "./month-summary";
import { ObservationCard } from "./observation-card";
import { emptyDraft, validateDraft, type ObservationDraft } from "./observation-data";
import { ObservationForm } from "./observation-form";

const TODAY = "2026-10-07";
const CATEGORIES: ObservationCategory[] = [
  { id: 1, code: "housekeeping", name: "Housekeeping" },
  { id: 2, code: "fire", name: "Fire" },
  { id: 3, code: "fire_system", name: "Fire System" },
];

function renderForm(props: Partial<React.ComponentProps<typeof ObservationForm>> = {}) {
  const draft = props.draft ?? emptyDraft(TODAY);
  return renderToStaticMarkup(
    <ObservationForm
      draft={draft}
      onChange={() => {}}
      onSubmit={() => {}}
      categories={CATEGORIES}
      errors={validateDraft(draft, TODAY)}
      showErrors={false}
      today={TODAY}
      submitLabel="Add Observation"
      {...props}
    />,
  );
}

const OBSERVATION: Observation = {
  id: 7,
  observedOn: "2026-10-06",
  outcome: "unsafe",
  kind: "condition",
  categoryId: 1,
  categoryCode: "housekeeping",
  categoryName: "Housekeeping",
  areaLocation: "Dock 3",
  description: "Pallet wrap <b>on</b> walkway",
  correctiveAction: null,
  createdAt: "2026-10-07T12:00:00Z",
  createdBy: "tester",
  updatedAt: "2026-10-07T12:00:00Z",
  updatedBy: "tester",
};

describe("ObservationForm", () => {
  it("offers every choice as a large tile, never a long select", () => {
    const html = renderForm();
    expect(html.match(/type="radio"/g)).toHaveLength(2 + 2 + CATEGORIES.length);
    expect(html).not.toContain("<select");
    expect(html.match(/min-h-12/g)?.length).toBe(2 + 2 + CATEGORIES.length);
    expect(html).toContain(">Fire<");
    expect(html).toContain(">Fire System<");
  });

  it("has the fields in entry order with an explicit Add button", () => {
    const html = renderForm();
    const order = ["Date", "Safe or Unsafe", "Act or Condition", "Category", "Area / Location", "Description", "Corrective Action", "Add Observation"];
    const positions = order.map((label) => html.indexOf(label));
    expect(positions.every((p) => p >= 0)).toBe(true);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
    expect(html).toContain('type="submit"');
    expect(html).toContain(`max="${TODAY}"`);
  });

  it("starts with nothing chosen", () => {
    expect(renderForm()).not.toMatch(/checked=""/);
  });

  it("marks the chosen values", () => {
    const draft: ObservationDraft = { ...emptyDraft(TODAY), outcome: "safe", kind: "act", categoryId: 3 };
    const html = renderForm({ draft });
    expect(html.match(/checked=""/g)).toHaveLength(3);
    expect(html).toMatch(/checked="" value="3"/);
  });

  it("shows validation only after a save was attempted", () => {
    expect(renderForm()).not.toContain("Choose Safe or Unsafe.");
    const html = renderForm({ showErrors: true });
    expect(html).toContain("Choose Safe or Unsafe.");
    expect(html).toContain("Choose Act or Condition.");
    expect(html).toContain("Choose a category.");
    expect(html).toContain("Complete the highlighted fields to save.");
  });

  it("shows a failed save and the cancel action for edits", () => {
    const html = renderForm({ saveError: "Nothing was saved.", onCancel: () => {}, submitLabel: "Save Changes" });
    expect(html).toContain('role="alert"');
    expect(html).toContain("Nothing was saved.");
    expect(html).toContain(">Cancel<");
    expect(renderForm()).not.toContain(">Cancel<");
  });

  it("disables input while saving", () => {
    const html = renderForm({ pending: true });
    expect(html).toContain('aria-busy="true"');
    expect(html.match(/disabled=""/g)?.length).toBeGreaterThanOrEqual(8);
  });
});

describe("ObservationCard", () => {
  it("is read-only without edit permission", () => {
    const html = renderToStaticMarkup(<ObservationCard observation={OBSERVATION} canEdit={false} />);
    expect(html).toContain("Unsafe Condition");
    expect(html).toContain("Housekeeping");
    expect(html).toContain("Dock 3");
    expect(html).toContain("Tue, Oct 6, 2026");
    expect(html).not.toContain(">Edit<");
    expect(html).not.toContain(">Delete<");
  });

  it("shows always-visible edit and delete actions to editors", () => {
    const html = renderToStaticMarkup(<ObservationCard observation={OBSERVATION} canEdit />);
    expect(html).toContain("Edit");
    expect(html).toContain("Delete");
    expect(html).not.toMatch(/group-hover|hover:opacity|opacity-0/);
  });

  it("asks before deleting", () => {
    const html = renderToStaticMarkup(<ObservationCard observation={OBSERVATION} canEdit confirmingDelete />);
    expect(html).toContain('role="alertdialog"');
    expect(html).toContain("Delete this observation? This cannot be undone.");
    expect(html).not.toContain(">Edit<");
  });

  it("escapes free text and omits empty optional fields", () => {
    const html = renderToStaticMarkup(<ObservationCard observation={OBSERVATION} canEdit={false} />);
    expect(html).toContain("Pallet wrap &lt;b&gt;on&lt;/b&gt; walkway");
    expect(html).not.toContain("Corrective action");
  });

  it("marks the observation just added", () => {
    const html = renderToStaticMarkup(<ObservationCard observation={OBSERVATION} canEdit highlighted />);
    expect(html).toContain("Just added");
  });
});

describe("MonthSummary", () => {
  const counts = { total: 5, safe: 2, unsafe: 3, safeAct: 1, safeCondition: 1, unsafeAct: 0, unsafeCondition: 3 };

  it("shows each count once with category counts that have observations", () => {
    const html = renderToStaticMarkup(
      <MonthSummary
        period="October 2026"
        counts={counts}
        categories={[
          { categoryId: 1, code: "housekeeping", name: "Housekeeping", total: 5, safe: 2, unsafe: 3 },
          { categoryId: 2, code: "fire", name: "Fire", total: 0, safe: 0, unsafe: 0 },
        ]}
      />,
    );
    for (const label of ["Total", "Safe", "Unsafe", "Safe Act", "Safe Condition", "Unsafe Act", "Unsafe Condition"]) {
      expect(html).toContain(`>${label}</dt>`);
    }
    expect(html).toContain("October 2026 summary");
    expect(html).toContain("Housekeeping");
    expect(html).not.toContain(">Fire");
  });

  it("says when the month has no observations", () => {
    const empty = { ...counts, total: 0, safe: 0, unsafe: 0, safeAct: 0, safeCondition: 0, unsafeCondition: 0 };
    const html = renderToStaticMarkup(<MonthSummary period="November 2026" counts={empty} categories={[]} />);
    expect(html).toContain("No observations recorded for November 2026.");
  });

  it("shows placeholders, not zeros, while loading", () => {
    const html = renderToStaticMarkup(<MonthSummary period="October 2026" counts={undefined} categories={[]} loading />);
    expect(html).toContain("animate-pulse");
    expect(html).not.toMatch(/<dd[^>]*>0<\/dd>/);
  });
});
