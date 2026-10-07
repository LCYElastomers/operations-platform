import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MonthlyGrid, type MonthlyGridRow } from "./monthly-grid";

const columns = ["Jan", "Feb", "Mar"];
const rows: MonthlyGridRow[] = [
  { id: "1", label: "First Aid", cells: [{ text: "0" }, { text: "" }, { text: "2" }], total: 2 },
  { id: "2", label: "Fire", cells: [{ text: "" }, { text: "" }, { text: "" }], total: null },
];

function render(props: Partial<React.ComponentProps<typeof MonthlyGrid>> = {}) {
  return renderToStaticMarkup(
    <MonthlyGrid title="Incident Classification" columns={columns} rows={rows} editable {...props} />,
  );
}

describe("MonthlyGrid", () => {
  it("renders one editable input per month and none for YTD", () => {
    const html = render();
    expect(html.match(/<input/g)).toHaveLength(6);
    expect(html).toContain('aria-label="First Aid, Jan"');
    expect(html).toContain(">YTD<");
    expect(html).toContain("Calculated from the monthly values; not editable");
  });

  it("keeps zero distinct from unreported", () => {
    const html = render({ editable: false });
    expect(html).toContain(">0<");
    expect(html).toContain("Not reported");
    expect(html).not.toContain("<input");
  });

  it("marks dirty and invalid cells", () => {
    const html = render({
      rows: [
        { id: "1", label: "A", cells: [{ text: "x", invalid: true, dirty: true }], total: null },
      ],
      columns: ["Jan"],
    });
    expect(html).toContain('aria-invalid="true"');
    expect(html).toContain("bg-destructive/10");
  });

  it("renders a calculated total footer", () => {
    const html = render({ footer: { label: "Total", values: [0, null, 2], total: 2 } });
    expect(html).toContain("<tfoot");
    expect(html).toContain(">Total<");
  });

  it("labels the block with its title", () => {
    const html = render();
    const labelledBy = html.match(/<section aria-labelledby="([^"]+)"/)?.[1];
    expect(labelledBy).toBeTruthy();
    expect(html).toContain(`id="${labelledBy}" class="block px-4 py-2.5">Incident Classification<`);
    expect(html).not.toContain("aria-expanded");
  });

  it("is a disclosure when open is controlled", () => {
    const html = render({ open: true, onOpenChange: () => {}, summary: "YTD 14" });
    expect(html).toContain('aria-expanded="true"');
    expect(html.match(/<input/g)).toHaveLength(6);
    expect(html).not.toContain("YTD 14");
  });

  it("hides the grid and shows the summary when collapsed", () => {
    const html = render({ open: false, onOpenChange: () => {}, summary: "YTD 14", status: "2 unsaved" });
    expect(html).toContain('aria-expanded="false"');
    const controls = html.match(/aria-controls="([^"]+)"/)?.[1];
    expect(html).toContain(`id="${controls}" hidden=""`);
    expect(html).not.toContain("<input");
    expect(html).toContain("YTD 14");
    expect(html).toContain("2 unsaved");
  });
});
