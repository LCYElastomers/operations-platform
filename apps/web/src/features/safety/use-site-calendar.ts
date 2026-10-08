import { useState, useSyncExternalStore } from "react";

import { siteToday } from "./site-calendar";

/** How often an open page checks whether the Baytown date has changed. */
export const SITE_DAY_REFRESH_MS = 60_000;

function subscribe(onChange: () => void) {
  const timer = setInterval(onChange, SITE_DAY_REFRESH_MS);
  // Timers are throttled while a tablet sleeps; check again as soon as it wakes.
  document.addEventListener("visibilitychange", onChange);
  return () => {
    clearInterval(timer);
    document.removeEventListener("visibilitychange", onChange);
  };
}

/**
 * Today's Baytown date (YYYY-MM-DD), kept current while the page stays open.
 * `serverToday` is the date the server rendered with; it is used for
 * hydration so the HTML and the first client render agree.
 */
export function useSiteToday(serverToday: string): string {
  return useSyncExternalStore(subscribe, siteToday, () => serverToday);
}

export type AutomaticValue<T> = {
  value: T;
  /** True until the user chooses a value, and again after `follow()`. */
  isAutomatic: boolean;
  choose: (value: T) => void;
  follow: () => void;
};

/**
 * A default that follows `automatic` (e.g. the current year) until the user
 * chooses a value; their choice is then kept until `follow()` is called.
 * While `hold` is true an automatic value stays where it is, so unsaved work
 * is never moved to another period; it catches up once `hold` is false.
 * `automatic` is compared with Object.is, so keep object values stable.
 * `initial`, when given, starts as the user's choice (e.g. from a link).
 */
export function useAutomaticValue<T>(
  automatic: T,
  { hold = false, initial }: { hold?: boolean; initial?: T } = {},
): AutomaticValue<T> {
  const [chosen, setChosen] = useState<{ value: T } | null>(initial === undefined ? null : { value: initial });
  const [shown, setShown] = useState(automatic);
  if (!hold && !Object.is(shown, automatic)) setShown(automatic);

  return {
    value: chosen ? chosen.value : hold ? shown : automatic,
    isAutomatic: chosen === null,
    choose: (value) => setChosen({ value }),
    follow: () => setChosen(null),
  };
}
