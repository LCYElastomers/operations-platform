// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { initials, toSession } from "./api";
import { SetupPasswordForm } from "./setup-password-form";
import { SignInForm } from "./sign-in-form";

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

type Fixture = { status: number; body?: unknown };
let responses: Record<string, Fixture>;
let requested: { path: string; init?: RequestInit }[];
let container: HTMLDivElement;
let root: Root | null = null;

beforeEach(() => {
  requested = [];
  responses = {};
  container = document.createElement("div");
  document.body.append(container);
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      requested.push({ path, init });
      const response = responses[`${init?.method ?? "GET"} ${path}`] ?? { status: 404, body: {} };
      return Promise.resolve({
        ok: response.status < 400,
        status: response.status,
        json: async () => response.body,
      });
    }),
  );
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  container.remove();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
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
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => root!.render(<QueryClientProvider client={client}>{page}</QueryClientProvider>));
  await settle();
}

function input(label: string): HTMLInputElement {
  const found = [...container.querySelectorAll("label")].find((l) => l.textContent?.startsWith(label));
  if (!found) throw new Error(`No field ${label}`);
  return found.querySelector("input")!;
}

async function type(element: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function submit() {
  await act(async () => {
    container.querySelector("form")!.requestSubmit();
  });
  await settle();
}

const sentBody = (method: string, path: string) =>
  requested.filter((r) => r.init?.method === method && r.path === path).map((r) => JSON.parse(String(r.init!.body)));

describe("sign in", () => {
  it("gives one message for a wrong password or unknown account, and clears the password", async () => {
    responses["POST /api/v1/auth/sign-in"] = { status: 401, body: { detail: { error: "sign_in_failed" } } };
    await render(<SignInForm next="/quality" />);
    await type(input("Email address"), "someone@example.com");
    await type(input("Password"), "not-the-password");
    await submit();

    expect(sentBody("POST", "/api/v1/auth/sign-in")).toEqual([
      { email: "someone@example.com", password: "not-the-password" },
    ]);
    const [request] = requested;
    expect(request.init!.headers).toMatchObject({ "X-Requested-With": "operations-platform" });
    expect(container.querySelector('[role="alert"]')!.textContent).toBe("The email or password is incorrect.");
    expect(input("Password").value).toBe("");
  });
});

describe("password setup link", () => {
  it("takes the token from the address fragment and removes it from the address bar", async () => {
    window.history.replaceState(null, "", "/setup-password#token=fixture-token");
    responses["POST /api/v1/auth/password-link/check"] = {
      status: 200,
      body: { name: "Fixture Person", email: "fixture@example.com" },
    };
    responses["POST /api/v1/auth/password-link"] = { status: 204 };
    await render(<SetupPasswordForm />);

    expect(window.location.hash).toBe("");
    expect(sentBody("POST", "/api/v1/auth/password-link/check")).toEqual([{ token: "fixture-token" }]);
    expect(container.textContent).toContain("For Fixture Person (fixture@example.com).");

    await type(input("New password"), "correct horse battery");
    await type(input("Confirm new password"), "correct horse battery!");
    await submit();
    expect(container.textContent).toContain("The two passwords do not match.");
    expect(sentBody("POST", "/api/v1/auth/password-link")).toEqual([]);

    await type(input("Confirm new password"), "correct horse battery");
    await submit();
    expect(sentBody("POST", "/api/v1/auth/password-link")).toEqual([
      { token: "fixture-token", password: "correct horse battery" },
    ]);
    expect(container.textContent).toContain("Password set");
  });

  it("refuses a link without a token, an expired link and a weak password", async () => {
    window.history.replaceState(null, "", "/setup-password");
    await render(<SetupPasswordForm />);
    expect(container.textContent).toContain("This link cannot be used");
    expect(requested).toEqual([]);
    await act(async () => root?.unmount());

    window.history.replaceState(null, "", "/setup-password#token=used-token");
    responses["POST /api/v1/auth/password-link/check"] = {
      status: 400,
      body: { detail: { error: "link_invalid", message: "This link is invalid or has expired." } },
    };
    await render(<SetupPasswordForm />);
    expect(container.textContent).toContain("This link is invalid or has expired.");
    await act(async () => root?.unmount());

    window.history.replaceState(null, "", "/setup-password#token=fresh-token");
    responses["POST /api/v1/auth/password-link/check"] = {
      status: 200,
      body: { name: "Fixture Person", email: "fixture@example.com" },
    };
    responses["POST /api/v1/auth/password-link"] = {
      status: 422,
      body: { detail: { error: "weak_password", message: "Fixture: choose a longer password.", field: "password" } },
    };
    await render(<SetupPasswordForm />);
    await type(input("New password"), "aaaaaaaaaaaa");
    await type(input("Confirm new password"), "aaaaaaaaaaaa");
    await submit();
    expect(container.textContent).toContain("Fixture: choose a longer password.");
  });
});

describe("session", () => {
  it("keeps only permissions the interface knows", () => {
    const session = toSession({
      user: { id: "u1", name: "Fixture Person", email: "fixture@example.com", image: null, status: "active" },
      roles: [{ code: "VIEWER", name: "Viewer" }],
      permissions: ["app.view", "car.view", "made.up"],
    });
    expect([...session.permissions]).toEqual(["app.view", "car.view"]);
  });

  it("shows initials for the avatar", () => {
    expect(initials("Fixture Person")).toBe("FP");
    expect(initials("  Cher ")).toBe("C");
    expect(initials("")).toBe("?");
  });
});
