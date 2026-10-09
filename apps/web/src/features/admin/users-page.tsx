"use client";

import { AlertTriangle, UserPlus, Users } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { FilterBar, FilterInput, FilterSelect } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { UserAvatar } from "@/components/layout/user-menu";
import { usePermissions } from "@/features/auth/use-session";
import { ApiError } from "@/lib/api-client";

import {
  createUser,
  describeAdminError,
  issuePasswordLink,
  setUserActive,
  setUserRoles,
  updateUser,
  type AdminUser,
  type AdminUserDetail,
  type PasswordLink,
  type Role,
} from "./api";
import { formatDateTime, Notice, PasswordLinkPanel, PermissionGroups, Section, TextField } from "./admin-shared";
import { useAdminMutation, useRoles, useUser, useUsers } from "./use-admin";

type StatusFilter = "" | "active" | "inactive";

function fieldError(error: unknown, field: string): string | null {
  return error instanceof ApiError && error.detail?.field === field ? (error.detail.message ?? null) : null;
}

export function UsersPage({ title, description }: { title: string; description?: string }) {
  const { has } = usePermissions();
  const users = useUsers();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("");
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  const term = search.trim().toLowerCase();
  const rows = (users.data ?? []).filter(
    (user) =>
      (status === "" || user.status === status) &&
      (term === "" || user.name.toLowerCase().includes(term) || user.email.toLowerCase().includes(term)),
  );

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Administration"
        title={title}
        description={description}
        actions={
          has("users.create") && (
            <Button onClick={() => setCreating(true)} className="pointer-coarse:h-11">
              <UserPlus />
              Add user
            </Button>
          )
        }
      />
      <FilterBar>
        <FilterInput
          label="Search"
          type="search"
          placeholder="Name or email"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <FilterSelect
          label="Status"
          options={[
            { value: "active", label: "Active" },
            { value: "inactive", label: "Inactive" },
          ]}
          value={status}
          onChange={(event) => setStatus(event.target.value as StatusFilter)}
        />
      </FilterBar>

      {users.isError ? (
        <EmptyState icon={AlertTriangle} title="Users could not be loaded" description={describeAdminError(users.error)} />
      ) : users.isPending ? (
        <p className="py-6 text-sm text-muted-foreground">Loading users…</p>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Users}
          title={users.data.length === 0 ? "No users yet" : "No users match the filters"}
          description={users.data.length === 0 ? "Add a user to give them access to the platform." : undefined}
        />
      ) : (
        <UserTable users={rows} onOpen={setOpenId} />
      )}

      {creating && <CreateUserDialog onClose={() => setCreating(false)} onCreated={(id) => setOpenId(id)} />}
      <UserDialog userId={openId} onClose={() => setOpenId(null)} />
    </div>
  );
}

const TH = "h-10 px-4 text-left text-xs font-semibold tracking-wide whitespace-nowrap text-muted-foreground uppercase";
const TD = "px-4 py-2.5 align-middle";

function UserStatusBadges({ user }: { user: AdminUser }) {
  return (
    <span className="flex flex-wrap gap-1.5">
      <StatusBadge tone={user.status === "active" ? "success" : "neutral"}>
        {user.status === "active" ? "Active" : "Inactive"}
      </StatusBadge>
      {!user.passwordSet && <StatusBadge tone="warning">Setup pending</StatusBadge>}
      {user.locked && <StatusBadge tone="danger">Locked</StatusBadge>}
    </span>
  );
}

