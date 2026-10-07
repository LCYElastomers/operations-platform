"use client";

import { AlertTriangle, ChartColumn, Eye, UserPlus, Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";

import { localIsoDate } from "../observations/observation-data";
import { describeContactError, type Contact, type Supervisor } from "./api";
import {
  contactDateError,
  countPeriodLabel,
  draftFromSupervisor,
  editableSupervisors,
  emptySupervisorDraft,
  EARLIEST_DATE,
  formatDate,
  newRequestId,
  periodOf,
  tallyTiles,
  toSupervisorInput,
  validateSupervisorDraft,
  type SupervisorDraft,
} from "./contact-data";
import { ContactEditor, ContactRow, fieldClasses, type ContactEdit } from "./recent-contacts";
import { SupervisorForm, SupervisorRow } from "./supervisor-manager";
import { AddedFeedback, TallyBoard } from "./tally-board";
import {
  useContactSummary,
  useCreateContact,
  useDeleteContact,
  useDeleteSupervisor,
  useRecentContacts,
  useSaveSupervisor,
  useSupervisors,
  useUpdateContact,
} from "./use-contacts";

const RECENT_PAGE_SIZE = 20;

type Feedback = { message: string; tone: "success" | "error"; undo: Contact | null };
type SupervisorEditing = { supervisor: Supervisor | null; draft: SupervisorDraft };

function isAccessDenied(error: unknown) {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

type ContactsPageProps = { title: string; description?: string };

export function ContactsPage({ title, description }: ContactsPageProps) {
  const dateId = useId();
  const [today, setToday] = useState(() => localIsoDate(new Date()));
  const [contactDate, setContactDate] = useState(today);

  // A tablet left open overnight should not keep offering yesterday as "today".
  useEffect(() => {
    const timer = window.setInterval(() => setToday(localIsoDate(new Date())), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  const dateError = contactDateError(contactDate, today);
  const period = dateError ? periodOf(today) : periodOf(contactDate);

  const supervisors = useSupervisors();
  const summary = useContactSummary(period.year, period.month);
  const [recentLimit, setRecentLimit] = useState(RECENT_PAGE_SIZE);
  const recent = useRecentContacts(recentLimit);
  const create = useCreateContact();
  const update = useUpdateContact();
  const remove = useDeleteContact();
  const saveSupervisor = useSaveSupervisor();
  const removeSupervisor = useDeleteSupervisor();

  const canEdit = supervisors.data?.canEdit ?? false;
  const allSupervisors = useMemo(() => supervisors.data?.supervisors ?? [], [supervisors.data]);
  const tiles = useMemo(
    () => tallyTiles(allSupervisors, dateError ? today : contactDate),
    [allSupervisors, contactDate, dateError, today],
  );
  const counts = useMemo(
    () =>
      summary.data && summary.data.year === period.year && summary.data.month === period.month
        ? new Map(summary.data.supervisors.map((s) => [s.supervisorId, s.contacts]))
        : undefined,
    [summary.data, period.year, period.month],
  );

  // A ref, not state: two taps in the same frame must not both get through.
  const inFlight = useRef(new Set<number>());
  const [pendingIds, setPendingIds] = useState<ReadonlySet<number>>(new Set());
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [lastAddedId, setLastAddedId] = useState<number | null>(null);
  const [undoing, setUndoing] = useState(false);
  const feedbackRef = useRef<HTMLParagraphElement>(null);

  const [editing, setEditing] = useState<{ contact: Contact; value: ContactEdit } | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const [managing, setManaging] = useState(false);
  const [supervisorEditing, setSupervisorEditing] = useState<SupervisorEditing | null>(null);
  const [supervisorAttempted, setSupervisorAttempted] = useState(false);
  const [confirmSupervisorDeleteId, setConfirmSupervisorDeleteId] = useState<number | null>(null);
  const supervisorErrors = useMemo(
    () =>
      supervisorEditing
        ? validateSupervisorDraft(supervisorEditing.draft, allSupervisors, supervisorEditing.supervisor?.id ?? null)
        : {},
    [supervisorEditing, allSupervisors],
  );

  const settle = (id: number) => {
    inFlight.current.delete(id);
    setPendingIds(new Set(inFlight.current));
  };

  const addContact = (supervisor: Supervisor) => {
    if (dateError || inFlight.current.has(supervisor.id)) return;
    inFlight.current.add(supervisor.id);
    setPendingIds(new Set(inFlight.current));
    const date = contactDate;
    create
      .mutateAsync({ contactDate: date, supervisorId: supervisor.id, requestId: newRequestId() })
      .then((saved) => {
        setLastAddedId(saved.id);
        setFeedback({
          message: `Contact added: ${saved.supervisorName}, ${formatDate(saved.contactDate)}.`,
          tone: "success",
          undo: saved,
        });
      })
      .catch((error: unknown) => {
        setFeedback({
          message: `Not saved for ${supervisor.displayName}: ${describeContactError(error)}`,
          tone: "error",
          undo: null,
        });
      })
      .finally(() => settle(supervisor.id));
  };

  const undo = () => {
    const contact = feedback?.undo;
    if (!contact || undoing) return;
    setUndoing(true);
    remove
      .mutateAsync(contact.id)
      .then(() => {
        if (lastAddedId === contact.id) setLastAddedId(null);
        setFeedback({
          message: `Undone: the contact for ${contact.supervisorName} on ${formatDate(contact.contactDate)} was removed.`,
          tone: "success",
          undo: null,
        });
      })
      .catch((error: unknown) => {
        setFeedback({ message: `Undo failed: ${describeContactError(error)}`, tone: "error", undo: null });
      })
      .finally(() => {
        setUndoing(false);
        feedbackRef.current?.focus();
      });
  };

  const editDateError = editing ? contactDateError(editing.value.contactDate, today) : null;

  const submitEdit = () => {
    if (!editing || editDateError) return;
    update
      .mutateAsync({
        id: editing.contact.id,
        input: editing.value,
        expectedUpdatedAt: editing.contact.updatedAt,
      })
      .then((saved) => {
        setEditing(null);
        setFeedback({
          message: `Contact updated: ${saved.supervisorName}, ${formatDate(saved.contactDate)}.`,
          tone: "success",
          undo: null,
        });
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
          setEditing(null);
          setFeedback({ message: describeContactError(error), tone: "error", undo: null });
        }
      });
  };

  const confirmDelete = (id: number) => {
    remove
      .mutateAsync(id)
      .then(() => {
        setConfirmDeleteId(null);
        if (lastAddedId === id) setLastAddedId(null);
        setFeedback({ message: "Contact deleted.", tone: "success", undo: null });
      })
      .catch((error: unknown) => {
        setConfirmDeleteId(null);
        setFeedback({ message: describeContactError(error), tone: "error", undo: null });
      })
      .finally(() => feedbackRef.current?.focus());
  };

  const openSupervisorForm = (supervisor: Supervisor | null) => {
    saveSupervisor.reset();
    setSupervisorAttempted(false);
    setConfirmSupervisorDeleteId(null);
    setManaging(true);
    setSupervisorEditing({
      supervisor,
      draft: supervisor ? draftFromSupervisor(supervisor) : emptySupervisorDraft(today),
    });
  };

  const submitSupervisor = () => {
    if (!supervisorEditing) return;
    setSupervisorAttempted(true);
    if (Object.keys(supervisorErrors).length > 0) return;
    const { supervisor, draft } = supervisorEditing;
    saveSupervisor
      .mutateAsync({
        id: supervisor?.id ?? null,
        input: toSupervisorInput(draft),
        expectedUpdatedAt: supervisor?.updatedAt ?? null,
      })
      .then((saved) => {
        setSupervisorEditing(null);
        setFeedback({
          message: `${supervisor ? "Supervisor updated" : "Supervisor added"}: ${saved.displayName}.`,
          tone: "success",
          undo: null,
        });
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
          setSupervisorEditing(null);
          setFeedback({ message: describeContactError(error), tone: "error", undo: null });
        }
      });
  };

  const confirmSupervisorDelete = (supervisor: Supervisor) => {
    removeSupervisor
      .mutateAsync(supervisor.id)
      .then(() => {
        setConfirmSupervisorDeleteId(null);
        setFeedback({ message: `Supervisor deleted: ${supervisor.displayName}.`, tone: "success", undo: null });
      })
      .catch((error: unknown) => {
        setConfirmSupervisorDeleteId(null);
        setFeedback({ message: describeContactError(error), tone: "error", undo: null });
      });
  };

  const loadError = supervisors.error ?? recent.error;
  const denied = isAccessDenied(loadError);
  const contacts = recent.data?.contacts ?? [];
  const totalContacts = recent.data?.totalMatching ?? 0;
  const countLabel = countPeriodLabel(dateError ? today : contactDate, today);

  const supervisorForm = supervisorEditing && (
    <section
      aria-label={supervisorEditing.supervisor ? "Edit supervisor" : "Add supervisor"}
      className="rounded-lg border border-primary/50 bg-card p-4 ring-2 ring-primary/20"
    >
      <h3 className="mb-4 text-sm font-semibold">
        {supervisorEditing.supervisor ? "Edit supervisor" : "Add supervisor"}
      </h3>
      <SupervisorForm
        draft={supervisorEditing.draft}
        onChange={(draft) => {
          setSupervisorEditing({ ...supervisorEditing, draft });
          if (saveSupervisor.isError) saveSupervisor.reset();
        }}
        onSubmit={submitSupervisor}
        onCancel={() => setSupervisorEditing(null)}
        errors={supervisorErrors}
        showErrors={supervisorAttempted}
        submitLabel={supervisorEditing.supervisor ? "Save Changes" : "Add Supervisor"}
        pending={saveSupervisor.isPending}
        saveError={saveSupervisor.isError ? describeContactError(saveSupervisor.error) : null}
      />
    </section>
  );

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Safety · Supervisor Safety Contacts"
        title={title}
        description={description}
        actions={
          <Link
            href="/safety/contacts/dashboard"
            className={buttonVariants({ variant: "outline", className: "pointer-coarse:h-11" })}
          >
            <ChartColumn />
            Open dashboard
          </Link>
        }
      />

      {denied ? (
        <EmptyState
          icon={AlertTriangle}
          title="Supervisor Safety Contacts are not available to you"
          description={describeContactError(loadError)}
        />
      ) : (
        <>
          <section aria-labelledby="record-contacts-heading" className="space-y-4 rounded-lg border bg-card p-4 sm:p-5">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div className="w-full max-w-xs">
                <label htmlFor={dateId} className="flex flex-col gap-1">
                  <span className="text-sm font-medium">Contact Date</span>
                  <input
                    id={dateId}
                    type="date"
                    required
                    min={EARLIEST_DATE}
                    max={today}
                    value={contactDate}
                    onChange={(event) => setContactDate(event.target.value)}
                    aria-invalid={dateError ? true : undefined}
                    aria-describedby={dateError ? `${dateId}-error` : undefined}
                    className={`${fieldClasses} h-12 text-base`}
                  />
                </label>
                {dateError && (
                  <p id={`${dateId}-error`} className="mt-1 text-xs font-medium text-destructive">
                    {dateError}
                  </p>
                )}
              </div>
              {contactDate !== today && (
                <Button variant="outline" className="h-11" onClick={() => setContactDate(today)}>
                  Use today
                </Button>
              )}
            </div>

            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 id="record-contacts-heading" className="text-base font-semibold">
                Active Supervisors
              </h2>
              {summary.isFetching && !summary.isPending && (
                <StatusBadge tone="pending" pulse>
                  Updating
                </StatusBadge>
              )}
            </div>

            {canEdit && (feedback || tiles.length > 0) && (
              <AddedFeedback
                message={feedback?.message ?? null}
                tone={feedback?.tone}
                onUndo={feedback?.undo ? undo : undefined}
                undoing={undoing}
                messageRef={feedbackRef}
              />
            )}

            {supervisors.isPending ? (
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4" aria-busy>
                {[0, 1, 2, 3].map((key) => (
                  <div key={key} className="h-32 animate-pulse rounded-lg border bg-muted/50" />
                ))}
                <span className="sr-only">Loading supervisors</span>
              </div>
            ) : supervisors.isError ? (
              <EmptyState
                variant="plain"
                icon={AlertTriangle}
                title="Could not load supervisors"
                description={describeContactError(supervisors.error)}
                action={
                  <Button variant="outline" onClick={() => void supervisors.refetch()}>
                    Retry
                  </Button>
                }
              />
            ) : tiles.length === 0 ? (
              <EmptyState
                variant="plain"
                icon={Users}
                title="No active supervisors"
                description={
                  canEdit
                    ? "Add the supervisors in this program to start recording contacts."
                    : "Supervisors appear here once they are added to the program."
                }
                action={
                  canEdit ? (
                    <Button className="h-11" onClick={() => openSupervisorForm(null)}>
                      <UserPlus />
                      Add supervisor
                    </Button>
                  ) : undefined
                }
              />
            ) : (
              <TallyBoard
                tiles={tiles}
                counts={counts}
                countLabel={countLabel}
                canEdit={canEdit}
                pendingIds={pendingIds}
                blocked={dateError !== null}
                onAdd={addContact}
              />
            )}

            {!canEdit && supervisors.isSuccess && (
              <p className="flex items-center gap-2 rounded-md border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">
                <Eye aria-hidden className="size-4 shrink-0" />
                You have view-only access. Contacts cannot be added or changed with your permissions.
              </p>
            )}
          </section>

          <div className="grid grid-cols-1 items-start gap-5 min-[1280px]:grid-cols-2">
            <section aria-labelledby="recent-contacts-heading" className="min-w-0 space-y-3">
              <div className="flex items-baseline justify-between gap-3">
                <h2
                  id="recent-contacts-heading"
                  className="text-xs font-semibold tracking-wide text-muted-foreground uppercase"
                >
                  Recent Contacts
                </h2>
                {recent.isSuccess && (
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {contacts.length < totalContacts
                      ? `${contacts.length} of ${totalContacts}`
                      : `${totalContacts} ${totalContacts === 1 ? "contact" : "contacts"}`}
                  </span>
                )}
              </div>
              {recent.isPending ? (
                <div className="space-y-2" aria-busy>
                  {[0, 1, 2].map((key) => (
                    <div key={key} className="h-16 animate-pulse rounded-lg border bg-muted/50" />
                  ))}
                </div>
              ) : recent.isError ? (
                <EmptyState
                  icon={AlertTriangle}
                  title="Could not load contacts"
                  description={describeContactError(recent.error)}
                  action={
                    <Button variant="outline" onClick={() => void recent.refetch()}>
                      Retry
                    </Button>
                  }
                />
              ) : contacts.length === 0 ? (
                <EmptyState
                  icon={Users}
                  title="No contacts recorded yet"
                  description={canEdit ? "Contacts you record will appear here, newest first." : undefined}
                />
              ) : (
                <ul className="space-y-2">
                  {contacts.map((contact) => (
                    <li key={contact.id}>
                      {editing?.contact.id === contact.id ? (
                        <ContactEditor
                          value={editing.value}
                          onChange={(value) => {
                            setEditing({ ...editing, value });
                            if (update.isError) update.reset();
                          }}
                          onSubmit={submitEdit}
                          onCancel={() => setEditing(null)}
                          supervisors={editableSupervisors(allSupervisors, contact.supervisorId)}
                          today={today}
                          dateError={editDateError}
                          pending={update.isPending}
                          saveError={update.isError ? describeContactError(update.error) : null}
                        />
                      ) : (
                        <ContactRow
                          contact={contact}
                          canEdit={canEdit}
                          highlighted={contact.id === lastAddedId}
                          confirmingDelete={confirmDeleteId === contact.id}
                          deleting={remove.isPending && remove.variables === contact.id}
                          onEdit={() => {
                            update.reset();
                            setConfirmDeleteId(null);
                            setEditing({
                              contact,
                              value: { contactDate: contact.contactDate, supervisorId: contact.supervisorId },
                            });
                          }}
                          onRequestDelete={() => {
                            setEditing(null);
                            setConfirmDeleteId(contact.id);
                          }}
                          onCancelDelete={() => setConfirmDeleteId(null)}
                          onConfirmDelete={() => confirmDelete(contact.id)}
                        />
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {recent.isSuccess && contacts.length < totalContacts && (
                <Button
                  variant="outline"
                  className="h-12 w-full"
                  onClick={() => setRecentLimit((value) => value + RECENT_PAGE_SIZE)}
                  disabled={recent.isFetching}
                >
                  Show more contacts
                </Button>
              )}
            </section>

            {canEdit && (
              <section aria-labelledby="supervisors-heading" className="min-w-0 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h2
                    id="supervisors-heading"
                    className="text-xs font-semibold tracking-wide text-muted-foreground uppercase"
                  >
                    Supervisors
                  </h2>
                  <div className="flex gap-2">
                    {managing && !supervisorEditing && (
                      <Button variant="outline" className="h-11" onClick={() => openSupervisorForm(null)}>
                        <UserPlus />
                        Add supervisor
                      </Button>
                    )}
                    <Button
                      variant="outline"
                      className="h-11"
                      aria-expanded={managing}
                      aria-controls="supervisor-management"
                      onClick={() => {
                        setManaging(!managing);
                        setSupervisorEditing(null);
                        setConfirmSupervisorDeleteId(null);
                      }}
                    >
                      <Users />
                      {managing ? "Close" : "Manage supervisors"}
                    </Button>
                  </div>
                </div>
                <div id="supervisor-management" hidden={!managing} className="space-y-2">
                  {supervisorEditing && !supervisorEditing.supervisor && supervisorForm}
                  {allSupervisors.length === 0 && !supervisorEditing ? (
                    <EmptyState variant="plain" icon={Users} title="No supervisors yet" />
                  ) : (
                    <ul className="space-y-2" aria-label="All supervisors">
                      {allSupervisors.map((supervisor) => (
                        <li key={supervisor.id}>
                          {supervisorEditing?.supervisor?.id === supervisor.id ? (
                            supervisorForm
                          ) : (
                            <SupervisorRow
                              supervisor={supervisor}
                              confirmingDelete={confirmSupervisorDeleteId === supervisor.id}
                              deleting={removeSupervisor.isPending && removeSupervisor.variables === supervisor.id}
                              onEdit={() => openSupervisorForm(supervisor)}
                              onRequestDelete={() => {
                                setSupervisorEditing(null);
                                setConfirmSupervisorDeleteId(supervisor.id);
                              }}
                              onCancelDelete={() => setConfirmSupervisorDeleteId(null)}
                              onConfirmDelete={() => confirmSupervisorDelete(supervisor)}
                            />
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="px-1 text-xs text-muted-foreground">
                    Supervisors with recorded contacts cannot be deleted; set them inactive with an end date
                    instead, so their history stays in the figures.
                  </p>
                </div>
              </section>
            )}
          </div>
        </>
      )}
    </div>
  );
}
