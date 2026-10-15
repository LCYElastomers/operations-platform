// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ActionPage } from "./action-page";
import {
  actionsFromParams,
  actionsHref,
  EMPTY_REGISTER_QUERY,
  registerExportFilters,
  registerFromParams,
  registerHref,
  type Abilities,
  type Action,
  type ActionDetail,
  type Dashboard,
  type PsmOptions,
  type RecommendationRow,
} from "./api";
import { CommandCenter } from "./command-center";
import { RiskBadge } from "./psm-shared";
import { RegisterPage } from "./register-page";

vi.mock("@/components/common/bar-chart", () => ({
  BarChart: ({ title }: { title: string }) => <div data-chart={title} />,
}));

const router = { push: vi.fn(), replace: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/safety/psm" }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const BASE = "/api/v1/safety/psm";

/** Test fixture: a user who may only view. */
const VIEW_ONLY: Abilities = {
  editRecommendation: false,
  decideDisposition: false,
  manageActions: false,
  requestClosure: false,
  verifyClosure: false,
  reopen: false,
  admin: false,
  manageStudies: false,
  importData: false,
  export: false,
};

/** Test fixture, not production data. */
const OPTIONS: PsmOptions = {
  studies: [{ id: 4, name: "Fixture PHA study", active: true }],
  studyTypes: [{ id: 1, name: "PHA", active: true }],
  areas: [],
  departments: [{ id: 2, name: "Fixture Operations", active: true }],
  processNodes: [],
  equipment: [],
  owners: [],
  elements: [],
  dispositions: [],
  actionStatuses: [],
  risks: [],
  evidenceTypes: [{ code: "other", label: "Other" }],
  abilities: VIEW_ONLY,
};

/** Test fixture dashboard. */
const DASHBOARD: Dashboard = {
  scopeStudyId: null,
  today: "2003-03-15",
  kpis: {
    total: 3,
    pending: 1,
    accepted: 2,
    rejected: 0,
    notStarted: 1,
    inProgress: 1,
    pendingVerification: 0,
    closed: 0,
    overdue: 1,
    needsScheduling: 0,
    closurePct: 0,
    actions: 2,
  },
  lifecycle: [
    { code: "identified", label: "Identified", definition: "Every recommendation in scope.", count: 3 },
    { code: "reviewed", label: "Reviewed", definition: "A disposition has been decided.", count: 2 },
  ],
  rejected: { code: "rejected", label: "Rejected", definition: "Rejected after review.", count: 0 },
  scenarioRisks: { high: 0, medium: 4, low: 1 },
  governingRisks: { high: 0, medium: 2, low: 1 },
  matrix: { high: { no_action: 0 }, medium: { no_action: 1 }, low: { no_action: 0 } },
  matrixColumns: [{ code: "no_action", label: "No Action / Pending Disposition" }],
  departments: [],
  aging: [{ code: "0_30", label: "0-30 days", count: 2 }],
  due7: [],
  due30: [],
  overdue: [],
  needsScheduling: 0,
  distribution: [],
  drafts: 0,
};

/** Test fixture register row. */
const ROW: RecommendationRow = {
  id: 7,
  displayId: "FX-01",
  studyId: 4,
  recommendationNumber: 1,
  areaEquipment: "Fixture tank",
  recommendationText: "Fixture recommendation text",
  governingRisk: "medium",
  scenarioCount: 2,
  scenarioRisks: { medium: 1, low: 1 },
  processNodeId: null,
  processNode: null,
  disposition: "pending_review",
  department: null,
  owner: null,
  dueDate: null,
  actionId: null,
  actionNumber: null,
  actionStatus: null,
  dueState: null,
  overdue: false,
  isDraft: false,
  archived: false,
  updatedAt: "2003-03-01T00:00:00Z",
};

/** Test fixture action. */
const ACTION: Action = {
  id: 11,
  actionNumber: "FX-A-01",
  recommendationId: 7,
  recommendationDisplayId: "FX-01",
  studyId: 4,
  title: "Fixture action",
  description: null,
  recommendationText: "Fixture recommendation text",
  areaEquipment: "Fixture tank",
  governingRisk: "medium",
  departmentId: null,
  department: null,
  ownerUserId: null,
  ownerName: "Fixture Owner",
  ownerEmail: "owner@example.test",
  dueDate: null,
  status: "not_started",
  dueState: "no_due_date",
  overdue: false,
  ageDays: 3,
  attention: ["missing_department", "missing_due_date"],
  closureSummary: null,
  closureExceptionReason: null,
  closureRequestedAt: null,
  closureRequestedByName: null,
  verifiedAt: null,
  verifiedByName: null,
  closedAt: null,
  returnedAt: null,
  returnReason: null,
  reopenedAt: null,
  reopenReason: null,
  requiresResolution: false,
  archived: false,
  version: 1,
  createdAt: "2003-03-12T00:00:00Z",
  updatedAt: "2003-03-12T00:00:00Z",
};

const ACTION_DETAIL: ActionDetail = {
  action: ACTION,
  updates: [],
  attachments: [],
  notifications: [
    {
      id: 1,
      eventType: "assigned",
      recipientName: "Fixture Owner",
      recipientEmail: "owner@example.test",
      subject: "Fixture assignment notice",
      status: "queued",
      statusDetail: null,
      attempts: 0,
      createdAt: "2003-03-12T00:00:00Z",
      lastAttemptAt: null,
      sentAt: null,
    },
  ],
  mailEnabled: false,
  abilities: VIEW_ONLY,
};

let container: HTMLDivElement;
let root: Root | null = null;
let queryClient: QueryClient;
let responses: Record<string, { status: number; body: unknown }>;

beforeEach(() => {
  window.history.replaceState(null, "", "/safety/psm");
  router.push.mockReset();
  router.replace.mockReset();
  responses = {
    [`GET ${BASE}/options`]: { status: 200, body: OPTIONS },
    [`GET ${BASE}/dashboard`]: { status: 200, body: DASHBOARD },
    [`GET ${BASE}/studies`]: { status: 200, body: [] },
    [`GET ${BASE}/recommendations`]: { status: 200, body: { rows: [ROW], total: 1, page: 1, pageSize: 25 } },
    [`GET ${BASE}/actions/11`]: { status: 200, body: ACTION_DETAIL },
  };
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  container = document.createElement("div");
  document.body.appendChild(container);
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${path.split("?")[0]}`;
      const response = responses[key] ?? { status: 404, body: { detail: { message: `No fixture for ${key}` } } };
      return Promise.resolve({ ok: response.status < 400, status: response.status, json: async () => response.body });
    }),
  );
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  container.remove();
  queryClient.clear();
  vi.unstubAllGlobals();
});

async function settle() {
  for (let i = 0; i < 4; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

async function render(page: React.ReactNode) {
  root = createRoot(container);
  await act(async () => root!.render(<QueryClientProvider client={queryClient}>{page}</QueryClientProvider>));
  await settle();
}

function button(label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll("button")].find((b) => (b.getAttribute("aria-label") ?? b.textContent ?? "").startsWith(label));
  if (!found) throw new Error(`No button ${label}`);
  return found;
}

function viewLink(): HTMLAnchorElement | null {
  return container.querySelector<HTMLAnchorElement>('aside[aria-label="Selection"] a');
}

describe("PSM URL state", () => {
  it("round-trips register filters through the URL", () => {
    const href = registerHref({ studyId: "4", scenarioRisk: "medium", overdue: true });
    const params = new URLSearchParams(href.split("?")[1]);
    expect(registerFromParams(Object.fromEntries(params))).toEqual({ ...EMPTY_REGISTER_QUERY, studyId: "4", scenarioRisk: "medium", overdue: true });
  });

  it("falls back to defaults for malformed values", () => {
    expect(actionsFromParams({ page: "-3", tab: "overdue" })).toMatchObject({ page: 1, tab: "overdue" });
    expect(actionsHref({})).toBe("/safety/psm/actions");
  });

  it("exports with the filters shown, as lists", () => {
    expect(registerExportFilters({ ...EMPTY_REGISTER_QUERY, governingRisk: "high", studyId: "4" })).toMatchObject({
      studyId: 4,
      governingRisk: ["high"],
      disposition: [],
    });
  });
});

describe("RiskBadge", () => {
  it.each([
    ["high", "High"],
    ["medium", "Medium"],
    ["low", "Low"],
  ])("labels %s risk in text, not only color", async (risk, label) => {
    await render(<RiskBadge risk={risk} />);
    expect(container.textContent).toBe(label);
  });

  it("says when there is no rating", async () => {
    await render(<RiskBadge risk={null} />);
    expect(container.textContent).toBe("Not rated");
  });
});

describe("Command Center", () => {
  it("shows figures from the API", async () => {
    await render(<CommandCenter title="PSM Command Center" />);
    expect(container.textContent).toContain("Recommendations");
    expect(button("Medium: 4 scenarios")).toBeTruthy();
    expect(button("Medium: 2 recommendations")).toBeTruthy();
  });

  it("selecting shows context without navigating; View carries the filter", async () => {
    window.history.replaceState(null, "", "/safety/psm?studyId=4");
    await render(<CommandCenter title="PSM Command Center" initialStudyId="4" />);
    expect(viewLink()).toBeNull();
    await act(async () => button("Medium: 4 scenarios").click());
    expect(router.push).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe("/safety/psm");
    const link = viewLink();
    expect(link?.textContent).toContain("View recommendations");
    const url = new URL(link!.getAttribute("href")!, "http://localhost");
    expect(url.pathname).toBe("/safety/psm/pha");
    expect(url.searchParams.get("scenarioRisk")).toBe("medium");
    expect(url.searchParams.get("studyId")).toBe("4");
  });

  it("selecting again clears the selection", async () => {
    await render(<CommandCenter title="PSM Command Center" />);
    await act(async () => button("Medium risk, No Action / Pending Disposition: 1").click());
    expect(new URL(viewLink()!.href).searchParams.get("matrixRisk")).toBe("medium");
    await act(async () => button("Medium risk, No Action / Pending Disposition: 1").click());
    expect(viewLink()).toBeNull();
  });

  it("shows an empty state, not invented figures, when nothing is stored", async () => {
    responses[`GET ${BASE}/dashboard`] = {
      status: 200,
      body: { ...DASHBOARD, kpis: { ...DASHBOARD.kpis, total: 0, closurePct: null, actions: 0 } },
    };
    await render(<CommandCenter title="PSM Command Center" />);
    expect(container.textContent).toContain("No PHA recommendations yet");
    expect(container.textContent).not.toContain("Recommendation lifecycle");
  });
});

describe("PHA register", () => {
  it("selects a row, then opens it only through View", async () => {
    await render(<RegisterPage title="PHA Management" initial={EMPTY_REGISTER_QUERY} />);
    expect(container.textContent).toContain("Fixture recommendation text");
    await act(async () => button("Select FX-01").click());
    expect(router.push).not.toHaveBeenCalled();
    expect(viewLink()?.getAttribute("href")).toBe("/safety/psm/pha/recommendations/7");
  });
});

describe("Action detail", () => {
  it("never reports an email as sent when email is not configured", async () => {
    await render(<ActionPage id={11} />);
    expect(container.textContent).toContain("Email is not configured; not sent.");
    expect(container.textContent).toContain("Not sent (email not configured)");
    expect(container.textContent).not.toMatch(/\bSent\b/);
  });

  it("offers no workflow controls to a view-only user", async () => {
    await render(<ActionPage id={11} />);
    const labels = [...container.querySelectorAll("button")].map((b) => b.textContent ?? "");
    for (const label of ["Request closure", "Verify and close", "Reopen", "Edit assignment", "Start work"]) {
      expect(labels.some((text) => text.includes(label))).toBe(false);
    }
    expect(container.textContent).toContain("No department");
  });
});
