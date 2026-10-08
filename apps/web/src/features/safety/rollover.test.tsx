// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, type ReactElement, type ReactNode } from "react";
import { createRoot, hydrateRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup, renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ContactDashboard } from "./contacts/contact-dashboard";
import { FIRST_CONTACT_YEAR } from "./contacts/contact-data";
import { ContactsPage } from "./contacts/contacts-page";
import { emptyAnalyticsExtras } from "./incidents/analytics.fixture";
import type { AnalyticsSeries, IncidentAnalyticsResponse } from "./incidents/api";
import { FIRST_REPORTING_YEAR } from "./incidents/grid";
import { IncidentDashboard } from "./incidents/incident-dashboard";
import { IncidentDataEntry } from "./incidents/incident-data-entry";
import { ReportingYearSelect } from "./incidents/reporting-year-select";
import { ObservationDashboard } from "./observations/observation-dashboard";
import { FIRST_OBSERVATION_YEAR } from "./observations/observation-data";
import { ObservationsPage } from "./observations/observations-page";
import { PerformanceDashboard } from "./performance/performance-dashboard";
import { PerformanceDataEntry } from "./performance/performance-data-entry";
import { siteIsoDate } from "./site-calendar";
import { useAutomaticValue } from "./use-site-calendar";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/components/common/bar-chart", async (original) => ({
  ...(await original<object>()),
  BarChart: () => null,
}));
vi.mock("@/components/common/trend-chart", async (original) => ({
  ...(await original<object>()),
  TrendChart: () => null,
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Baytown is UTC-6 in winter.
const LAST_MINUTE_OF_2026 = "2027-01-01T05:59:00Z"; // 23:59 CST, 31 December 2026
const LAST_SECOND_OF_2026 = "2027-01-01T05:59:59Z";
const LAST_MINUTE_OF_2027 = "2028-01-01T05:59:00Z"; // 23:59 CST, 31 December 2027
const MINUTE = 60_000;
const DAY = 24 * 60 * MINUTE;

type Page = (siteToday: string) => ReactElement;

const YEAR_PAGES: [string, Page][] = [
  ["Incident & Near Miss Data Entry", (today) => <IncidentDataEntry title="Data Entry" siteToday={today} />],
  ["Incident & Near Miss Dashboard", (today) => <IncidentDashboard title="Dashboard" siteToday={today} />],
  ["Safety Observations", (today) => <ObservationsPage title="Observations" siteToday={today} />],
  ["Safety Observations Dashboard", (today) => <ObservationDashboard title="Dashboard" siteToday={today} />],
  ["Supervisor Safety Contacts Dashboard", (today) => <ContactDashboard title="Dashboard" siteToday={today} />],
  ["Safety Performance Data Entry", (today) => <PerformanceDataEntry title="Data Entry" siteToday={today} />],
  ["Safety Performance Dashboard", (today) => <PerformanceDashboard title="Dashboard" siteToday={today} />],
];

const ALL_PAGES: [string, Page][] = [
  ...YEAR_PAGES,
  ["Supervisor Safety Contacts", (today) => <ContactsPage title="Contacts" siteToday={today} />],
];

// API --------------------------------------------------------------------------------

type Responder = (url: URL) => unknown;
let requested: string[] = [];

/** Requests the responder does not answer stay pending: the page shows its loading state. */
function stubApi(respond: Responder = () => undefined) {
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) => {
      requested.push(path);
      const body = respond(new URL(path, "http://baytown.test"));
      if (body === undefined) return new Promise(() => {});
      return Promise.resolve({ ok: true, status: 200, json: async () => body });
    }),
  );
}

function requestedYears(): number[] {
  return requested.flatMap((path) => {
    const year = new URL(path, "http://baytown.test").searchParams.get("year");
    return year ? [Number(year)] : [];
  });
}

const CATEGORIES = { categories: [{ id: 1, code: "housekeeping", name: "Housekeeping" }], canEdit: true };

/** Test fixture: Incident Analytics for January of a year with nothing reported. */
function emptyIncidentYear(year: number): IncidentAnalyticsResponse {
  const empty = (section: string, code: string): AnalyticsSeries => ({
    section,
    code,
    name: code,
    values: [null],
    total: null,
    monthsReported: 0,
    unreportedMonths: [1],
    complete: false,
  });
  const keys = ["incidents", "near_misses", "lopc", "psif", "pit", "combined_damage"] as const;
  return {
    year,
    throughMonth: 1,
    latestMonth: 1,
    availableYears: [year, 2026],
    kpis: keys.map((key) => ({ key, value: null, monthsReported: 0, throughMonth: 1, complete: false, parts: [] })),
    incidents: empty("incident_near_miss_totals", "incident"),
    nearMisses: empty("incident_near_miss_totals", "near_miss"),
    classifications: [],
    lopc: empty("lopc", "lopc"),
    psif: empty("psif", "psif"),
    pit: empty("incident_classification", "pit_accident"),
    propertyDamage: empty("incident_classification", "property_damage"),
    equipmentDamage: empty("incident_classification", "equipment_damage_failure"),
    combinedDamage: empty("incident_classification", "property_damage+equipment_damage_failure"),
    ...emptyAnalyticsExtras(year, 1),
  };
}

