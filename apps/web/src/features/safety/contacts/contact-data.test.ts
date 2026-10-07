import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api-client";

import { describeContactError, type ContactDashboardResponse, type Supervisor } from "./api";
import {
  contactDateError,
  contactsByMonth,
  countAxis,
  countPeriodLabel,
  editableSupervisors,
  emptySupervisorDraft,
  formatParticipation,
  formatRate,
  headlineMonth,
  newRequestId,
  normalizeName,
  participationByMonth,
  runningContactTotal,
  siteIsoDate,
  tallyTiles,
  toSupervisorInput,
  validateSupervisorDraft,
} from "./contact-data";

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

const SUPERVISORS = [
  supervisor(1, "Casey Brown"),
  supervisor(2, "avery Jones"),
  supervisor(3, "Blake Smith", { active: false, effectiveTo: "2026-06-30" }),
  supervisor(4, "Drew Lee", { effectiveFrom: "2026-11-01" }),
];

describe("contact date", () => {
  it.each([
    ["2026-10-07", null],
    ["2026-01-01", null],
    ["2026-10-08", "The contact date cannot be in the future."],
    ["", "Choose the contact date."],
    ["2026-02-30", "Enter a valid date."],
    ["1999-12-31", "The date is too early."],
  ])("%s", (date, expected) => {
    expect(contactDateError(date, TODAY)).toBe(expected);
  });

  it.each([
    ["2026-10-08T04:59:00Z", "2026-10-07"], // 23:59 CDT
    ["2026-10-08T05:00:00Z", "2026-10-08"], // midnight CDT
    ["2026-01-01T05:59:00Z", "2025-12-31"], // 23:59 CST
    ["2026-01-01T06:00:00Z", "2026-01-01"], // midnight CST
    ["2026-03-09T04:59:00Z", "2026-03-08"], // daylight saving began 8 March
    ["2026-03-09T05:00:00Z", "2026-03-09"],
  ])("today at %s is the Baytown date %s", (instant, expected) => {
    expect(siteIsoDate(new Date(instant))).toBe(expected);
  });

  it("rejects tomorrow in Baytown even when UTC has already reached it", () => {
    const today = siteIsoDate(new Date("2026-10-08T03:00:00Z")); // 22:00 CDT, 7 October
    expect(contactDateError("2026-10-07", today)).toBeNull();
    expect(contactDateError("2026-10-08", today)).toBe("The contact date cannot be in the future.");
  });

  it("labels counts as this month only for the current month", () => {
    expect(countPeriodLabel("2026-10-01", TODAY)).toBe("This month");
    expect(countPeriodLabel("2026-09-30", TODAY)).toBe("September 2026");
  });
});

describe("tally tiles", () => {
  it("lists active supervisors alphabetically, ignoring case, never by volume", () => {
    const tiles = tallyTiles(SUPERVISORS, TODAY);
    expect(tiles.map((t) => t.supervisor.displayName)).toEqual(["avery Jones", "Casey Brown", "Drew Lee"]);
  });

  it("blocks +1 outside a supervisor's effective dates", () => {
    const tiles = tallyTiles(SUPERVISORS, TODAY);
    expect(tiles.find((t) => t.supervisor.id === 4)?.unavailable).toBe("Effective from Sun, Nov 1, 2026");
    expect(tiles.find((t) => t.supervisor.id === 1)?.unavailable).toBeNull();
    const ended = tallyTiles([supervisor(5, "Emery", { effectiveTo: "2026-09-30" })], TODAY);
    expect(ended[0].unavailable).toBe("Effective until Wed, Sep 30, 2026");
  });

  it("offers active supervisors plus the contact's current one when editing", () => {
    expect(editableSupervisors(SUPERVISORS, 3).map((s) => s.id)).toEqual([2, 3, 1, 4]);
    expect(editableSupervisors(SUPERVISORS, 1).map((s) => s.id)).toEqual([2, 1, 4]);
  });
});

describe("request ids", () => {
  it("are distinct v4 UUIDs", () => {
    const a = newRequestId();
    const b = newRequestId();
    expect(a).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(a).not.toBe(b);
  });
});

