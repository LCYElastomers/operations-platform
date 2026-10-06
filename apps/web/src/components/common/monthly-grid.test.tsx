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
    expect(render()).toContain(">Incident Classification</h2>");
  });
});
