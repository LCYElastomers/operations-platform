/**
 * The Baytown site calendar, as in the API: "today" and the current reporting
 * year are the America/Chicago date, whatever the device's or the server's own
 * time zone. A new reporting year starts at midnight in Baytown on 1 January.
 * The platform has one site; move this into site configuration if it becomes
 * multi-site.
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

/** The site's reporting year at the given instant. */
export function siteYear(instant: Date): number {
  return yearOf(siteIsoDate(instant));
}

/** The site's calendar date now. */
export function siteToday(): string {
  return siteIsoDate(new Date());
}

export function yearOf(isoDate: string): number {
  return Number(isoDate.slice(0, 4));
}

export function monthOf(isoDate: string): number {
  return Number(isoDate.slice(5, 7));
}