describe("supervisor form", () => {
  const draft = { ...emptySupervisorDraft(TODAY), displayName: "  Jordan   Lee " };

  it("starts active, eligible, and effective from the first of the month", () => {
    expect(emptySupervisorDraft(TODAY)).toEqual({
      displayName: "",
      active: true,
      participationEligible: true,
      effectiveFrom: "2026-10-01",
      effectiveTo: "",
    });
  });

  it("normalizes the name and sends a blank end date as null", () => {
    expect(normalizeName(" a   b ")).toBe("a b");
    expect(toSupervisorInput(draft)).toEqual({
      displayName: "Jordan Lee",
      active: true,
      participationEligible: true,
      effectiveFrom: "2026-10-01",
      effectiveTo: null,
    });
  });

  it("validates like the API", () => {
    expect(validateSupervisorDraft(draft, SUPERVISORS, null)).toEqual({});
    expect(validateSupervisorDraft({ ...draft, displayName: "   " }, [], null).displayName).toBeDefined();
    expect(validateSupervisorDraft({ ...draft, displayName: "x".repeat(101) }, [], null).displayName).toBeDefined();
    expect(validateSupervisorDraft({ ...draft, displayName: "CASEY  brown" }, SUPERVISORS, null).displayName).toBe(
      "Another supervisor already has this name.",
    );
    expect(validateSupervisorDraft({ ...draft, displayName: "casey brown" }, SUPERVISORS, 1)).toEqual({});
    expect(validateSupervisorDraft({ ...draft, active: false }, [], null).effectiveTo).toBe(
      "An inactive supervisor needs an end date.",
    );
    expect(validateSupervisorDraft({ ...draft, effectiveTo: "2026-09-30" }, [], null).effectiveTo).toBe(
      "The end date cannot be before the start date.",
    );
    expect(validateSupervisorDraft({ ...draft, effectiveFrom: "" }, [], null).effectiveFrom).toBeDefined();
  });
});

const DASHBOARD: ContactDashboardResponse = {
  year: 2026,
  throughMonth: 3,
  contacts: 7,
  months: [
    { month: 1, contacts: 4, participation: { participating: 2, eligible: 3, rate: 2 / 3 } },
    { month: 2, contacts: 0, participation: { participating: 0, eligible: 3, rate: 0 } },
    { month: 3, contacts: 3, participation: { participating: 1, eligible: 0, rate: null } },
    ...Array.from({ length: 9 }, (_, i) => ({ month: i + 4, contacts: null, participation: null })),
  ],
  supervisors: [],
  yearsWithData: [2026],
};

describe("dashboard series", () => {
  it("keeps months that have not started as null, and a started empty month as 0", () => {
    expect(contactsByMonth(DASHBOARD)[0].values.slice(0, 5)).toEqual([4, 0, 3, null, null]);
    const [participating, eligible] = participationByMonth(DASHBOARD);
    expect(participating.values.slice(0, 4)).toEqual([2, 0, 1, null]);
    expect(eligible.values.slice(0, 4)).toEqual([3, 3, 0, null]);
  });

  it("formats participation with numerator and denominator, and no rate without eligible supervisors", () => {
    expect(formatParticipation({ participating: 2, eligible: 3, rate: 2 / 3 })).toBe("2 of 3");
    expect(formatRate(2 / 3)).toBe("67%");
    expect(formatRate(0)).toBe("0%");
    expect(formatRate(null)).toBeNull();
    expect(formatParticipation(null)).toBeNull();
  });

  it("headlines the latest started month", () => {
    expect(headlineMonth(DASHBOARD)?.month).toBe(3);
    expect(headlineMonth({ ...DASHBOARD, throughMonth: 0 })).toBeNull();
  });

  it("accumulates a running total dated to month ends, capped at today", () => {
    const [series] = runningContactTotal(DASHBOARD, "2026-03-15");
    expect(series.points).toEqual([
      ["2026-01-31", 4],
      ["2026-02-28", 4],
      ["2026-03-15", 7],
    ]);
  });

  it("uses whole-number axis ticks for small counts", () => {
    expect(countAxis([{ name: "x", points: [["2026-01-31", 1]] }])).toEqual({
      min: 0,
      max: 1,
      interval: 1,
      labelDigits: 0,
    });
    expect(countAxis([{ name: "x", points: [["2026-01-31", 7]] }])).toMatchObject({ max: 8, interval: 2 });
    expect(countAxis([{ name: "x", points: [["2026-01-31", 144]] }])).toMatchObject({ max: 150, interval: 50 });
    expect(countAxis([])).toMatchObject({ min: 0, max: 1, interval: 1 });
  });
});

describe("error messages", () => {
  it("explains program rules and access", () => {
    const rule = (error: string, extra = {}) => new ApiError(422, "x", { error, message: "m", ...extra });
    expect(describeContactError(rule("supervisor_inactive"))).toMatch(/inactive/);
    expect(describeContactError(rule("contacts_outside_effective_period", { contacts: 2 }))).toBe(
      "2 contacts are recorded outside these dates. Adjust the dates to include them.",
    );
    expect(describeContactError(new ApiError(409, "x", { error: "supervisor_has_contacts" }))).toMatch(
      /set them inactive/i,
    );
    expect(describeContactError(new ApiError(403, "x"))).toBe("You do not have permission for this Safety function.");
    expect(describeContactError(new TypeError("fetch failed"))).toBe("The API could not be reached. Nothing was saved.");
  });
});
