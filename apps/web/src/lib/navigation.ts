import type { ComponentType } from "react";

import { meets, type Permission, type Requirement } from "./permissions";

export type ModuleStatus = "available" | "in-development" | "not-configured";

export type NavItem = {
  id: string;
  label: string;
  /** Items without an href are expandable groups only. */
  href?: string;
  /** Match the pathname exactly instead of treating href as a prefix. */
  exact?: boolean;
  icon?: ComponentType<{ className?: string }>;
  description?: string;
  status?: ModuleStatus;
  /** The page shows development fixture data, labelled as such where it is listed. */
  fixture?: boolean;
  /**
   * Permissions needed to see the item and open its page. Hiding is a
   * convenience only: the API refuses the page's requests on its own.
   */
  requires?: Requirement;
  children?: NavItem[];
};

export type NavSection = {
  id: string;
  label?: string;
  items: NavItem[];
};

export function isNavItemActive(item: NavItem, pathname: string): boolean {
  if (!item.href) return false;
  if (item.exact) return pathname === item.href;
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

export function containsActive(item: NavItem, pathname: string): boolean {
  return (
    isNavItemActive(item, pathname) ||
    (item.children?.some((child) => containsActive(child, pathname)) ?? false)
  );
}

/** Path from a top-level item down to the active item, or [] if none match. */
export function findNavTrail(sections: NavSection[], pathname: string): NavItem[] {
  const walk = (items: NavItem[]): NavItem[] => {
    for (const item of items) {
      if (item.children) {
        const trail = walk(item.children);
        if (trail.length > 0) return [item, ...trail];
      }
      if (isNavItemActive(item, pathname)) return [item];
    }
    return [];
  };

  for (const section of sections) {
    const trail = walk(section.items);
    if (trail.length > 0) return trail;
  }
  return [];
}

/**
 * The navigation a user may use: items whose requirements they meet, and
 * groups with at least one such item left. Sections left empty are dropped.
 */
export function filterNavigation(sections: NavSection[], granted: ReadonlySet<Permission>): NavSection[] {
  const keep = (items: NavItem[]): NavItem[] =>
    items.flatMap((item) => {
      if (!meets(granted, item.requires)) return [];
      if (!item.children) return [item];
      const children = keep(item.children);
      return children.length > 0 ? [{ ...item, children }] : [];
    });
  return sections
    .map((section) => ({ ...section, items: keep(section.items) }))
    .filter((section) => section.items.length > 0);
}

/** The requirements of each page under an item; the item is usable if any one is met. */
export function pageRequirements(item: NavItem): Requirement[] {
  if (!item.children) return [item.requires ?? {}];
  return item.children.flatMap(pageRequirements).map((requirement) => ({
    all: [...(item.requires?.all ?? []), ...(requirement.all ?? [])],
    any: requirement.any,
  }));
}

/** Whether the page at `pathname` is one the user may open, judged by its navigation trail. */
export function canOpen(sections: NavSection[], pathname: string, granted: ReadonlySet<Permission>): boolean {
  return findNavTrail(sections, pathname).every((item) => meets(granted, item.requires));
}

export function findNavItemByHref(sections: NavSection[], href: string): NavItem | undefined {
  const walk = (items: NavItem[]): NavItem | undefined => {
    for (const item of items) {
      if (item.href === href) return item;
      const found = item.children && walk(item.children);
      if (found) return found;
    }
    return undefined;
  };

  for (const section of sections) {
    const found = walk(section.items);
    if (found) return found;
  }
  return undefined;
}
