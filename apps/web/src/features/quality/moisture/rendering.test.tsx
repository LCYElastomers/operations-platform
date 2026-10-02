import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MetricCard } from "@/components/common/metric-card";

import type { MoistureRecord } from "./api";
import { RecentMaterialsTable } from "./recent-materials-table";

const record = (overrides: Partial<MoistureRecord>): MoistureRecord => ({
  date: "2026-09-01",
  campaignNo: "26101",
  lot: "A260901-01",
  location: "Silo 1",
  product: "PRD-A",
  avgMoisture: 0.4,
  avgColor: 40,
  avgCombinedBd: 0.7,
  ...overrides,
});

describe("MetricCard null versus zero", () => {
  it("renders zero as a value", () => {
    const html = renderToStaticMarkup(<MetricCard label="Records" value={0} caption="c" />);
    expect(html).toContain(">0<");
    expect(html).not.toContain("No data");
  });

  it("renders null as no data", () => {
    const html = renderToStaticMarkup(<MetricCard label="Records" value={null} />);
    expect(html).toContain("No data");
    expect(html).toContain("—");
  });

  it("renders identifiers verbatim instead of formatting them as numbers", () => {
    const html = renderToStaticMarkup(<MetricCard label="Lot" value="0012345" />);
    expect(html).toContain(">0012345<");
  });
});

function renderTable(records: MoistureRecord[]) {
  return renderToStaticMarkup(
    <RecentMaterialsTable records={records} loading={false} emptyState={<p>EMPTY</p>} />,
  );
}

describe("RecentMaterialsTable", () => {
  it("renders zero measurements as zero and null measurements as missing", () => {
    const html = renderTable([record({ avgMoisture: 0, avgColor: null })]);
    expect(html).toContain(">0.000<");
    expect(html).toContain('title="No value in source"');
  });

  it("rounds for display but keeps full source precision in the title", () => {
    const html = renderTable([record({ avgMoisture: 0.43333333333333335 })]);
    expect(html).toContain(">0.433<");
    expect(html).toContain('title="0.43333333333333335"');
  });

  it("shows identifiers and locations exactly as provided", () => {
    const html = renderTable([record({ campaignNo: "00042", location: "SILO 1" })]);
    expect(html).toContain(">00042<");
    expect(html).toContain(">SILO 1<");
  });

  it("renders rows in the order provided, without sort controls", () => {
    const html = renderTable([
      record({ lot: "NEWEST", date: "2026-09-03" }),
      record({ lot: "OLDEST", date: "2026-09-01" }),
    ]);
    expect(html.indexOf("NEWEST")).toBeLessThan(html.indexOf("OLDEST"));
    expect(html).not.toContain("<button");
  });

  it("renders the empty state when there are no records", () => {
    expect(renderTable([])).toContain("EMPTY");
  });

  it("has the required columns", () => {
    const html = renderTable([record({})]);
    for (const header of [
      "Date",
      "Campaign",
      "Product",
      "Lot",
      "Location",
      "Avg Moisture",
      "Avg Color",
      "Avg Combined BD",
    ]) {
      expect(html).toContain(`>${header}<`);
    }
  });
});
