import { ApiError, apiGet, apiSend } from "@/lib/api-client";

/** Mirrors the FastAPI Supervisor Safety Contacts contract. Every count is a count of contact records. */

export type SupervisorInput = {
  displayName: string;
  active: boolean;
  participationEligible: boolean;
  /** YYYY-MM-DD */
  effectiveFrom: string;
  /** YYYY-MM-DD; required when inactive. */
  effectiveTo: string | null;
};

export type Supervisor = SupervisorInput & {
  id: number;
  /** Supervisors with contacts cannot be deleted. */
  hasContacts: boolean;
  createdAt: string;
  createdBy: string;
  updatedAt: string;
  updatedBy: string;
};

export type SupervisorListResponse = { supervisors: Supervisor[]; canEdit: boolean };

export type ContactInput = {
  /** YYYY-MM-DD */
  contactDate: string;
  supervisorId: number;
};

export type Contact = ContactInput & {
  id: number;
  supervisorName: string;
  createdAt: string;
  createdBy: string;
  updatedAt: string;
  updatedBy: string;
};

export type ContactListResponse = { contacts: Contact[]; totalMatching: number; canEdit: boolean };

/** Eligible supervisors with a contact in the month, out of those eligible for it. */
export type Participation = { participating: number; eligible: number; rate: number | null };

export type SupervisorCount = {
  supervisorId: number;
  displayName: string;
  active: boolean;
  contacts: number;
};

export type ContactSummaryResponse = {
  year: number;
  month: number | null;
  contacts: number;
  participation: Participation | null;
  supervisors: SupervisorCount[];
};

export type ContactDashboardResponse = {
  year: number;
  /** Last month of the year that has started (0-12). Later months are null. */
  throughMonth: number;
  contacts: number;
  months: { month: number; contacts: number | null; participation: Participation | null }[];
  /** Alphabetical. */
  supervisors: (Omit<SupervisorCount, "contacts"> & { monthly: (number | null)[]; total: number })[];
  yearsWithData: number[];
};

const BASE = "/api/v1/safety/contacts";

export const contactKeys = {
  all: ["safety", "contacts"] as const,
  supervisors: () => [...contactKeys.all, "supervisors"] as const,
  recent: (limit: number) => [...contactKeys.all, "recent", limit] as const,
  summary: (year: number, month: number) => [...contactKeys.all, "summary", year, month] as const,
  dashboard: (year: number) => [...contactKeys.all, "dashboard", year] as const,
};

export function fetchSupervisors(signal?: AbortSignal) {
  return apiGet<SupervisorListResponse>(`${BASE}/supervisors`, { signal });
}

export function fetchRecentContacts(limit: number, signal?: AbortSignal) {
  return apiGet<ContactListResponse>(`${BASE}?limit=${limit}`, { signal });
}

export function fetchContactSummary(year: number, month: number, signal?: AbortSignal) {
  return apiGet<ContactSummaryResponse>(`${BASE}/summary?year=${year}&month=${month}`, { signal });
}

export function fetchContactDashboard(year: number, signal?: AbortSignal) {
  return apiGet<ContactDashboardResponse>(`${BASE}/dashboard?year=${year}`, { signal });
}

/** ``requestId`` identifies one tap: resubmitting it never records a second contact. */
export function createContact(input: ContactInput & { requestId: string }) {
  return apiSend<Contact>("POST", BASE, input);
}

export function updateContact(id: number, input: ContactInput, expectedUpdatedAt: string) {
  return apiSend<Contact>("PUT", `${BASE}/${id}`, { ...input, expectedUpdatedAt });
}

export function deleteContact(id: number) {
  return apiSend<void>("DELETE", `${BASE}/${id}`);
}

export function createSupervisor(input: SupervisorInput) {
  return apiSend<Supervisor>("POST", `${BASE}/supervisors`, input);
}

export function updateSupervisor(id: number, input: SupervisorInput, expectedUpdatedAt: string) {
  return apiSend<Supervisor>("PUT", `${BASE}/supervisors/${id}`, { ...input, expectedUpdatedAt });
}

export function deleteSupervisor(id: number) {
  return apiSend<void>("DELETE", `${BASE}/supervisors/${id}`);
}

const RULE_MESSAGES: Record<string, string> = {
  contact_date_in_future: "The contact date cannot be in the future.",
  unknown_supervisor: "That supervisor no longer exists. Refresh the page.",
  supervisor_inactive: "That supervisor is inactive and cannot be credited with new contacts.",
  outside_effective_period: "The contact date is outside the supervisor's effective dates.",
  duplicate_display_name: "Another supervisor already has this name.",
  effective_period_invalid: "The end date cannot be before the start date.",
  inactive_requires_end_date: "An inactive supervisor needs an end date.",
  supervisor_has_contacts:
    "Contacts are recorded for this supervisor, so they cannot be deleted. Set them inactive instead.",
};

/** User-facing explanation of a failed Supervisor Safety Contacts request. */
export function describeContactError(error: unknown): string {
  if (!(error instanceof ApiError)) return "The API could not be reached. Nothing was saved.";
  const code = error.detail?.error;
  if (code === "contacts_outside_effective_period") {
    const count = Number(error.detail?.contacts ?? 0);
    return `${count} ${count === 1 ? "contact is" : "contacts are"} recorded outside these dates. Adjust the dates to include them.`;
  }
  if (code && RULE_MESSAGES[code]) return RULE_MESSAGES[code];
  switch (error.status) {
    case 401:
      return "Sign-in is required to view Safety data. User authentication is not enabled on this server yet.";
    case 403:
      return "You do not have permission for this Safety function.";
    case 404:
      return "This record no longer exists. It may have been deleted by someone else.";
    case 409:
      return "Someone else changed this record since it was loaded. Nothing was saved; the latest version is now shown.";
    case 503:
      return "Safety data is unavailable because the database could not be reached.";
    default:
      return error.detail?.message ?? `The API responded with HTTP ${error.status}.`;
  }
}
