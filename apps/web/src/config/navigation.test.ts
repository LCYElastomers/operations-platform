import { describe, expect, it } from "vitest";

import { findNavTrail } from "@/lib/navigation";

import { getNavItem, moduleItems, navigation } from "./navigation";

const requiredRoutes = [
  "/",
  "/quality",
  "/quality/raw-materials/moisture",
  "/mechanical-integrity",
  "/safety",
  "/safety/incidents/data-entry",
  "/safety/incidents/dashboard",
  "/environmental",
  "/procurement",
  "/sales",
  "/system/data-sources",
  "/system/sync",
  "/system/audit",
];

describe("navigation config", () => {
  it.each(requiredRoutes)("registers %s", (route) => {
    expect(getNavItem(route).href).toBe(route);
  });

  it("nests Moisture Analysis under Quality > Raw Materials", () => {
    const trail = findNavTrail(navigation, "/quality/raw-materials/moisture");
    expect(trail.map((item) => item.label)).toEqual([
      "Quality",
      "Raw Materials",
      "Moisture Analysis",
    ]);
  });

  it.each([
    ["/safety/incidents/data-entry", "Data Entry"],
    ["/safety/incidents/dashboard", "Dashboard"],
  ])("nests %s under Safety > Incident & Near Miss", (route, label) => {
    const trail = findNavTrail(navigation, route);
    expect(trail.map((item) => item.label)).toEqual(["Safety", "Incident & Near Miss", label]);
  });

  it("does not mark Safety Overview active on Safety function pages", () => {
    const trail = findNavTrail(navigation, "/safety");
    expect(trail.map((item) => item.id)).toEqual(["safety", "safety-overview"]);
    expect(findNavTrail(navigation, "/safety/incidents/dashboard").at(-1)?.id).toBe(
      "safety-incidents-dashboard",
    );
  });

  it("keeps Safety a top-level module alongside Quality", () => {
    expect(moduleItems.map((item) => item.id)).toContain("safety");
  });

  it("keeps Quality and Mechanical Integrity as top-level modules", () => {
    const ids = moduleItems.map((item) => item.id);
    expect(ids).toContain("quality");
    expect(ids).toContain("mechanical-integrity");
  });

  it("uses unique ids", () => {
    const ids: string[] = [];
    const collect = (items: typeof moduleItems) =>
      items.forEach((item) => {
        ids.push(item.id);
        if (item.children) collect(item.children);
      });
    navigation.forEach((section) => collect(section.items));
    expect(new Set(ids).size).toBe(ids.length);
  });
});
