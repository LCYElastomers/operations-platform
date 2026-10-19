// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OverviewPage } from "./overview-page";
import { SettingsPage } from "./settings-page";

vi.mock("@/features/auth/use-session", () => ({
  usePermissions: () => ({
    has: (code: string) =>
      code === "notifications.settings.manage" || code === "notifications.view",
  }),
}));

vi.mock("./use-notifications", () => ({
  useOverview: () => ({
    isPending: false,
    isError: false,
    error: null,
    data: {
      provider: "resend",
      apiKeyConfigured: true,
      deliveryMode: "disabled",
      emailEnabled: false,
      emergencyPause: false,
      pendingOutbox: 0,
      acceptedCount: 0,
      failedCount: 0,
      warnings: ["Email delivery is disabled."],
      recentDeliveries: [],
    },
  }),
  useNotificationSettings: () => ({
    isPending: false,
    isError: false,
    error: null,
    data: {
      provider: "resend",
      apiKeyConfigured: true,
      emailEnabled: false,
      deliveryMode: "disabled",
      emailFromAddress: "noreply@example.com",
      emailFromName: "Ops",
      emailReplyTo: null,
      emailRedirectTo: null,
      emergencyPause: false,
    },
  }),
  useNotificationsMutation: () => ({
    isPending: false,
    mutate: vi.fn(),
  }),
}));

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root | null = null;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  container.remove();
});

function renderPage(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  root = createRoot(container);
  act(() => {
    root!.render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  });
}

describe("Email Management UI", () => {
  it("renders overview provider status and warnings", () => {
    renderPage(<OverviewPage title="Overview" description="Status" />);
    expect(container.textContent).toContain("Overview");
    expect(container.textContent).toContain("resend");
    expect(container.textContent).toContain("Email delivery is disabled.");
    expect(container.textContent).toContain("No deliveries yet");
  });

  it("shows env-controlled settings without a secret API key field", () => {
    renderPage(<SettingsPage title="Settings" description="Config" />);
    expect(container.textContent).toContain("Environment configuration");
    expect(container.textContent).toContain("noreply@example.com");
    expect(container.querySelector('input[type="password"]')).toBeNull();
    expect(container.textContent).toContain("Pause all shared email delivery");
  });
});
