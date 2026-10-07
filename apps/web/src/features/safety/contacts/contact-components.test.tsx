import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { Contact, ContactDashboardResponse, Supervisor } from "./api";
import { supervisorMonthColumns } from "./contact-dashboard";
import { tallyTiles } from "./contact-data";
import { ContactEditor, ContactRow } from "./recent-contacts";
import { SupervisorForm, SupervisorRow } from "./supervisor-manager";
import { AddedFeedback, SupervisorTile, TallyBoard } from "./tally-board";

const TODAY = "2026-10-07";

function supervisor(id: number, displayName: string, overrides: Partial<Supervisor> = {}): Supervisor {
  return {
    id,
    displayName,
    active: true,
    participationEligible: true,
    effectiveFrom: "2026-01-01",
    effectiveTo: null,
    hasContacts: false,
    createdAt: "2026-10-01T00:00:00Z",
    createdBy: "tester",
    updatedAt: "2026-10-01T00:00:00Z",
    updatedBy: "tester",
    ...overrides,
  };
}

const SUPERVISORS = [supervisor(1, "Casey Brown"), supervisor(2, "Avery <b>Jones</b>"), supervisor(3, "Blake Smith")];

const CONTACT: Contact = {
  id: 7,
  contactDate: "2026-10-06",
  supervisorId: 1,
  supervisorName: "Casey Brown",
  createdAt: "2026-10-07T12:00:00Z",
  createdBy: "tester",
  updatedAt: "2026-10-07T12:00:00Z",
  updatedBy: "tester",
};

function board(props: Partial<React.ComponentProps<typeof TallyBoard>> = {}) {
  return renderToStaticMarkup(
    <TallyBoard
      tiles={tallyTiles(SUPERVISORS, TODAY)}
      counts={new Map([[1, 12], [3, 0]])}
      countLabel="This month"
      canEdit
      pendingIds={new Set()}
      blocked={false}
      onAdd={() => {}}
      {...props}
    />,
  );
}

describe("TallyBoard", () => {
  it("shows tiles alphabetically with the month count and a large +1 button", () => {
    const html = board();
    const order = ["Avery", "Blake", "Casey"].map((name) => html.indexOf(name));
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(html).toContain("This month: <span");
    expect(html).toContain(">12<");
    expect(html.match(/\+1 Contact</g)).toHaveLength(3);
    expect(html.match(/h-12 w-full/g)).toHaveLength(3);
    expect(html).toContain('aria-label="+1 Contact for Casey Brown"');
  });

  it("escapes names", () => {
    expect(board()).toContain("Avery &lt;b&gt;Jones&lt;/b&gt;");
  });

  it("never ranks, colour-codes, or compares supervisors to a target", () => {
    const html = board();
    expect(html).not.toMatch(/target|rank|top |behind|goal|of 8|\/ ?8\b/i);
    expect(html).not.toMatch(/text-(red|green|amber)|bg-(red|green|amber)/);
  });

  it("is read-only without edit permission", () => {
    const html = board({ canEdit: false });
    expect(html).not.toContain("+1 Contact");
    expect(html).toContain(">12<");
  });

  it("disables only the tile being saved, and every tile while the date is invalid", () => {
    expect(board({ pendingIds: new Set([1]) }).match(/disabled=""/g)).toHaveLength(1);
    expect(board({ pendingIds: new Set([1]) })).toContain('aria-busy="true"');
    expect(board({ blocked: true }).match(/disabled=""/g)).toHaveLength(3);
  });

  it("shows a placeholder, not zero, while counts load", () => {
    const html = board({ counts: undefined });
    expect(html).toContain("animate-pulse");
    expect(html).not.toContain(">0<");
  });

  it("explains a supervisor outside their effective dates", () => {
    const [tile] = tallyTiles([supervisor(9, "Drew Lee", { effectiveFrom: "2026-11-01" })], TODAY);
    const html = renderToStaticMarkup(<SupervisorTile tile={tile} count={0} countLabel="This month" canEdit />);
    expect(html).toContain("Effective from Sun, Nov 1, 2026");
    expect(html).toContain('disabled=""');
  });
});

describe("AddedFeedback", () => {
  it("announces the save and offers Undo", () => {
    const html = renderToStaticMarkup(<AddedFeedback message="Contact added: Casey Brown." onUndo={() => {}} />);
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-live="polite"');
    expect(html).toContain("Contact added: Casey Brown.");
    expect(html).toContain(">Undo<");
    expect(html).toContain("h-11");
  });

  it("offers no Undo without a just-added contact", () => {
    expect(renderToStaticMarkup(<AddedFeedback message="Contact deleted." />)).not.toContain("Undo");
    expect(renderToStaticMarkup(<AddedFeedback message={null} onUndo={() => {}} />)).not.toContain(">Undo<");
  });
});