function UserTable({ users, onOpen }: { users: AdminUser[]; onOpen: (id: string) => void }) {
  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-sm">
          <caption className="sr-only">Users</caption>
          <thead className="bg-muted/60">
            <tr className="border-b">
              <th scope="col" className={TH}>User</th>
              <th scope="col" className={TH}>Roles</th>
              <th scope="col" className={TH}>Status</th>
              <th scope="col" className={TH}>Last sign-in</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr
                key={user.id}
                onClick={() => onOpen(user.id)}
                className="cursor-pointer border-b last:border-b-0 hover:bg-muted/40"
              >
                <th scope="row" className={`${TD} text-left font-normal`}>
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      onOpen(user.id);
                    }}
                    className="flex items-center gap-3 text-left focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
                  >
                    <UserAvatar user={user} />
                    <span className="min-w-0">
                      <span className="block font-medium text-primary">{user.name}</span>
                      <span className="block text-xs text-muted-foreground">{user.email}</span>
                    </span>
                  </button>
                </th>
                <td className={TD}>
                  {user.roles.length === 0 ? (
                    <span className="text-muted-foreground">No roles</span>
                  ) : (
                    user.roles.map((role) => role.name).join(", ")
                  )}
                </td>
                <td className={TD}>
                  <UserStatusBadges user={user} />
                </td>
                <td className={`${TD} whitespace-nowrap`}>{formatDateTime(user.lastLoginAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RolePicker({
  roles,
  selected,
  onChange,
  disabled,
}: {
  roles: Role[];
  selected: string[];
  onChange: (codes: string[]) => void;
  disabled?: boolean;
}) {
  const toggle = (code: string) =>
    onChange(selected.includes(code) ? selected.filter((c) => c !== code) : [...selected, code]);
  return (
    <fieldset>
      <legend className="sr-only">Roles</legend>
      <ul className="grid gap-2 sm:grid-cols-2">
        {roles.map((role) => (
          <li key={role.code}>
            <label className="flex items-start gap-2 rounded-md border p-2.5 text-sm has-[:checked]:border-primary/50 has-[:checked]:bg-primary/5">
              <input
                type="checkbox"
                className="mt-0.5 size-4"
                checked={selected.includes(role.code)}
                onChange={() => toggle(role.code)}
                disabled={disabled}
              />
              <span className="min-w-0">
                <span className="flex flex-wrap items-center gap-1.5 font-medium">
                  {role.name}
                  {!role.active && <StatusBadge>Inactive</StatusBadge>}
                </span>
                {role.description && <span className="block text-xs text-muted-foreground">{role.description}</span>}
              </span>
            </label>
          </li>
        ))}
      </ul>
    </fieldset>
  );
}

function CreateUserDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const { has } = usePermissions();
  const roles = useRoles(has("roles.view"));
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [roleCodes, setRoleCodes] = useState<string[]>([]);
  const [created, setCreated] = useState<{ user: AdminUserDetail; link: PasswordLink } | null>(null);
  const create = useAdminMutation(createUser);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    create.mutate(
      { name: name.trim(), email: email.trim(), roleCodes: has("users.assignRoles") ? roleCodes : [] },
      { onSuccess: (result) => setCreated({ user: result.user, link: result.passwordLink }) },
    );
  };

  if (created) {
    return (
      <Dialog
        open
        onClose={onClose}
        title="User added"
        footer={
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => {
                onClose();
                onCreated(created.user.id);
              }}
            >
              Open user
            </Button>
            <Button onClick={onClose}>Done</Button>
          </div>
        }
      >
        <div className="space-y-4">
          <Notice tone="success">
            {created.user.name} ({created.user.email}) was added. They cannot sign in until they set a password with the link below.
          </Notice>
          <PasswordLinkPanel link={created.link} name={created.user.name} />
        </div>
      </Dialog>
    );
  }

  const otherError = create.error && !fieldError(create.error, "email") && !fieldError(create.error, "name");
  return (
    <Dialog
      open
      onClose={onClose}
      title="Add user"
      description="The user receives a one-time link to set their own password. No password is chosen or seen by administrators."
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="create-user" disabled={create.isPending}>
            {create.isPending ? "Adding…" : "Add user"}
          </Button>
        </div>
      }
    >
      <form id="create-user" onSubmit={submit} className="space-y-4">
        {otherError && <Notice tone="error">{describeAdminError(create.error)}</Notice>}
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="Name"
            required
            maxLength={200}
            value={name}
            onChange={(event) => setName(event.target.value)}
            error={fieldError(create.error, "name")}
          />
          <TextField
            label="Email address"
            type="email"
            required
            maxLength={254}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            error={fieldError(create.error, "email")}
            hint="Used to sign in. Must be unique."
          />
        </div>
        {has("users.assignRoles") && (
          <Section title="Roles" description="The user's access is the combination of every role they hold.">
            {roles.isError ? (
              <p className="text-sm text-destructive">{describeAdminError(roles.error)}</p>
            ) : !roles.data ? (
              <p className="text-sm text-muted-foreground">{has("roles.view") ? "Loading roles…" : "Roles cannot be listed."}</p>
            ) : (
              <RolePicker roles={roles.data} selected={roleCodes} onChange={setRoleCodes} disabled={create.isPending} />
            )}
          </Section>
        )}
      </form>
    </Dialog>
  );
}

