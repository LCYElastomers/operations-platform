import {
  Activity,
  ChartColumn,
  CircleDollarSign,
  ClipboardCheck,
  ClipboardList,
  Clock,
  Database,
  Droplets,
  FilePlus2,
  FlaskConical,
  Grid2x2,
  HardHat,
  Handshake,
  LayoutDashboard,
  Leaf,
  RefreshCw,
  ScrollText,
  TableProperties,
  TrendingDown,
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
                fixture: true,
                description: "Moisture, color, and combined BD of incoming raw materials.",
              },
            ],
          },
          {
            id: "quality-cost",
            label: "Cost of Quality",
            children: [
              {
                id: "quality-cost-register",
                label: "Quality Cost Register",
                href: "/quality/cost/register",
                icon: ClipboardList,
                status: "in-development",
                description:
                  "Every quality cost item, classified as prevention, appraisal, internal or external failure. Add, review and update items here.",
              },
              {
                id: "quality-copq",
                label: "Cost of Poor Quality",
                href: "/quality/cost/copq",
                icon: CircleDollarSign,
                status: "in-development",
                description:
                  "Internal and external failure costs from the Quality Cost Register: confirmed cost, potential exposure, recovery, trends and aging, plus an incident cost estimator.",
              },
              {
                id: "quality-coq-matrix",
                label: "COQ Matrix",
                href: "/quality/cost/matrix",
                icon: Grid2x2,
                status: "in-development",
                description:
                  "Prevention, appraisal, internal and external failure costs from the Quality Cost Register, and the cost of quality mix.",
              },
            ],
          },
          {
            id: "quality-cars",
            label: "Corrective Action Reports",
            children: [
              {
                id: "quality-cars-dashboard",
                label: "Dashboard",
                href: "/quality/cars",
                exact: true,
                icon: ChartColumn,
                status: "in-development",
                description:
                  "Open, past-due and due-soon CARs, effectiveness reviews waiting, trends, aging and cost impact.",
              },
              {
                id: "quality-cars-register",
                label: "CAR Register",
                href: "/quality/cars/register",
                icon: ClipboardCheck,
                status: "in-development",
                description:
                  "Every Corrective Action Report with its status, actions, effectiveness and cost impact. Select a CAR to open, edit and progress it.",
              },
              {
                id: "quality-cars-new",
                label: "+ New CAR",
                href: "/quality/cars/new",
                icon: FilePlus2,
                status: "in-development",
                description:
                  "Record a new Corrective Action Report. Only the subject and request date are needed to save; the other steps can be completed later.",
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
        icon: HardHat,
        status: "in-development",
        description:
          "Departmental safety reporting: Incident & Near Miss, Safety Observations, Safety Performance, and TRIR Experience.",
        children: [
          { id: "safety-overview", label: "Overview", href: "/safety", exact: true },
          {
            id: "safety-incidents",
            label: "Incident & Near Miss",
            description: "Monthly incident classification, near miss, LOPC, damage, PIT, and PSIF counts.",
            children: [
              {
                id: "safety-incidents-data-entry",
                label: "Data Entry",
                href: "/safety/incidents/data-entry",
                icon: TableProperties,
                status: "in-development",
                description: "Enter monthly Incident & Near Miss counts in the familiar spreadsheet layout.",
              },
              {
                id: "safety-incidents-dashboard",
                label: "Dashboard",
                href: "/safety/incidents/dashboard",
                icon: ChartColumn,
                status: "in-development",
                description:
                  "Year-to-date Incident, Near Miss, LOPC, PSIF, PIT and damage counts, with monthly trends through a chosen month.",
              },
            ],
          },
          {
            id: "safety-observations",
            label: "Safety Observations",
            description: "Safe and unsafe acts and conditions, recorded one observation at a time.",
            children: [
              {
                id: "safety-observations-entry",
                label: "Observations",
                href: "/safety/observations",
                exact: true,
                icon: ClipboardList,
                status: "in-development",
                description: "Record safe and unsafe acts and conditions, and review the month's observations.",
              },
              {
                id: "safety-observations-dashboard",
                label: "Dashboard",
                href: "/safety/observations/dashboard",
                icon: ChartColumn,
                status: "in-development",
                description: "Year-to-date Safe vs Unsafe, Act / Condition, and category trends.",
              },
            ],
          },
          {
            id: "safety-performance",
            label: "Safety Performance",
            description: "Worked hours and TRIR, First Aid, LOPC and Property & Equipment Damage rates.",
            children: [
              {
                id: "safety-performance-data-entry",
                label: "Data Entry",
                href: "/safety/performance/data-entry",
                icon: Clock,
                status: "in-development",
                description: "Enter monthly worked hours and close months once their event counts are complete.",
              },
              {
                id: "safety-performance-dashboard",
                label: "Dashboard",
                href: "/safety/performance/dashboard",
                icon: Activity,
                status: "in-development",
                description: "YTD and 12-Month Rolling Average (12MRA) rates, worked hours, and annual TRIR.",
              },
            ],
          },
          {
            id: "safety-trir",
            label: "TRIR Experience",
            description: "Total Recordable Incident Rate history against the industry benchmark.",
            children: [
              {
                id: "safety-trir-experience",
                label: "Experience",
                href: "/safety/trir",
                icon: TrendingDown,
                status: "in-development",
                description:
                  "LCY TRIR by year and month with the benchmark, every calculation shown, and the methodology.",
              },
            ],
          },
        ],
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
