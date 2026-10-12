// @vitest-environment jsdom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Toaster } from "@/components/ui/toast";
import type { PeriodConfig, PeriodValue } from "@/lib/period";

import { ExportMenu } from "./export-menu";
import { PeriodFilter } from "./period-filter";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let granted = new Set<string>();
vi.mock("@/features/auth/use-session", () => ({
  usePermissions: () => ({ has: (permission: string) => granted.has(permission) }),
}));

const TODAY = "2026-10-09";
const CONFIG: PeriodConfig = {
  presets: ["all", "this-month", "last-month", "ytd"],
  browse: "year-month",
  custom: true,
  years: [2026, 2025, 2024],
};

let container: HTMLDivElement;
let root: Root | null = null;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  container.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function render(node: React.ReactNode) {
  root = createRoot(container);
  await act(async () => root!.render(node));
}

async function settle() {
  for (let i = 0; i < 4; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

async function click(element: Element) {
  await act(async () => (element as HTMLElement).click());
}

async function change(element: HTMLInputElement | HTMLSelectElement, value: string) {
  await act(async () => {
    const prototype = Object.getPrototypeOf(element) as object;
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(element, value);
    element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
  });
}

const button = (label: string, scope: ParentNode = container) => {
  const found = [...scope.querySelectorAll("button")].find((b) => b.textContent?.trim() === label);
  if (!found) throw new Error(`No button ${label}`);
  return found;
};

const field = <T extends HTMLElement>(label: string) => {
  const found = [...container.querySelectorAll("label")].find((l) => l.textContent?.startsWith(label));
  if (!found) throw new Error(`No field ${label}`);
  return found.querySelector<T>("input, select")!;
};

function Harness({ initial = { mode: "all" } as PeriodValue, onChange }: { initial?: PeriodValue; onChange?: (v: PeriodValue) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <PeriodFilter
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
      today={TODAY}
      config={CONFIG}
      hint="by request date"
    />
  );
}

describe("PeriodFilter", () => {
  const trigger = () => container.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]')!;
  const range = () => container.querySelector('[data-testid="period-range"]')!.textContent;

  it("always shows the chosen period and its dates", async () => {
    await render(<Harness initial={{ mode: "ytd" }} />);
    expect(trigger().textContent).toContain("Year to Date");
    expect(range()).toBe("Jan 1 – Oct 9, 2026 · by request date");
    expect(trigger().getAttribute("aria-expanded")).toBe("false");
  });

  it("applies a quick preset and closes, returning focus to the trigger", async () => {
    const onChange = vi.fn();
    await render(<Harness onChange={onChange} />);
    await click(trigger());
    const dialog = container.querySelector('[role="dialog"]')!;
    expect(trigger().getAttribute("aria-expanded")).toBe("true");
    expect(button("Selected: All dates", dialog).getAttribute("aria-pressed")).toBe("true");
    await click(button("Last Month", dialog));
    expect(onChange).toHaveBeenCalledWith({ mode: "last-month" });
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(trigger());
    expect(range()).toContain("September 2026");
  });

  it("browses a year, or a month of a year", async () => {
    const onChange = vi.fn();
    await render(<Harness onChange={onChange} />);
    await click(trigger());
    await change(field<HTMLSelectElement>("Year"), "2025");
    await click(button("Apply", container.querySelectorAll("section")[1]));
    expect(onChange).toHaveBeenLastCalledWith({ mode: "year", year: 2025 });

    await click(trigger());
    await change(field<HTMLSelectElement>("Year"), "2024");
    await change(field<HTMLSelectElement>("Month"), "2");
    await click(button("Apply", container.querySelectorAll("section")[1]));
    expect(onChange).toHaveBeenLastCalledWith({ mode: "month", year: 2024, month: 2 });
    expect(range()).toContain("Feb 1 – Feb 29, 2024");
  });

  it("validates a custom range before applying it", async () => {
    const onChange = vi.fn();
    await render(<Harness onChange={onChange} />);
    await click(trigger());
    const custom = container.querySelectorAll("section")[2];
    await change(field<HTMLInputElement>("From"), "2026-03-10");
    await change(field<HTMLInputElement>("To"), "2026-03-01");
    expect(custom.querySelector('[role="alert"]')!.textContent).toBe("The To date is before the From date.");
    expect(button("Apply", custom).disabled).toBe(true);
    await change(field<HTMLInputElement>("To"), "2026-04-02");
    await click(button("Apply", custom));
    expect(onChange).toHaveBeenLastCalledWith({ mode: "custom", from: "2026-03-10", to: "2026-04-02" });
  });

  it("closes on Escape without changing the period", async () => {
    const onChange = vi.fn();
    await render(<Harness onChange={onChange} />);
    await click(trigger());
    const dialog = container.querySelector('[role="dialog"]')!;
    await act(async () => {
      dialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("opens as a bottom sheet with a backdrop and close button on small screens", async () => {
    await render(<Harness />);
    await click(trigger());
    const dialog = container.querySelector('[role="dialog"]')!;
    // Fixed to the bottom by default; a popover only from the sm breakpoint.
    expect(dialog.className).toContain("fixed inset-x-0 bottom-0");
    expect(dialog.className).toContain("sm:absolute");
    expect(container.querySelector(".fixed.inset-0.sm\\:hidden")).not.toBeNull();
    await click(dialog.querySelector('button[aria-label="Close"]')!);
    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });
});

describe("ExportMenu", () => {
  const exportButton = () => container.querySelector<HTMLButtonElement>('button[aria-haspopup="menu"]') ?? undefined;
  const context = () => ({ period: { mode: "month" as const, year: 2026, month: 8 }, filters: { status: ["open"], search: "", repeat: false } });

  beforeEach(() => {
    granted = new Set(["car.view", "car.export"]);
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:fixture"), revokeObjectURL: vi.fn() }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  const menu = (
    <>
      <ExportMenu reportKey="car-dashboard" title="CAR Dashboard" requires={["car.view", "car.export"]} context={context} />
      <Toaster />
    </>
  );

  it("is hidden without every required permission", async () => {
    granted = new Set(["car.view"]);
    await render(menu);
    expect(exportButton()).toBeUndefined();
  });

  it("offers PDF and Excel from a keyboard-operable menu", async () => {
    await render(menu);
    await click(exportButton()!);
    const items = [...container.querySelectorAll('[role="menuitem"]')];
    expect(items.map((item) => item.textContent)).toEqual(["PDF report", "Excel workbook"]);
    expect(document.activeElement).toBe(items[0]);
    await act(async () => {
      container.querySelector('[role="menu"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    });
    expect(document.activeElement).toBe(items[1]);
    await act(async () => {
      container.querySelector('[role="menu"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(container.querySelector('[role="menu"]')).toBeNull();
  });

  it("sends the screen's period and filters, shows progress once and confirms the download", async () => {
    let finish: (response: unknown) => void = () => {};
    const fetchMock = vi.fn(() => new Promise((resolve) => (finish = resolve)));
    vi.stubGlobal("fetch", fetchMock);
    await render(menu);
    await click(exportButton()!);
    await click(button("PDF report"));

    expect(exportButton()!.textContent).toContain("Generating PDF…");
    expect(exportButton()!.disabled).toBe(true);
    expect(exportButton()!.getAttribute("aria-busy")).toBe("true");
    await click(exportButton()!);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const [path, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe("/api/v1/reports/car-dashboard/export");
    expect((init.headers as Record<string, string>)["X-Requested-With"]).toBe("operations-platform");
    expect(JSON.parse(String(init.body))).toEqual({
      format: "pdf",
      period: { mode: "month", year: 2026, month: 8 },
      filters: { status: ["open"], repeat: false },
    });

    await act(async () =>
      finish({
        ok: true,
        status: 200,
        headers: new Headers({ "Content-Disposition": 'attachment; filename="Operations-Platform_CAR-Dashboard_2026-08.pdf"' }),
        blob: async () => new Blob(["%PDF"]),
      }),
    );
    await settle();
    expect(exportButton()!.textContent).toContain("Export");
    expect(exportButton()!.disabled).toBe(false);
    const status = container.querySelector('[role="status"]')!;
    expect(status.textContent).toContain("PDF report ready");
    expect(status.textContent).toContain("Operations-Platform_CAR-Dashboard_2026-08.pdf");
  });

  it("explains a failure and stays on the page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 403,
        headers: new Headers(),
        json: async () => ({ detail: { error: "forbidden", message: "Not allowed." } }),
      })),
    );
    await render(menu);
    await click(exportButton()!);
    await click(button("Excel workbook"));
    await settle();
    const alert = container.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain("CAR Dashboard could not be exported");
    expect(alert.textContent).toContain("You do not have permission to export this report.");
    expect(exportButton()!.disabled).toBe(false);
  });
});
