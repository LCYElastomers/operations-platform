import type { BarSeries } from "@/components/common/bar-chart";
import { PALETTE, type TrendSeries, type YAxisRange } from "@/components/common/trend-chart";

import { MONTH_LABELS } from "../incidents/grid";
import { localIsoDate, monthName } from "../observations/observation-data";
import type {
  ContactDashboardResponse,
  Participation,
  Supervisor,
  SupervisorInput,
} from "./api";

/** Same limits as the API and the database. */
export const EARLIEST_DATE = "2000-01-01";
export const MAX_DISPLAY_NAME_LENGTH = 100;

/**
 * "Today" is the Baytown site's calendar date, as in the API, whatever the
 * device's own time zone. The platform has one site; move this into site
 * configuration if it becomes multi-site.
 */
export const SITE_TIME_ZONE = "America/Chicago";

const siteDateParts = new Intl.DateTimeFormat("en-US", {
  timeZone: SITE_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** The site's calendar date (YYYY-MM-DD) at the given instant. */
export function siteIsoDate(instant: Date): string {
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    siteDateParts.formatToParts(instant).find((p) => p.type === type)!.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function isIsoDate(text: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return false;
  const [year, month, day] = text.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day;
}

/** Why a contact date cannot be used, or null if it can. Mirrors the API's rules. */
export function contactDateError(contactDate: string, today: string): string | null {
  if (!contactDate) return "Choose the contact date.";
  if (!isIsoDate(contactDate)) return "Enter a valid date.";
  if (contactDate > today) return "The contact date cannot be in the future.";
  if (contactDate < EARLIEST_DATE) return "The date is too early.";
  return null;
}

/** "Tue, Oct 6, 2026" for a YYYY-MM-DD date, without shifting it through a time zone. */
export function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function periodOf(isoDate: string): { year: number; month: number } {
  const [year, month] = isoDate.split("-").map(Number);
  return { year, month };
}

/** "This month" when the contact date is in the current month, otherwise "September 2026". */
export function countPeriodLabel(contactDate: string, today: string): string {
  if (contactDate.slice(0, 7) === today.slice(0, 7)) return "This month";
  const { year, month } = periodOf(contactDate);
  return `${monthName(month)} ${year}`;
}

/**
 * A random v4 UUID identifying one tap. Uses getRandomValues, which (unlike
 * randomUUID) is also available when the app is served over plain HTTP.
 */
export function newRequestId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function inEffect(supervisor: SupervisorInput, isoDate: string): boolean {
  return (
    supervisor.effectiveFrom <= isoDate &&
    (supervisor.effectiveTo === null || supervisor.effectiveTo >= isoDate)
  );
}

export function byName(a: { displayName: string }, b: { displayName: string }): number {
  return a.displayName.localeCompare(b.displayName, "en", { sensitivity: "base" });
}

export type TallyTile = {
  supervisor: Supervisor;
  /** Why +1 is unavailable on the chosen date, or null. */
  unavailable: string | null;
};

/** Active supervisors, alphabetical (never by volume), with whether +1 applies on the date. */
export function tallyTiles(supervisors: Supervisor[], contactDate: string): TallyTile[] {
  return supervisors
    .filter((s) => s.active)
    .sort(byName)
    .map((supervisor) => ({
      supervisor,
      unavailable:
        supervisor.effectiveFrom > contactDate
          ? `Effective from ${formatDate(supervisor.effectiveFrom)}`
          : supervisor.effectiveTo !== null && supervisor.effectiveTo < contactDate
            ? `Effective until ${formatDate(supervisor.effectiveTo)}`
            : null,
    }));
}

/** Supervisors a contact can be moved to: active ones, plus its current supervisor. */
export function editableSupervisors(supervisors: Supervisor[], currentId: number): Supervisor[] {
  return supervisors.filter((s) => s.active || s.id === currentId).sort(byName);
}

// Supervisor form -----------------------------------------------------------------

export type SupervisorDraft = {
  displayName: string;
  active: boolean;
  participationEligible: boolean;
  effectiveFrom: string;
  effectiveTo: string;
};

export type SupervisorDraftErrors = Partial<Record<keyof SupervisorDraft, string>>;

/** Trimmed, with single inner spaces: the form the API stores. */
export function normalizeName(name: string): string {
  return name.trim().split(/\s+/).filter(Boolean).join(" ");
}

/** New supervisors start active, eligible, and in effect from the first of the current month. */
export function emptySupervisorDraft(today: string): SupervisorDraft {
  return {
    displayName: "",
    active: true,
    participationEligible: true,
    effectiveFrom: `${today.slice(0, 7)}-01`,
    effectiveTo: "",
  };
}

export function draftFromSupervisor(supervisor: Supervisor): SupervisorDraft {
  return {
    displayName: supervisor.displayName,
    active: supervisor.active,
    participationEligible: supervisor.participationEligible,
    effectiveFrom: supervisor.effectiveFrom,
    effectiveTo: supervisor.effectiveTo ?? "",
  };
}

/** Field errors; an empty object means the draft can be saved. Mirrors the API's rules. */
export function validateSupervisorDraft(
  draft: SupervisorDraft,
  others: { id: number; displayName: string }[],
  editingId: number | null,
): SupervisorDraftErrors {
  const errors: SupervisorDraftErrors = {};
  const name = normalizeName(draft.displayName);
  if (!name) errors.displayName = "Enter the supervisor's name.";
  else if (name.length > MAX_DISPLAY_NAME_LENGTH) {
    errors.displayName = `Use at most ${MAX_DISPLAY_NAME_LENGTH} characters.`;
  } else if (
    others.some((s) => s.id !== editingId && s.displayName.toLowerCase() === name.toLowerCase())
  ) {
    errors.displayName = "Another supervisor already has this name.";
  }
  if (!draft.effectiveFrom) errors.effectiveFrom = "Choose the start date.";
  else if (!isIsoDate(draft.effectiveFrom)) errors.effectiveFrom = "Enter a valid date.";
  else if (draft.effectiveFrom < EARLIEST_DATE) errors.effectiveFrom = "The date is too early.";
  if (draft.effectiveTo) {
    if (!isIsoDate(draft.effectiveTo)) errors.effectiveTo = "Enter a valid date.";
    else if (draft.effectiveFrom && draft.effectiveTo < draft.effectiveFrom) {
      errors.effectiveTo = "The end date cannot be before the start date.";
    }
  } else if (!draft.active) {
    errors.effectiveTo = "An inactive supervisor needs an end date.";
  }
  return errors;
}

export function toSupervisorInput(draft: SupervisorDraft): SupervisorInput {
  return {
    displayName: normalizeName(draft.displayName),
    active: draft.active,
    participationEligible: draft.participationEligible,
    effectiveFrom: draft.effectiveFrom,
    effectiveTo: draft.effectiveTo || null,
  };
}

// Dashboard -----------------------------------------------------------------------

export const CONTACTS_COLOR = PALETTE[0];
export const PARTICIPATING_COLOR = PALETTE[2];
export const ELIGIBLE_COLOR = PALETTE[4];

export function formatRate(rate: number | null): string | null {
  return rate === null ? null : `${Math.round(rate * 100)}%`;
}

export function formatParticipation(participation: Participation | null): string | null {
  return participation ? `${participation.participating} of ${participation.eligible}` : null;
}

/** The month the headline figures describe: the latest started month of the year. */
export function headlineMonth(dashboard: ContactDashboardResponse | undefined) {
  if (!dashboard || dashboard.throughMonth === 0) return null;
  return dashboard.months[dashboard.throughMonth - 1] ?? null;
}

/** Contacts per month. Months that have not started are null (no bar), not 0. */
export function contactsByMonth(dashboard: ContactDashboardResponse | undefined): BarSeries[] {
  const months = dashboard?.months ?? [];
  return [
    {
      name: "Contacts",
      color: CONTACTS_COLOR,
      values: MONTH_LABELS.map((_, index) => months[index]?.contacts ?? null),
    },
  ];
}

/** Participating and eligible supervisors per month; months not started are null. */
export function participationByMonth(dashboard: ContactDashboardResponse | undefined): BarSeries[] {
  const months = dashboard?.months ?? [];
  const values = (pick: (p: Participation) => number) =>
    MONTH_LABELS.map((_, index) => {
      const participation = months[index]?.participation;
      return participation ? pick(participation) : null;
    });
  return [
    { name: "Participating", color: PARTICIPATING_COLOR, values: values((p) => p.participating) },
    { name: "Eligible", color: ELIGIBLE_COLOR, values: values((p) => p.eligible) },
  ];
}

/**
 * Cumulative contacts at the end of each started month. The current month's
 * point is dated today, since its count is only through today.
 */
export function runningContactTotal(
  dashboard: ContactDashboardResponse | undefined,
  today: string,
): TrendSeries[] {
  if (!dashboard) return [];
  let total = 0;
  const points: [string, number][] = [];
  for (const { month, contacts } of dashboard.months) {
    if (contacts === null) continue;
    total += contacts;
    const monthEnd = localIsoDate(new Date(dashboard.year, month, 0));
    points.push([monthEnd > today ? today : monthEnd, total]);
  }
  return [{ name: "Contacts (running total)", points }];
}

/** Whole-number ticks from 0, so small counts never show fractional contacts. */
export function countAxis(series: TrendSeries[]): YAxisRange {
  const max = Math.max(0, ...series.flatMap((s) => s.points.map(([, value]) => value ?? 0)));
  const target = Math.max(1, Math.ceil(max / 5));
  const magnitude = 10 ** Math.floor(Math.log10(target));
  const interval = [1, 2, 5, 10].map((step) => step * magnitude).find((step) => step >= target)!;
  return { min: 0, max: Math.max(interval, Math.ceil(max / interval) * interval), interval, labelDigits: 0 };
}
