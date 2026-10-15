// @vitest-environment jsdom
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useUrlState } from "./use-url-state";

const navigation = vi.hoisted(() => ({ search: "" }));

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(navigation.search) }));

const read = (params: URLSearchParams) => params.get("risk") ?? "";
const write = (params: URLSearchParams, value: string) => {
  if (value) params.set("risk", value);
  else params.delete("risk");
};

let root: Root;
let container: HTMLElement;
const probe: { set?: (value: string) => void } = {};

function Probe({ initial }: { initial: string }) {
  const [value, set] = useUrlState(initial, read, write);
  useEffect(() => {
    probe.set = set;
  });
  return <output>{value}</output>;
}

function render(initial = "") {
  act(() => root.render(<Probe initial={initial} />));
}

const shown = () => container.textContent;
const choose = (value: string) => act(() => probe.set!(value));

/** A Next navigation: the address bar and `useSearchParams` both change. */
function navigate(search: string) {
  window.history.pushState(null, "", search ? `/?${search}` : "/");
  navigation.search = search;
  render();
}

/** Next reporting a query late, after the address bar has moved on. */
function lateReport(search: string) {
  navigation.search = search;
  render();
}

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  navigation.search = "";
  window.history.replaceState(null, "", "/");
});

describe("useUrlState", () => {
  it("re-reads the state when a link changes the query of the mounted page", () => {
    window.history.replaceState(null, "", "/?risk=medium");
    navigation.search = "risk=medium";
    render("medium");
    expect(shown()).toBe("medium");

    navigate("");

    expect(shown()).toBe("");
  });

  it("ignores a late report of an earlier write", () => {
    render();
    choose("low");
    choose("high");
    expect(window.location.search).toBe("?risk=high");

    lateReport("risk=low");
    expect(shown()).toBe("high");

    lateReport("risk=high");
    expect(shown()).toBe("high");
  });

  it("follows a link back to a query it wrote earlier", () => {
    render();
    choose("low");
    lateReport("risk=low");

    navigate("");
    expect(shown()).toBe("");

    navigate("risk=low");
    expect(shown()).toBe("low");
  });
});
