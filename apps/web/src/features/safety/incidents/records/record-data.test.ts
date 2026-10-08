import { describe, expect, it } from "vitest";

import type { MonthReconciliation } from "./api";
import {
  describeReconciliation,
  historyChanges,
  monthActionLabel,
  monthDateRange,
  monthTitle,
} from "./record-data";

const month = (monthlyTotal: number | null, documented: number, state: MonthReconciliation["state"]) => ({
  month: 1,
  eventType: "incident" as const,
  monthlyTotal,
  documented,
  state,
});

describe("record labels", () => {
  it("names month actions for assistive technology", () => {
    expect(monthActionLabel("incident", 3, 2026, 1)).toBe("Manage 3 Incident records for January 2026");
    expect(monthActionLabel("incident", 1, 2026, 1)).toBe("Manage 1 Incident record for January 2026");
    expect(monthActionLabel("near_miss", 0, 2026, 5)).toBe("Add Near Miss record for May 2026");
    expect(monthTitle("incident", 2026, 1)).toBe("January 2026 Incidents");
    expect(monthTitle("near_miss", 2026, 2)).toBe("February 2026 Near Misses");
  });

  it("explains every reconciliation state without changing the total", () => {
    expect(describeReconciliation(month(2, 2, "reconciled"))).toBe("Reported total 2; 2 records documented. They match.");
    expect(describeReconciliation(month(0, 0, "reconciled"))).toBe("Reported total 0 and no records.");
    expect(describeReconciliation(month(3, 1, "records_missing"))).toContain("2 not yet documented");
    expect(describeReconciliation(month(1, 2, "records_exceed_total"))).toContain("The total is not changed.");
    expect(describeReconciliation(month(null, 1, "total_unreported_with_records"))).toContain(
      "The total is not filled in from records.",
    );
    expect(describeReconciliation(month(0, 1, "explicit_zero_with_records"))).toContain("Reported total 0, but 1 record");
    expect(describeReconciliation(month(null, 0, "no_total_and_no_records"))).toBe(
      "No total is reported and no records are documented.",
    );
  });

  it("limits record dates to the month and never past today", () => {
    expect(monthDateRange(2026, 2, "2026-10-08")).toEqual({ min: "2026-02-01", max: "2026-02-28" });
    expect(monthDateRange(2024, 2, "2026-10-08")).toEqual({ min: "2024-02-01", max: "2024-02-29" });
    expect(monthDateRange(2026, 10, "2026-10-08")).toEqual({ min: "2026-10-01", max: "2026-10-08" });
    expect(monthDateRange(2026, 11, "2026-10-08")).toBeNull();
  });

  it("lists changed fields of an audit event by name", () => {
    const names = { areas: new Map([[4, "Lab"]]), classifications: new Map<number, string>() };
    expect(
      historyChanges(
        { incident_number: null, area_id: null, status: "active", version: 1 },
        { incident_number: "LCY-2026-001", area_id: 4, status: "voided", version: 2 },
        names,
      ),
    ).toEqual([
      { label: "Number", from: "—", to: "LCY-2026-001" },
      { label: "Area", from: "—", to: "Lab" },
      { label: "Status", from: "Active", to: "Voided" },
    ]);
  });
});
