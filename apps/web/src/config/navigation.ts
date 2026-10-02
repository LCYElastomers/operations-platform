import {
  Database,
  Droplets,
  FlaskConical,
  HardHat,
  Handshake,
  LayoutDashboard,
  Leaf,
  RefreshCw,
  ScrollText,
  Truck,
  Wrench,
} from "lucide-react";

import { findNavItemByHref, type NavItem, type NavSection } from "@/lib/navigation";

export const navigation: NavSection[] = [
  {
    id: "main",
    items: [{ id: "overview", label: "Overview", href: "/", exact: true, icon: LayoutDashboard }],
  },
  {
    id: "modules",
    label: "Modules",
    items: [
      {
        id: "quality",
        label: "Quality",
        icon: FlaskConical,
        status: "in-development",
        description: "Raw material, in-process, and finished product quality analysis.",
        children: [
          { id: "quality-overview", label: "Overview", href: "/quality", exact: true },
          {
            id: "quality-raw-materials",
            label: "Raw Materials",
            children: [
              {
                id: "quality-moisture",
                label: "Moisture Analysis",
                href: "/quality/raw-materials/moisture",
                icon: Droplets,
                status: "in-development",
                description: "Moisture, color, and combined BD of incoming raw materials.",
              },
            ],
          },
        ],
      },
      {
        id: "mechanical-integrity",
        label: "Mechanical Integrity",
        href: "/mechanical-integrity",
        icon: Wrench,
        status: "not-configured",
        description: "Inspection, testing, and preventive maintenance of fixed equipment.",
      },
      {
        id: "safety",
        label: "Safety",
        href: "/safety",
        icon: HardHat,
        status: "not-configured",
        description: "Incidents, observations, and safety performance tracking.",
      },
      {
        id: "environmental",
        label: "Environmental",
        href: "/environmental",
        icon: Leaf,
        status: "not-configured",
        description: "Emissions, permits, and environmental compliance monitoring.",
      },
      {
        id: "procurement",
        label: "Procurement",
        href: "/procurement",
        icon: Truck,
        status: "not-configured",
        description: "Purchasing, supplier performance, and inbound material tracking.",
      },
      {
        id: "sales",
        label: "Sales",
        href: "/sales",
        icon: Handshake,
        status: "not-configured",
        description: "Orders, shipments, and customer demand.",
      },
    ],
  },
  {
    id: "system",
    label: "System",
    items: [
      {
        id: "data-sources",
        label: "Data Sources",
        href: "/system/data-sources",
        icon: Database,
        description: "Connections to source systems that feed platform modules.",
      },
      {
        id: "sync",
        label: "Sync Status",
        href: "/system/sync",
        icon: RefreshCw,
        description: "Health and history of data synchronization jobs.",
      },
      {
        id: "audit",
        label: "Audit Log",
        href: "/system/audit",
        icon: ScrollText,
        description: "Security-relevant and data ingestion events.",
      },
    ],
  },
];

export const moduleItems: NavItem[] =
  navigation.find((section) => section.id === "modules")?.items ?? [];

export function getNavItem(href: string): NavItem {
  const item = findNavItemByHref(navigation, href);
  if (!item) throw new Error(`No navigation item registered for ${href}`);
  return item;
}