function UserDialog({ userId, onClose }: { userId: string | null; onClose: () => void }) {
  const user = useUser(userId);
  return (
    <Dialog open={userId !== null} onClose={onClose} title={user.data?.name ?? "User"} description={user.data?.email}>
      {user.isError ? (
        <EmptyState icon={AlertTriangle} title="This user could not be loaded" description={describeAdminError(user.error)} />
      ) : !user.data ? (
        <p className="py-6 text-sm text-muted-foreground">Loading…</p>
      ) : (
        <UserDetail key={user.data.id} user={user.data} />
      )}
    </Dialog>
  );
}

function UserDetail({ user }: { user: AdminUserDetail }) {
  const { has, session } = usePermissions();
  const self = session?.user.id === user.id;
  const [notice, setNotice] = useState<string | null>(null);
  const [link, setLink] = useState<PasswordLink | null>(null);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <UserAvatar user={user} className="size-10" />
        <div className="min-w-0 flex-1">
          <UserStatusBadges user={user} />
          <p className="mt-1 text-xs text-muted-foreground">
            Last sign-in {formatDateTime(user.lastLoginAt)} · Added {formatDateTime(user.createdAt)}
          </p>
        </div>
      </div>
      {notice && <Notice tone="success">{notice}</Notice>}
      {link && <PasswordLinkPanel link={link} name={user.name} />}

      <DetailsSection key={user.updatedAt} user={user} canEdit={has("users.edit")} onSaved={() => setNotice("Details saved.")} />
      <RolesSection
        key={user.roles.map((role) => role.code).join()}
        user={user}
        canEdit={has("users.assignRoles")}
        onSaved={() => setNotice("Roles saved.")}
      />

      <Section
        title="Effective permissions"
        description={
          user.status === "active"
            ? "Everything the user's active roles grant together."
            : "None: an inactive user has no access, whatever their roles."
        }
      >
        <PermissionGroups codes={user.permissions} />
      </Section>

      <AccessSection
        user={user}
        self={self}
        onNotice={setNotice}
        onLink={(issued) => {
          setNotice(null);
          setLink(issued);
        }}
      />
    </div>
  );
}

function DetailsSection({ user, canEdit, onSaved }: { user: AdminUserDetail; canEdit: boolean; onSaved: () => void }) {
  const [name, setName] = useState(user.name);
  const [email, setEmail] = useState(user.email);
  const [image, setImage] = useState(user.image ?? "");
  const save = useAdminMutation((body: { name: string; email: string; image: string | null }) => updateUser(user.id, body));
  const dirty = name !== user.name || email !== user.email || image !== (user.image ?? "");
  const otherError =
    save.error && !fieldError(save.error, "email") && !fieldError(save.error, "name") && !fieldError(save.error, "image");

  return (
    <Section title="Details">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate({ name: name.trim(), email: email.trim(), image: image.trim() || null }, { onSuccess: onSaved });
        }}
        className="space-y-3"
      >
        {otherError && <Notice tone="error">{describeAdminError(save.error)}</Notice>}
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField label="Name" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} disabled={!canEdit} error={fieldError(save.error, "name")} />
          <TextField label="Email address" type="email" required maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} disabled={!canEdit} error={fieldError(save.error, "email")} />
          <div className="sm:col-span-2">
            <TextField
              label="Picture URL (optional)"
              type="url"
              pattern="https://.*"
              maxLength={2000}
              value={image}
              onChange={(e) => setImage(e.target.value)}
              disabled={!canEdit}
              error={fieldError(save.error, "image")}
              hint="An https:// address. Initials are shown when empty."
            />
          </div>
        </div>
        {canEdit && (
          <div className="flex justify-end">
            <Button type="submit" size="sm" disabled={!dirty || save.isPending}>
              {save.isPending ? "Saving…" : "Save details"}
            </Button>
          </div>
        )}
      </form>
    </Section>
  );
}

