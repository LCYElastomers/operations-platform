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
  Inbox,
  LayoutDashboard,
  Leaf,
  RefreshCw,
  ScrollText,
  ShieldCheck,
  TableProperties,
  TrendingDown,
  Truck,
  UserRound,
  Users,
  Wrench,
} from "lucide-react";

import { findNavItemByHref, type NavItem, type NavSection } from "@/lib/navigation";

const APP = { all: ["app.view"] } as const;

export const navigation: NavSection[] = [
  {
    id: "main",
    items: [
      { id: "overview", label: "Overview", href: "/", exact: true, icon: LayoutDashboard, requires: APP },
      {
        id: "my-assignments",
        label: "My Assignments",
        href: "/my-assignments",
        icon: Inbox,
        requires: { all: ["assignments.viewOwn"] },
        description: "Corrective Action Reports, CAR actions and quality cost items assigned to you.",
      },
    ],
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
          { id: "quality-overview", label: "Overview", href: "/quality", exact: true, requires: { all: ["quality.view"] } },
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
                requires: { all: ["quality.view"] },
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
                requires: { all: ["qualityCost.view"] },
                description:
                  "Every quality cost item, classified as prevention, appraisal, internal or external failure. Add, review and update items here.",
              },
              {
                id: "quality-copq",
                label: "Cost of Poor Quality",
                href: "/quality/cost/copq",
                icon: CircleDollarSign,
                status: "in-development",
                requires: { all: ["qualityCost.view", "qualityDashboard.view"] },
                description:
                  "Internal and external failure costs from the Quality Cost Register: confirmed cost, potential exposure, recovery, trends and aging, plus an incident cost estimator.",
              },
              {
                id: "quality-coq-matrix",
                label: "COQ Matrix",
                href: "/quality/cost/matrix",
                icon: Grid2x2,
                status: "in-development",
                requires: { all: ["qualityCost.view", "qualityDashboard.view"] },
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
                requires: { all: ["car.view", "qualityDashboard.view"] },
                description:
                  "Open, past-due and due-soon CARs, effectiveness reviews waiting, trends, aging and cost impact.",
              },
              {
                id: "quality-cars-register",
                label: "CAR Register",
                href: "/quality/cars/register",
                icon: ClipboardCheck,
                status: "in-development",
                requires: { all: ["car.view"] },
                description:
                  "Every Corrective Action Report with its status, actions, effectiveness and cost impact. Select a CAR to open, edit and progress it.",
              },
              {
                id: "quality-cars-new",
                label: "+ New CAR",
                href: "/quality/cars/new",
                icon: FilePlus2,
                status: "in-development",
                requires: { all: ["car.view", "car.create"] },
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
        requires: APP,
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
          { id: "safety-overview", label: "Overview", href: "/safety", exact: true, requires: { all: ["safety.view"] } },
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
                requires: { all: ["safetyRecord.view"] },
                description: "Enter monthly Incident & Near Miss counts in the familiar spreadsheet layout.",
              },
              {
                id: "safety-incidents-dashboard",
                label: "Dashboard",
                href: "/safety/incidents/dashboard",
                icon: ChartColumn,
                status: "in-development",
                requires: { all: ["safetyRecord.view", "safetyDashboard.view"] },
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
                requires: { all: ["safetyObservation.view"] },
                description: "Record safe and unsafe acts and conditions, and review the month's observations.",
              },
              {
                id: "safety-observations-dashboard",
                label: "Dashboard",
                href: "/safety/observations/dashboard",
                icon: ChartColumn,
                status: "in-development",
                requires: { all: ["safetyObservation.view", "safetyDashboard.view"] },
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
                requires: { all: ["safetyRecord.view"] },
                description: "Enter monthly worked hours and close months once their event counts are complete.",
              },
              {
                id: "safety-performance-dashboard",
                label: "Dashboard",
                href: "/safety/performance/dashboard",
                icon: Activity,
                status: "in-development",
                requires: { all: ["safetyRecord.view", "safetyDashboard.view"] },
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
                requires: { all: ["safetyRecord.view", "safetyDashboard.view"] },
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
        requires: APP,
        description: "Emissions, permits, and environmental compliance monitoring.",
      },
      {
        id: "procurement",
        label: "Procurement",
        href: "/procurement",
        icon: Truck,
        status: "not-configured",
        requires: APP,
        description: "Purchasing, supplier performance, and inbound material tracking.",
      },
      {
        id: "sales",
        label: "Sales",
        href: "/sales",
        icon: Handshake,
        status: "not-configured",
        requires: APP,
        description: "Orders, shipments, and customer demand.",
      },
    ],
  },
  {
    id: "administration",
    label: "Administration",
    items: [
      {
        id: "admin-users",
        label: "Users",
        href: "/admin/users",
        icon: Users,
        requires: { all: ["users.view"] },
        description: "Create user accounts, assign roles, activate and deactivate users, and issue password setup links.",
      },
      {
        id: "admin-roles",
        label: "Roles & Permissions",
        href: "/admin/roles",
        icon: ShieldCheck,
        requires: { all: ["roles.view"] },
        description: "Roles and the permissions each grants. A user's access is the union of their active roles.",
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
        requires: APP,
        description: "Connections to source systems that feed platform modules.",
      },
      {
        id: "sync",
        label: "Sync Status",
        href: "/system/sync",
        icon: RefreshCw,
        requires: APP,
        description: "Health and history of data synchronization jobs.",
      },
      {
        id: "audit",
        label: "Audit Log",
        href: "/system/audit",
        icon: ScrollText,
        requires: { all: ["audit.view"] },
        description: "Who changed what and when: user and role changes, password links, and record changes.",
      },
    ],
  },
];

/** Pages reached from the user menu rather than the sidebar. */
export const accountNavigation: NavSection[] = [
  {
    id: "account",
    items: [
      {
        id: "profile",
        label: "Profile",
        href: "/profile",
        icon: UserRound,
        requires: APP,
        description: "Your account details, roles and permissions, and your password.",
      },
    ],
  },
];

export const moduleItems: NavItem[] =
  navigation.find((section) => section.id === "modules")?.items ?? [];

export function getNavItem(href: string): NavItem {
  const item = findNavItemByHref([...navigation, ...accountNavigation], href);
  if (!item) throw new Error(`No navigation item registered for ${href}`);
  return item;
}
