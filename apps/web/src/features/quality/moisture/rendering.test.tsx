// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";

import { MetricCard } from "@/components/common/metric-card";

import type { MoistureLotDetail, MoistureRecord } from "./api";
import { LotLocationRecords, LotTable } from "./lot-table";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const record = (overrides: Partial<MoistureRecord>): MoistureRecord => ({
  date: "2026-09-01",
  campaignNo: "26101",
  lot: "260932010",
  location: "PKG/0",
  product: "3411",
  avgMoisture: 0.4,
  avgColor: 40,
  avgCombinedBd: 0.7,
  ...overrides,
});

const lot = (overrides: Partial<MoistureLotDetail>): MoistureLotDetail => ({
  product: "3411",
  lot: "260932010",
  firstDate: "2026-09-01",
  lastDate: "2026-09-03",
  campaignNos: ["26101"],
  locations: ["PKG/0", "PKG/1", "SILO/1"],
  recordCount: 3,
  avgMoisture: 0.4,
  avgColor: 40,
  avgCombinedBd: 0.7,
  moistureValueCount: 3,
  colorValueCount: 3,
  combinedBdValueCount: 3,
  records: [
    record({ location: "PKG/0" }),
    record({ location: "PKG/1", date: "2026-09-02" }),
    record({ location: "SILO/1", date: "2026-09-03" }),
  ],
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

function renderTable(lots: MoistureLotDetail[]) {
  return renderToStaticMarkup(<LotTable lots={lots} loading={false} emptyState={<p>EMPTY</p>} />);
}

describe("LotTable", () => {
  it("has the master columns", () => {
    const html = renderTable([lot({})]);
    for (const header of [
      "Date",
      "Product",
      "Lot",
      "Campaign",
      "Records",
      "Avg Moisture",
      "Avg Color",
      "Avg Combined BD",
    ]) {
      expect(html).toContain(`>${header}<`);
    }
  });

  it("starts collapsed, showing one row per lot and no location records", () => {
    const html = renderTable([lot({})]);
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain(">PKG/1<");
    expect(html).not.toContain(">Location<");
  });

  it("shows the lot date range", () => {
    expect(renderTable([lot({})])).toContain("Sep 1, 2026 – Sep 3, 2026");
    expect(renderTable([lot({ lastDate: "2026-09-01" })])).not.toContain("–");
  });

  it("renders zero lot means as zero and null lot means as missing", () => {
    const html = renderTable([lot({ avgMoisture: 0, avgColor: null })]);
    expect(html).toContain(">0.000<");
    expect(html).toContain('title="No value in source"');
  });

  it("rounds for display but keeps full precision in the title", () => {
    const html = renderTable([lot({ avgMoisture: 0.43333333333333335 })]);
    expect(html).toContain(">0.433<");
    expect(html).toContain('title="0.43333333333333335"');
  });

  it("shows identifiers exactly as provided", () => {
    const html = renderTable([lot({ product: "007", lot: "0012345", campaignNos: ["00042"] })]);
    expect(html).toContain(">007<");
    expect(html).toContain(">0012345<");
    expect(html).toContain(">00042<");
  });

  it("renders lots in the order provided, without sort controls", () => {
    const html = renderTable([lot({ lot: "NEWEST" }), lot({ lot: "OLDEST" })]);
    expect(html.indexOf("NEWEST")).toBeLessThan(html.indexOf("OLDEST"));
    expect(html).not.toContain("aria-sort");
  });

  it("renders the empty state when there are no lots", () => {
    expect(renderTable([])).toContain("EMPTY");
  });
});

describe("LotLocationRecords", () => {
  it("lists each location record with its own measurements", () => {
    const html = renderToStaticMarkup(
      <LotLocationRecords
        records={[
          record({ location: "SILO 1", avgMoisture: 0 }),
          record({ location: null, avgColor: null }),
        ]}
      />,
    );
    for (const header of ["Date", "Location", "Moisture", "Color", "Combined BD"]) {
      expect(html).toContain(`>${header}<`);
    }
    expect(html).toContain(">SILO 1<");
    expect(html).toContain('title="No location in source"');
    expect(html).toContain(">0.000<");
    expect(html).toContain('title="No value in source"');
  });
});

describe("LotTable drill-down", () => {
  let root: Root | null = null;
  let container: HTMLDivElement;

  afterEach(async () => {
    await act(async () => root?.unmount());
    root = null;
    container.remove();
  });

  it("expands and collapses a lot's location records", async () => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () =>
      root!.render(
        <LotTable
          lots={[lot({}), lot({ lot: "OTHER", records: [record({ location: "RAIL" })] })]}
          loading={false}
          emptyState={null}
        />,
      ),
    );
    const [first, second] = container.querySelectorAll<HTMLButtonElement>("button[aria-expanded]");
    expect(first.getAttribute("aria-label")).toBe("Show location records for 3411 lot 260932010");

    await act(async () => first.click());

    expect(first.getAttribute("aria-expanded")).toBe("true");
    const detail = document.getElementById(first.getAttribute("aria-controls")!);
    const locations = [...detail!.querySelectorAll(":scope tbody tr")].map(
      (row) => row.children[1].textContent,
    );
    expect(locations).toEqual(["PKG/0", "PKG/1", "SILO/1"]);
    expect(second.getAttribute("aria-expanded")).toBe("false");
    expect(container.textContent).not.toContain("RAIL");

    await act(async () => first.click());

    expect(first.getAttribute("aria-expanded")).toBe("false");
    expect(container.textContent).not.toContain("SILO/1");
  });
});