// Rendering --------------------------------------------------------------------------

let root: Root | null = null;
let container: HTMLDivElement;
let queryClient: QueryClient;
const originalZone = process.env.TZ;

function withQueries(ui: ReactNode) {
  return <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>;
}

/** Fixes the clock (and optionally the browser's own time zone) for the test. */
function at(instant: string, browserZone = "UTC") {
  process.env.TZ = browserZone;
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
  vi.setSystemTime(new Date(instant));
}

/** The page as the server would render it for a request at the current instant. */
async function render(page: Page) {
  root = createRoot(container);
  await act(async () => root!.render(withQueries(page(siteIsoDate(new Date())))));
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function wait(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
  await settle();
}

function select(label: string): HTMLSelectElement {
  const found = [...container.querySelectorAll("label")].find(
    (element) => element.querySelector("span")?.textContent === label,
  );
  const control = found?.querySelector("select");
  if (!control) throw new Error(`No "${label}" select`);
  return control;
}

const yearSelect = () => select("Reporting year");
const options = (control: HTMLSelectElement) => [...control.options].map((option) => Number(option.value));

async function choose(control: HTMLSelectElement, value: number) {
  await act(async () => {
    control.value = String(value);
    control.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function button(text: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find((element) => element.textContent?.trim() === text);
}

beforeEach(() => {
  requested = [];
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  container = document.createElement("div");
  document.body.append(container);
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  stubApi();
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  container.remove();
  queryClient.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  process.env.TZ = originalZone;
});

// Default year -----------------------------------------------------------------------

describe.each(YEAR_PAGES)("%s", (_name, page) => {
  it.each([
    // Browser zone, instant, the Baytown year that must be the default.
    ["America/Los_Angeles", "2027-01-01T06:30:00Z", 2027], // 00:30 CST; 22:30 on 31 December in LA
    ["UTC", LAST_SECOND_OF_2026, 2026], // already 2027 in UTC
    ["Asia/Tokyo", "2026-12-31T21:00:00Z", 2026], // 15:00 CST; already 2027 in Tokyo
    ["America/Chicago", "2027-01-01T06:00:00Z", 2027],
  ])("a browser in %s at %s defaults to the Baytown year %s", async (zone, instant, year) => {
    at(instant, zone);
    await render(page);

    expect(Number(yearSelect().value)).toBe(year);
    expect(options(yearSelect())).toContain(year);
    expect(new Set(requestedYears())).toEqual(new Set([year]));
  });

  it("offers and selects the new year at Baytown midnight while untouched, with no records", async () => {
    at(LAST_MINUTE_OF_2026);
    await render(page);
    expect(Number(yearSelect().value)).toBe(2026);
    expect(options(yearSelect())).not.toContain(2027);

    await wait(MINUTE);
    expect(Number(yearSelect().value)).toBe(2027);
    expect(options(yearSelect())).toContain(2027);
    expect(requestedYears()).toContain(2027);
  });

  it("keeps a year the user chose across midnight", async () => {
    at(LAST_MINUTE_OF_2027);
    await render(page);
    expect(Number(yearSelect().value)).toBe(2027);

    await choose(yearSelect(), 2026);
    await wait(2 * MINUTE);

    expect(Number(yearSelect().value)).toBe(2026);
    expect(options(yearSelect())).toContain(2028);
  });

  it("keeps a chosen current year when the year changes", async () => {
    at(LAST_MINUTE_OF_2027);
    await render(page);
    await choose(yearSelect(), 2026);
    await choose(yearSelect(), 2027);

    await wait(2 * MINUTE);

    expect(Number(yearSelect().value)).toBe(2027);
  });
});

describe("module year floors", () => {
  it.each([
    ["Incident & Near Miss Dashboard", (t: string) => <IncidentDashboard title="D" siteToday={t} />, [2026]],
    [
      "Safety Observations Dashboard",
      (t: string) => <ObservationDashboard title="D" siteToday={t} />,
      [2026, 2025, 2024, 2023, 2022],
    ],
    [
      "Supervisor Safety Contacts Dashboard",
      (t: string) => <ContactDashboard title="D" siteToday={t} />,
      [2026, 2025, 2024, 2023, 2022],
    ],
    [
      "Safety Performance Dashboard",
      (t: string) => <PerformanceDashboard title="D" siteToday={t} />,
      [2026, 2025, 2024, 2023, 2022],
    ],
  ])("%s offers %j on 31 December 2026", async (_name, page, expected) => {
    at(LAST_MINUTE_OF_2026);
    await render(page);
    expect(options(yearSelect())).toEqual(expected);
  });

  const offered = (firstYear: number) =>
    renderToStaticMarkup(
      <ReportingYearSelect
        year={2027}
        onChange={() => {}}
        currentYear={2027}
        firstYear={firstYear}
        yearsWithData={[2019, 2026]}
      />,
    );

  it("lets Observations and Contacts offer a pre-2026 year the API returns", () => {
    expect(offered(FIRST_OBSERVATION_YEAR)).toContain('value="2019"');
    expect(offered(FIRST_CONTACT_YEAR)).toContain('value="2019"');
  });

  it("keeps Incident & Near Miss at 2026 and later", () => {
    expect(offered(FIRST_REPORTING_YEAR)).not.toContain('value="2019"');
    expect(offered(FIRST_REPORTING_YEAR)).not.toContain('value="2025"');
  });
});

// Long-open pages --------------------------------------------------------------------

describe("Supervisor Safety Contacts date", () => {
  const page: Page = (today) => <ContactsPage title="Contacts" siteToday={today} />;
  const dateInput = () => container.querySelector<HTMLInputElement>('input[type="date"]')!;

  it("follows the Baytown date while untouched", async () => {
    at(LAST_MINUTE_OF_2026);
    await render(page);
    expect(dateInput().value).toBe("2026-12-31");
    expect(dateInput().max).toBe("2026-12-31");
    expect(button("Use today")).toBeUndefined();

    await wait(MINUTE);

    expect(dateInput().value).toBe("2027-01-01");
    expect(dateInput().max).toBe("2027-01-01");
    expect(requested).toContain("/api/v1/safety/contacts/summary?year=2027&month=1");
  });

  it("keeps a date the user entered, and Use today follows the site date again", async () => {
    at(LAST_MINUTE_OF_2026);
    await render(page);
    await type(dateInput(), "2026-12-30");
    expect(button("Use today")).toBeDefined();

    await wait(MINUTE);
    expect(dateInput().value).toBe("2026-12-30");
    expect(dateInput().max).toBe("2027-01-01");

    await act(async () => button("Use today")!.click());
    expect(dateInput().value).toBe("2027-01-01");
    expect(button("Use today")).toBeUndefined();

    await wait(DAY);
    expect(dateInput().value).toBe("2027-01-02");
  });
});

describe("Safety Observations period and draft date", () => {
  const page: Page = (today) => <ObservationsPage title="Observations" siteToday={today} />;
  const dateInput = () => container.querySelector<HTMLInputElement>('input[type="date"]')!;
  const areaInput = () => container.querySelector<HTMLInputElement>('input[type="text"]')!;

  beforeEach(() => stubApi((url) => (url.pathname.endsWith("/categories") ? CATEGORIES : undefined)));

  it("moves an untouched period and draft date to the new day without clearing the form", async () => {
    at(LAST_MINUTE_OF_2026);
    await render(page);
    await settle();
    await type(areaInput(), "Tank farm");
    expect(dateInput().value).toBe("2026-12-31");
    expect(Number(yearSelect().value)).toBe(2026);
    expect(Number(select("Month").value)).toBe(12);

    await wait(MINUTE);

    expect(dateInput().value).toBe("2027-01-01");
    expect(Number(yearSelect().value)).toBe(2027);
    expect(Number(select("Month").value)).toBe(1);
    expect(areaInput().value).toBe("Tank farm");
    expect(requested).toContain("/api/v1/safety/observations/summary?year=2027&month=1");
  });

  it("keeps a month and a date the user chose", async () => {
    at(LAST_MINUTE_OF_2026);
    await render(page);
    await settle();
    await choose(select("Month"), 11);
    await type(dateInput(), "2026-12-30");

    await wait(MINUTE);

    expect(Number(yearSelect().value)).toBe(2026);
    expect(Number(select("Month").value)).toBe(11);
    expect(dateInput().value).toBe("2026-12-30");
  });
});

describe("Incident & Near Miss Dashboard through month", () => {
  const page: Page = (today) => <IncidentDashboard title="Dashboard" siteToday={today} />;

  it("moves an untouched period to January of the new year at Baytown midnight", async () => {
    at(LAST_MINUTE_OF_2026);
    await render(page);
    expect(Number(select("Through month").value)).toBe(12);

    await wait(MINUTE);

    expect(Number(yearSelect().value)).toBe(2027);
    expect(Number(select("Through month").value)).toBe(1);
    expect(requested.at(-1)).toBe("/api/v1/safety/incidents/analytics?year=2027");
  });

  it("keeps a chosen year and through month across midnight", async () => {
    at(LAST_MINUTE_OF_2026);
    await render(page);
    await choose(yearSelect(), 2026);
    await choose(select("Through month"), 9);

    await wait(MINUTE);

    expect(Number(yearSelect().value)).toBe(2026);
    expect(Number(select("Through month").value)).toBe(9);
    expect(options(yearSelect())).toContain(2027);
    expect(requested.at(-1)).toBe("/api/v1/safety/incidents/analytics?year=2026&through=9");
  });
});

// Empty new year ---------------------------------------------------------------------

describe("an empty 2027", () => {
  it("shows the Incident & Near Miss dashboard as not yet reported, not as 2026 or zero", async () => {
    stubApi((url) =>
      url.pathname === "/api/v1/safety/incidents/analytics"
        ? emptyIncidentYear(Number(url.searchParams.get("year")))
        : undefined,
    );
    at("2027-01-01T06:01:00Z");
    await render((today) => <IncidentDashboard title="Dashboard" siteToday={today} />);
    await settle();

    expect(Number(yearSelect().value)).toBe(2027);
    expect(Number(select("Through month").value)).toBe(1);
    expect(container.textContent).toContain("No months have been reported for Jan 2027.");
    expect(container.textContent).toContain("No months reported, Jan 2027");
    expect(container.textContent).not.toContain("2026 ·");
    expect(requestedYears()).toEqual([2027]);
  });
});

// Holding a default while work is unsaved ------------------------------------------

describe("useAutomaticValue", () => {
  let latest: ReturnType<typeof useAutomaticValue<number>>;

  function Probe({ automatic, hold }: { automatic: number; hold: boolean }) {
    latest = useAutomaticValue(automatic, { hold });
    return null;
  }

  async function show(automatic: number, hold = false) {
    await act(async () => root!.render(<Probe automatic={automatic} hold={hold} />));
  }

  beforeEach(() => {
    root = createRoot(container);
  });

  it("follows until chosen, then keeps the choice until follow()", async () => {
    await show(2026);
    expect(latest).toMatchObject({ value: 2026, isAutomatic: true });

    await show(2027);
    expect(latest.value).toBe(2027);

    await act(async () => latest.choose(2027));
    await show(2028);
    expect(latest).toMatchObject({ value: 2027, isAutomatic: false });

    await act(async () => latest.follow());
    expect(latest).toMatchObject({ value: 2028, isAutomatic: true });
  });

  it("does not move while held, and catches up afterwards", async () => {
    await show(2026, true);
    await show(2027, true);
    expect(latest.value).toBe(2026);

    await show(2027, false);
    expect(latest.value).toBe(2027);
  });
});

// Hydration --------------------------------------------------------------------------

describe.each(ALL_PAGES)("%s hydration", (_name, page) => {
  async function hydrate(serverToday: string) {
    const errors = vi.spyOn(console, "error");
    const recoverable = vi.fn();
    container.innerHTML = renderToString(withQueries(page(serverToday)));
    await act(async () => {
      root = hydrateRoot(container, withQueries(page(serverToday)), { onRecoverableError: recoverable });
    });
    await settle();
    return { errors, recoverable };
  }

  it("hydrates without a mismatch when the server and browser agree", async () => {
    at(LAST_SECOND_OF_2026, "Asia/Tokyo");
    const { errors, recoverable } = await hydrate("2026-12-31");

    expect(recoverable).not.toHaveBeenCalled();
    expect(errors).not.toHaveBeenCalled();
    const html = container.innerHTML;
    expect(html).not.toContain("2027-01-01");
  });

  it("hydrates the server's date, then moves to the new Baytown day without a mismatch", async () => {
    at("2027-01-01T06:00:01Z", "America/Los_Angeles");
    const { errors, recoverable } = await hydrate("2026-12-31");

    expect(recoverable).not.toHaveBeenCalled();
    expect(errors).not.toHaveBeenCalled();
    const control = container.querySelector<HTMLInputElement>('input[type="date"]');
    if (page === ALL_PAGES.at(-1)![1]) expect(control!.value).toBe("2027-01-01");
    else expect(Number(yearSelect().value)).toBe(2027);
  });
});
