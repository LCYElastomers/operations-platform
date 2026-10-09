import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { accountNavigation, navigation } from "@/config/navigation";

import {
  canOpen,
  filterNavigation,
  findNavItemByHref,
  findNavTrail,
  type NavItem,
  type NavSection,
} from "./navigation";
import { meets, PERMISSIONS, type Permission } from "./permissions";

const hrefs = (sections: NavSection[]): string[] => {
  const walk = (items: NavItem[]): string[] =>
    items.flatMap((item) => [...(item.href ? [item.href] : []), ...walk(item.children ?? [])]);
  return sections.flatMap((section) => walk(section.items));
};

const granted = (...permissions: Permission[]) => new Set<Permission>(permissions);

describe("permission catalog", () => {
  it("matches the API's catalog exactly", () => {
    const source = readFileSync(
      fileURLToPath(new URL("../../../api/app/core/permissions.py", import.meta.url)),
      "utf8",
    );
    const api = [...source.matchAll(/^\s+[A-Z_]+ = "([A-Za-z.]+)"$/gm)].map((match) => match[1]);
    expect(api.length).toBeGreaterThan(0);
    expect([...PERMISSIONS]).toEqual(api);
  });

  it("needs every permission in all and one in any", () => {
    expect(meets(granted("car.view"), { all: ["car.view", "car.create"] })).toBe(false);
    expect(meets(granted("car.view", "car.create"), { all: ["car.view", "car.create"] })).toBe(true);
    expect(meets(granted("car.view"), { any: ["car.view", "qualityCost.view"] })).toBe(true);
    expect(meets(granted(), { any: ["car.view"] })).toBe(false);
    expect(meets(granted(), undefined)).toBe(true);
  });
});

describe("navigation by permission", () => {
  it("shows nothing to a user without app.view", () => {
    expect(filterNavigation(navigation, granted())).toEqual([]);
  });

  it("shows a CAR-only user the CAR register but not dashboards, Quality Cost, Safety or administration", () => {
    const visible = hrefs(filterNavigation(navigation, granted("app.view", "quality.view", "car.view")));
    expect(visible).toContain("/quality/cars/register");
    expect(visible).not.toContain("/quality/cars");
    expect(visible).not.toContain("/quality/cars/new");
    expect(visible).not.toContain("/quality/cost/register");
    expect(visible.some((href) => href.startsWith("/safety"))).toBe(false);
    expect(visible.some((href) => href.startsWith("/admin"))).toBe(false);
  });

  it("drops a group with nothing left in it", () => {
    const sections = filterNavigation(navigation, granted("app.view", "safety.view"));
    const safety = sections.flatMap((s) => s.items).find((item) => item.id === "safety");
    expect(safety?.children?.every((child) => child.href || (child.children?.length ?? 0) > 0)).toBe(true);
    expect(hrefs(sections)).not.toContain("/safety/incidents/data-entry");
  });

  it("shows administration only with users.view or roles.view", () => {
    expect(hrefs(filterNavigation(navigation, granted("app.view", "users.view")))).toContain("/admin/users");
    expect(hrefs(filterNavigation(navigation, granted("app.view", "users.view")))).not.toContain("/admin/roles");
    expect(hrefs(filterNavigation(navigation, granted("app.view", "roles.view")))).toContain("/admin/roles");
  });

  it("gives every page a requirement, so none is open to everyone by accident", () => {
    const open = hrefs(navigation).filter((href) =>
      findNavTrail(navigation, href).every((item) => !item.requires),
    );
    expect(open).toEqual([]);
    expect(findNavItemByHref(accountNavigation, "/profile")?.requires).toEqual({ all: ["app.view"] });
  });

  it("refuses to open a page whose trail the user does not meet", () => {
    const viewer = granted("app.view", "quality.view", "car.view");
    expect(canOpen(navigation, "/quality/cars/register/9", viewer)).toBe(true);
    expect(canOpen(navigation, "/quality/cars/new", viewer)).toBe(false);
    expect(canOpen(navigation, "/admin/users", viewer)).toBe(false);
    expect(canOpen(navigation, "/admin/users", granted("app.view", "users.view"))).toBe(true);
  });
});
