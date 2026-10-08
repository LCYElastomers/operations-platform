import type { ComponentType } from "react";

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
