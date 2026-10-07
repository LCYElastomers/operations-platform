import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { MonthCounts, PerformanceMonth } from "./api";
import { monthColumns } from "./performance-dashboard";
import { MonthCard } from "./performance-data-entry";

const COUNTS: MonthCounts = {
  trir: 1,
  firstAid: 0,
  lopc: 2,
  propertyEquipmentDamage: 0,
  recordableInjury: 1,
  occupationalIllness: 0,
  propertyDamage: 0,
  equipmentDamageFailure: 0,
};

const CLOSED: PerformanceMonth = {
  month: 8,
  status: "closed",
  hours: {
    totalHours: 18031,
    hourlyHours: null,
    salaryHours: null,
    monthClosed: true,
    updatedAt: "2026-10-06T12:00:00Z",
    updatedBy: "tester",
  },
  counts: COUNTS,
  countsConfirmed: true,
  eligible: true,
  ineligibleReason: null,
  canEnter: true,
  canClose: true,
};

function card(props: Partial<React.ComponentProps<typeof MonthCard>> = {}) {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <MonthCard
        year={2026}
        month={CLOSED}
        countSource="incidents"
        canEdit
        draft={null}
        onDraft={() => {}}
        {...props}
      />
    </QueryClientProvider>,
  );
}

describe("MonthCard", () => {
  it("shows status, hours, and read-only Incident counts", () => {
    const html = card();
    expect(html).toContain("August 2026");
    expect(html).toContain(">Closed<");
    expect(html).toContain('value="18031"');
    expect(html).toContain("Recordable injuries");
    expect(html).toContain("Equipment damage / failure");
    expect(html).toContain("(confirmed; blanks count as zero)");
    expect(html).toContain("Saved: 18,031 h, closed");
  });

  it("saves only when something changed", () => {
    expect(card()).toMatch(/<button[^>]*disabled=""[^>]*>Save August<\/button>/);
    const edited = card({ draft: { total: "18000", hourly: "", salary: "", breakdown: false, closed: true } });
    expect(edited).not.toMatch(/<button[^>]*disabled=""[^>]*>Save August/);
    expect(edited).toContain("Discard changes");
    expect(card()).toContain("Clear month");
  });

  it("shows validation errors for an edited draft", () => {
    const html = card({
      draft: { total: "100", hourly: "60", salary: "30", breakdown: true, closed: true },
    });
    expect(html).toContain("Hourly and salary hours must add up to total hours.");
  });

  it("is read-only without edit permission", () => {
    const html = card({ canEdit: false });
    expect(html).not.toContain("Save August");
    expect(html).not.toContain("Clear month");
    expect(html).toMatch(/<input[^>]*disabled=""[^>]*value="18031"|<input[^>]*value="18031"[^>]*disabled=""/);
  });

  it("explains unconfirmed counts and future months", () => {
    const open = card({
      month: { ...CLOSED, status: "reported", countsConfirmed: false, canClose: false, hours: { ...CLOSED.hours!, monthClosed: false } },
    });
    expect(open).toContain("(not confirmed until the month is closed)");
    expect(open).toContain("Can be closed after the month ends.");
    const future = card({ month: { ...CLOSED, status: "not_reported", hours: null, canEnter: false, canClose: false } });
    expect(future).toContain("This month has not started.");
    expect(future).not.toContain("Save August");
  });

  it("shows the legacy combined counts before 2026", () => {
    const html = card({ countSource: "performance_legacy", year: 2025 });
    expect(html).toContain("Recordable injuries &amp; illnesses");
    expect(html).toContain("Property &amp; Equipment Damage");
    expect(html).not.toContain("Equipment damage / failure");
    expect(html).toContain("(workbook import; a blank is not confirmed)");
    expect(html).not.toContain("blanks count as zero");
    expect(html).toContain("Month closed: worked hours are final");
  });
});

describe("monthly status table", () => {
  it("keeps null distinct from zero", () => {
    const value = (id: string, row: PerformanceMonth) => {
      const column = monthColumns.find((c) => c.id === id) as unknown as {
        accessorFn: (r: PerformanceMonth, index: number) => unknown;
      };
      return column.accessorFn(row, 0);
    };
    const unreported: PerformanceMonth = {
      ...CLOSED,
      status: "not_reported",
      hours: null,
      counts: { ...COUNTS, lopc: null },
      countsConfirmed: false,
    };
    expect(value("total", CLOSED)).toBe("18,031");
    expect(value("total", unreported)).toBe("—");
    expect(value("firstAid", CLOSED)).toBe(0);
    expect(value("lopc", unreported)).toBe("—");
    expect(value("counts", CLOSED)).toBe("Confirmed");
  });
});