describe("ContactRow", () => {
  it("shows the date and supervisor, read-only without permission", () => {
    const html = renderToStaticMarkup(<ContactRow contact={CONTACT} canEdit={false} />);
    expect(html).toContain("Casey Brown");
    expect(html).toContain("Tue, Oct 6, 2026");
    expect(html).not.toContain(">Edit<");
    expect(html).not.toContain(">Delete<");
  });

  it("shows always-visible, touch-sized Edit and Delete to editors", () => {
    const html = renderToStaticMarkup(<ContactRow contact={CONTACT} canEdit />);
    expect(html).toContain("Edit");
    expect(html).toContain("Delete");
    expect(html.match(/h-11 min-w-24/g)).toHaveLength(2);
    expect(html).not.toMatch(/group-hover|hover:opacity|opacity-0/);
  });

  it("asks before deleting", () => {
    const html = renderToStaticMarkup(<ContactRow contact={CONTACT} canEdit confirmingDelete />);
    expect(html).toContain('role="alertdialog"');
    expect(html).toContain("Delete this contact? This cannot be undone.");
    expect(html).not.toContain(">Edit<");
  });
});

describe("ContactEditor", () => {
  const render = (props: Partial<React.ComponentProps<typeof ContactEditor>> = {}) =>
    renderToStaticMarkup(
      <ContactEditor
        value={{ contactDate: "2026-10-06", supervisorId: 1 }}
        onChange={() => {}}
        onSubmit={() => {}}
        onCancel={() => {}}
        supervisors={[...SUPERVISORS, supervisor(4, "Former", { active: false, effectiveTo: "2026-06-30" })]}
        today={TODAY}
        dateError={null}
        {...props}
      />,
    );

  it("edits the date (no future dates) and the supervisor", () => {
    const html = render();
    expect(html).toContain('type="date"');
    expect(html).toContain('max="2026-10-07"');
    expect(html).toContain("<select");
    expect(html).toContain("Former (inactive)");
  });

  it("shows date errors and blocks saving", () => {
    const html = render({ dateError: "The contact date cannot be in the future." });
    expect(html).toContain('aria-invalid="true"');
    expect(html).toContain("The contact date cannot be in the future.");
    expect(html).toMatch(/type="submit"[^>]*disabled=""/);
  });
});

describe("Supervisor management", () => {
  it("uses neutral status terms only", () => {
    const html = renderToStaticMarkup(
      <>
        <SupervisorRow supervisor={supervisor(1, "Casey Brown")} />
        <SupervisorRow
          supervisor={supervisor(2, "Blake", {
            active: false,
            participationEligible: false,
            effectiveTo: "2026-06-30",
            hasContacts: true,
          })}
        />
      </>,
    );
    expect(html).toContain("Active");
    expect(html).toContain("Inactive");
    expect(html).toContain("Eligible for participation");
    expect(html).toContain("Not eligible for participation");
    expect(html).toContain("Thu, Jan 1, 2026 – Tue, Jun 30, 2026");
    const text = html.replace(/<[^>]*>/g, " ");
    expect(text).not.toMatch(/\b(poor|good|bad|low|high|under|over|behind|perform\w*|rating|score)\b/i);
  });

  it("offers Delete only for supervisors without contacts", () => {
    const withContacts = renderToStaticMarkup(<SupervisorRow supervisor={supervisor(1, "A", { hasContacts: true })} />);
    const without = renderToStaticMarkup(<SupervisorRow supervisor={supervisor(1, "A")} />);
    expect(withContacts).not.toContain(">Delete<");
    expect(without).toContain("Delete");
  });

  it("has explicit active and eligibility choices and effective dates", () => {
    const html = renderToStaticMarkup(
      <SupervisorForm
        draft={{ displayName: "", active: false, participationEligible: true, effectiveFrom: "2026-10-01", effectiveTo: "" }}
        onChange={() => {}}
        onSubmit={() => {}}
        errors={{ effectiveTo: "An inactive supervisor needs an end date." }}
        showErrors
        submitLabel="Add Supervisor"
      />,
    );
    expect(html.match(/type="checkbox"/g)).toHaveLength(2);
    expect(html.match(/type="date"/g)).toHaveLength(2);
    expect(html).toContain("(required when inactive)");
    expect(html).toContain("An inactive supervisor needs an end date.");
    expect(html.match(/min-h-11/g)).toHaveLength(2);
  });
});

describe("Supervisor × month table", () => {
  it("has Supervisor, Jan..Dec, and YTD columns", () => {
    const headers = supervisorMonthColumns.map((c) => c.header);
    expect(headers).toEqual(["Supervisor", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "YTD"]);
    const row: ContactDashboardResponse["supervisors"][number] = {
      supervisorId: 1,
      displayName: "Casey",
      active: true,
      monthly: [1, 0, ...Array(10).fill(null)],
      total: 1,
    };
    const month = supervisorMonthColumns[2] as { accessorFn: (r: typeof row, index: number) => unknown };
    expect(month.accessorFn(row, 0)).toBe(0);
  });
});
