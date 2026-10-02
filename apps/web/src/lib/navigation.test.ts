import { describe, expect, it } from "vitest";

import {
  containsActive,
  findNavItemByHref,
  findNavTrail,
  isNavItemActive,
  type NavSection,
} from "./navigation";

const fixtureSections: NavSection[] = [
  { id: "main", items: [{ id: "home", label: "Home", href: "/", exact: true }] },
  {
    id: "modules",
    items: [
      {
        id: "quality",
        label: "Quality",
        children: [
          { id: "quality-overview", label: "Overview", href: "/quality", exact: true },
          {
            id: "raw",
            label: "Raw Materials",
            children: [
              { id: "moisture", label: "Moisture", href: "/quality/raw-materials/moisture" },
            ],
          },
        ],
      },
      { id: "safety", label: "Safety", href: "/safety" },
    ],
  },
];

const [, modules] = fixtureSections;
const quality = modules.items[0];
const safety = modules.items[1];

describe("isNavItemActive", () => {
  it("matches exact items only on the exact path", () => {
    const home = fixtureSections[0].items[0];
    expect(isNavItemActive(home, "/")).toBe(true);
    expect(isNavItemActive(home, "/safety")).toBe(false);
  });

  it("matches prefix items on nested paths but not on lookalike paths", () => {
    expect(isNavItemActive(safety, "/safety")).toBe(true);
    expect(isNavItemActive(safety, "/safety/incidents")).toBe(true);
    expect(isNavItemActive(safety, "/safety-old")).toBe(false);
  });

  it("never matches groups without an href", () => {
    expect(isNavItemActive(quality, "/quality")).toBe(false);
  });
});

describe("containsActive", () => {
  it("is true for every ancestor of the active item", () => {
    expect(containsActive(quality, "/quality/raw-materials/moisture")).toBe(true);
    expect(containsActive(quality.children![1], "/quality/raw-materials/moisture")).toBe(true);
  });

  it("does not mark the exact Overview child active on deeper routes", () => {
    expect(containsActive(quality.children![0], "/quality/raw-materials/moisture")).toBe(false);
  });
});

describe("findNavTrail", () => {
  it("returns the full path to a nested item", () => {
    const trail = findNavTrail(fixtureSections, "/quality/raw-materials/moisture");
    expect(trail.map((item) => item.id)).toEqual(["quality", "raw", "moisture"]);
  });

  it("returns an empty trail for unknown paths", () => {
    expect(findNavTrail(fixtureSections, "/unknown")).toEqual([]);
  });
});

describe("findNavItemByHref", () => {
  it("finds nested items", () => {
    expect(findNavItemByHref(fixtureSections, "/quality/raw-materials/moisture")?.id).toBe(
      "moisture",
    );
  });
});