function RolesSection({ user, canEdit, onSaved }: { user: AdminUserDetail; canEdit: boolean; onSaved: () => void }) {
  const { has } = usePermissions();
  const roles = useRoles(has("roles.view"));
  const current = user.roles.map((role) => role.code);
  const [selected, setSelected] = useState<string[]>(current);
  const save = useAdminMutation((codes: string[]) => setUserRoles(user.id, codes));
  const dirty = selected.length !== current.length || selected.some((code) => !current.includes(code));

  return (
    <Section title="Roles" description="The user's access is the combination of every active role they hold.">
      {save.error && <div className="mb-3"><Notice tone="error">{describeAdminError(save.error)}</Notice></div>}
      {canEdit && roles.data ? (
        <>
          <RolePicker roles={roles.data} selected={selected} onChange={setSelected} disabled={save.isPending} />
          <div className="mt-3 flex justify-end">
            <Button size="sm" disabled={!dirty || save.isPending} onClick={() => save.mutate(selected, { onSuccess: onSaved })}>
              {save.isPending ? "Saving…" : "Save roles"}
            </Button>
          </div>
        </>
      ) : user.roles.length === 0 ? (
        <p className="text-sm text-muted-foreground">No roles.</p>
      ) : (
        <ul className="flex flex-wrap gap-1.5">
          {user.roles.map((role) => (
            <li key={role.code}>
              <StatusBadge tone="info">{role.name}</StatusBadge>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function AccessSection({
  user,
  self,
  onNotice,
  onLink,
}: {
  user: AdminUserDetail;
  self: boolean;
  onNotice: (message: string) => void;
  onLink: (link: PasswordLink) => void;
}) {
  const { has } = usePermissions();
  const [confirming, setConfirming] = useState(false);
  const status = useAdminMutation((active: boolean) => setUserActive(user.id, active));
  const issue = useAdminMutation(() => issuePasswordLink(user.id));
  const active = user.status === "active";
  const canToggle = active ? has("users.deactivate") : has("users.activate");
  const canIssue = has("users.edit") && active;
  if (!canToggle && !canIssue) return null;

  return (
    <Section title="Access">
      <div className="space-y-3">
        {(status.error || issue.error) && <Notice tone="error">{describeAdminError(status.error ?? issue.error)}</Notice>}
        {canIssue && (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground">
              {user.passwordSet
                ? "Issue a one-time link for the user to choose a new password. Earlier links stop working."
                : "The user has not set a password yet. Issue a new setup link if the first was lost or expired."}
            </p>
            <Button variant="outline" size="sm" disabled={issue.isPending} onClick={() => issue.mutate(undefined, { onSuccess: onLink })}>
              {user.passwordSet ? "Issue password reset link" : "Issue new setup link"}
            </Button>
          </div>
        )}
        {canToggle && (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground">
              {active
                ? "Deactivating ends the user's sessions and stops them signing in. Their name stays on records and history."
                : "Activating lets the user sign in again with their roles."}
            </p>
            {active && !confirming ? (
              <Button variant="outline" size="sm" disabled={self} title={self ? "You cannot deactivate yourself." : undefined} onClick={() => setConfirming(true)}>
                Deactivate user
              </Button>
            ) : active ? (
              <span className="flex gap-2">
                <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
                  Cancel
                </Button>
                <Button
                  size="sm"
                  className="bg-destructive text-white hover:bg-destructive/90"
                  disabled={status.isPending}
                  onClick={() =>
                    status.mutate(false, {
                      onSuccess: () => {
                        setConfirming(false);
                        onNotice(`${user.name} was deactivated.`);
                      },
                    })
                  }
                >
                  Confirm deactivation
                </Button>
              </span>
            ) : (
              <Button size="sm" disabled={status.isPending} onClick={() => status.mutate(true, { onSuccess: () => onNotice(`${user.name} was activated.`) })}>
                Activate user
              </Button>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}
