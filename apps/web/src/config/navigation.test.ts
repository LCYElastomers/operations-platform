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
  "/safety/incidents/analytics",
  "/safety/observations",
  "/safety/observations/dashboard",
  "/safety/contacts",
  "/safety/contacts/dashboard",
  "/safety/performance/data-entry",
  "/safety/performance/dashboard",
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
    ["/safety/incidents/analytics", "Analytics"],
  ])("nests %s under Safety > Incident & Near Miss", (route, label) => {
    const trail = findNavTrail(navigation, route);
    expect(trail.map((item) => item.label)).toEqual(["Safety", "Incident & Near Miss", label]);
  });

  it("lists Data Entry, Dashboard and Analytics under Incident & Near Miss", () => {
    const safety = moduleItems.find((item) => item.id === "safety");
    const incidents = safety?.children?.find((item) => item.id === "safety-incidents");
    expect(incidents?.children?.map((item) => item.label)).toEqual(["Data Entry", "Dashboard", "Analytics"]);
  });

  it.each([
    ["/safety/observations", "Observations"],
    ["/safety/observations/dashboard", "Dashboard"],
  ])("nests %s under Safety > Safety Observations", (route, label) => {
    const trail = findNavTrail(navigation, route);
    expect(trail.map((item) => item.label)).toEqual(["Safety", "Safety Observations", label]);
  });

  it.each([
    ["/safety/contacts", "Contacts"],
    ["/safety/contacts/dashboard", "Dashboard"],
  ])("nests %s under Safety > Supervisor Safety Contacts", (route, label) => {
    const trail = findNavTrail(navigation, route);
    expect(trail.map((item) => item.label)).toEqual(["Safety", "Supervisor Safety Contacts", label]);
  });

  it.each([
    ["/safety/performance/data-entry", "Data Entry"],
    ["/safety/performance/dashboard", "Dashboard"],
  ])("nests %s under Safety > Safety Performance", (route, label) => {
    const trail = findNavTrail(navigation, route);
    expect(trail.map((item) => item.label)).toEqual(["Safety", "Safety Performance", label]);
  });

  it("lists the Safety areas in order", () => {
    const safety = moduleItems.find((item) => item.id === "safety");
    expect(safety?.children?.map((item) => item.label)).toEqual([
      "Overview",
      "Incident & Near Miss",
      "Safety Observations",
      "Supervisor Safety Contacts",
      "Safety Performance",
    ]);
  });

  it("marks only the Contacts page active on its dashboard", () => {
    expect(findNavTrail(navigation, "/safety/contacts/dashboard").at(-1)?.id).toBe(
      "safety-contacts-dashboard",
    );
    expect(findNavTrail(navigation, "/safety/contacts").at(-1)?.id).toBe("safety-contacts-entry");
  });

  it("marks only the Observations page active on its dashboard", () => {
    expect(findNavTrail(navigation, "/safety/observations/dashboard").at(-1)?.id).toBe(
      "safety-observations-dashboard",
    );
    expect(findNavTrail(navigation, "/safety/observations").at(-1)?.id).toBe(
      "safety-observations-entry",
    );
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
