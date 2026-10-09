"use client";

import { AlertTriangle, Lock, Plus, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { usePermissions } from "@/features/auth/use-session";
import { ApiError } from "@/lib/api-client";

import {
  createRole,
  deleteRole,
  describeAdminError,
  ROLE_CODE_PATTERN,
  setRolePermissions,
  updateRole,
  type PermissionInfo,
  type Role,
} from "./api";
import { Notice, PermissionGroups, Section, TextField, inputClass } from "./admin-shared";
import { useAdminMutation, usePermissionCatalog, useRoles } from "./use-admin";

function fieldError(error: unknown, field: string): string | null {
  return error instanceof ApiError && error.detail?.field === field ? (error.detail.message ?? null) : null;
}

export function RolesPage({ title, description }: { title: string; description?: string }) {
  const { has } = usePermissions();
  const roles = useRoles();
  const catalog = usePermissionCatalog();
  const [creating, setCreating] = useState(false);
  const [openCode, setOpenCode] = useState<string | null>(null);
  const open = roles.data?.find((role) => role.code === openCode) ?? null;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Administration"
        title={title}
        description={description}
        actions={
          has("roles.create") && (
            <Button onClick={() => setCreating(true)} className="pointer-coarse:h-11">
              <Plus />
              Add role
            </Button>
          )
        }
      />

      {roles.isError ? (
        <EmptyState icon={AlertTriangle} title="Roles could not be loaded" description={describeAdminError(roles.error)} />
      ) : roles.isPending ? (
        <p className="py-6 text-sm text-muted-foreground">Loading roles…</p>
      ) : roles.data.length === 0 ? (
        <EmptyState icon={ShieldCheck} title="No roles" />
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {roles.data.map((role) => (
            <li key={role.code}>
              <button
                type="button"
                onClick={() => setOpenCode(role.code)}
                className="flex h-full w-full flex-col rounded-lg border bg-card p-4 text-left shadow-xs transition-colors hover:border-ring/60 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
              >
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{role.name}</span>
                  <span className="font-mono text-xs text-muted-foreground">{role.code}</span>
                  {role.isSystem && (
                    <StatusBadge tone="info">
                      <Lock className="size-3" />
                      System
                    </StatusBadge>
                  )}
                  {!role.active && <StatusBadge>Inactive</StatusBadge>}
                </span>
                <span className="mt-1 flex-1 text-sm text-muted-foreground">{role.description || "No description."}</span>
                <span className="mt-3 text-xs text-muted-foreground">
                  {role.permissions.length} permission{role.permissions.length === 1 ? "" : "s"} · {role.userCount} active user
                  {role.userCount === 1 ? "" : "s"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {creating && (
        <CreateRoleDialog
          catalog={catalog.data}
          onClose={() => setCreating(false)}
          onCreated={(code) => {
            setCreating(false);
            setOpenCode(code);
          }}
        />
      )}
      <Dialog open={open !== null} onClose={() => setOpenCode(null)} title={open?.name ?? "Role"} description={open?.code}>
        {open && <RoleDetail key={open.code} role={open} catalog={catalog.data} onDeleted={() => setOpenCode(null)} />}
      </Dialog>
    </div>
  );
}

function CreateRoleDialog({
  catalog,
  onClose,
  onCreated,
}: {
  catalog?: PermissionInfo[];
  onClose: () => void;
  onCreated: (code: string) => void;
}) {
  const { has } = usePermissions();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const create = useAdminMutation(createRole);
  const canAssign = has("roles.assignPermissions");
  const codeInvalid = code !== "" && !ROLE_CODE_PATTERN.test(code);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (codeInvalid) return;
    create.mutate(
      { code, name: name.trim(), description: description.trim(), permissions: canAssign ? [...selected] : [] },
      { onSuccess: (role) => onCreated(role.code) },
    );
  };
  const otherError = create.error && !fieldError(create.error, "code") && !fieldError(create.error, "name");

  return (
    <Dialog
      open
      onClose={onClose}
      title="Add role"
      description="A role is a named set of permissions. Users can hold several roles; their access is the combination."
      className="sm:w-[min(60rem,calc(100vw-2rem))]"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="create-role" disabled={create.isPending || codeInvalid}>
            {create.isPending ? "Adding…" : "Add role"}
          </Button>
        </div>
      }
    >
      <form id="create-role" onSubmit={submit} className="space-y-4">
        {otherError && <Notice tone="error">{describeAdminError(create.error)}</Notice>}
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="Code"
            required
            maxLength={50}
            value={code}
            onChange={(event) => setCode(event.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_"))}
            error={codeInvalid ? "Capital letters, digits and underscores, starting with a letter." : fieldError(create.error, "code")}
            hint="For example QUALITY_REVIEWER. Cannot be changed later."
          />
          <TextField label="Name" required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} error={fieldError(create.error, "name")} />
        </div>
        <label className="block space-y-1">
          <span className="text-sm font-medium">Description</span>
          <textarea
            maxLength={1000}
            rows={2}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className={`${inputClass} h-auto py-2`}
          />
        </label>
        {canAssign && catalog && (
          <Section title="Permissions">
            <PermissionGroups
              codes={catalog.map((p) => p.code)}
              catalog={catalog}
              selected={selected}
              onToggle={(permission) =>
                setSelected((current) => {
                  const next = new Set(current);
                  if (!next.delete(permission)) next.add(permission);
                  return next;
                })
              }
              disabled={create.isPending}
            />
          </Section>
        )}
      </form>
    </Dialog>
  );
}

function RoleDetail({ role, catalog, onDeleted }: { role: Role; catalog?: PermissionInfo[]; onDeleted: () => void }) {
  const { has } = usePermissions();
  const [notice, setNotice] = useState<string | null>(null);
  const protectedRole = role.code === "ADMIN";

  return (
    <div className="space-y-4">
      {role.isSystem && (
        <p className="flex items-start gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          <Lock className="mt-0.5 size-4 shrink-0" />
          {protectedRole
            ? "The Administrator role always grants every permission. It cannot be renamed, deactivated or deleted."
            : "A standard role. It keeps its name and cannot be deleted; its description, permissions and active state can be changed."}
        </p>
      )}
      {notice && <Notice tone="success">{notice}</Notice>}
      <RoleSettings
        key={`${role.name}:${role.description}:${role.active}`}
        role={role}
        canEdit={has("roles.edit")}
        onSaved={() => setNotice("Role saved.")}
      />
      <RolePermissions
        key={role.permissions.join()}
        role={role}
        catalog={catalog}
        canEdit={has("roles.assignPermissions") && !protectedRole}
        onSaved={() => setNotice("Permissions saved.")}
      />
      {has("roles.delete") && !role.isSystem && <DeleteRole role={role} onDeleted={onDeleted} />}
    </div>
  );
}

function RoleSettings({ role, canEdit, onSaved }: { role: Role; canEdit: boolean; onSaved: () => void }) {
  const [name, setName] = useState(role.name);
  const [description, setDescription] = useState(role.description);
  const [active, setActive] = useState(role.active);
  const save = useAdminMutation((body: { name: string; description: string; active: boolean }) => updateRole(role.code, body));
  const dirty = name !== role.name || description !== role.description || active !== role.active;

  return (
    <Section title="Role">
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate({ name: name.trim(), description: description.trim(), active }, { onSuccess: onSaved });
        }}
      >
        {save.error && !fieldError(save.error, "name") && <Notice tone="error">{describeAdminError(save.error)}</Notice>}
        <TextField
          label="Name"
          required
          maxLength={100}
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={!canEdit || role.isSystem}
          error={fieldError(save.error, "name")}
        />
        <label className="block space-y-1">
          <span className="text-sm font-medium">Description</span>
          <textarea
            maxLength={1000}
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={!canEdit}
            className={`${inputClass} h-auto py-2`}
          />
        </label>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-0.5 size-4" checked={active} onChange={(e) => setActive(e.target.checked)} disabled={!canEdit || role.code === "ADMIN"} />
          <span>
            Active
            <span className="block text-xs text-muted-foreground">An inactive role grants nothing to the users who hold it.</span>
          </span>
        </label>
        {canEdit && (
          <div className="flex justify-end">
            <Button type="submit" size="sm" disabled={!dirty || save.isPending}>
              {save.isPending ? "Saving…" : "Save role"}
            </Button>
          </div>
        )}
      </form>
    </Section>
  );
}

function RolePermissions({
  role,
  catalog,
  canEdit,
  onSaved,
}: {
  role: Role;
  catalog?: PermissionInfo[];
  canEdit: boolean;
  onSaved: () => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set(role.permissions));
  const save = useAdminMutation((permissions: string[]) => setRolePermissions(role.code, permissions));
  const dirty = selected.size !== role.permissions.length || role.permissions.some((p) => !selected.has(p));

  return (
    <Section title="Permissions" description={`${role.permissions.length} granted.`}>
      {save.error && <div className="mb-3"><Notice tone="error">{describeAdminError(save.error)}</Notice></div>}
      {canEdit && catalog ? (
        <>
          <PermissionGroups
            codes={catalog.map((p) => p.code)}
            catalog={catalog}
            selected={selected}
            onToggle={(permission) =>
              setSelected((current) => {
                const next = new Set(current);
                if (!next.delete(permission)) next.add(permission);
                return next;
              })
            }
            disabled={save.isPending}
          />
          <div className="mt-3 flex justify-end gap-2">
            <Button variant="ghost" size="sm" disabled={!dirty || save.isPending} onClick={() => setSelected(new Set(role.permissions))}>
              Reset
            </Button>
            <Button size="sm" disabled={!dirty || save.isPending} onClick={() => save.mutate([...selected], { onSuccess: onSaved })}>
              {save.isPending ? "Saving…" : "Save permissions"}
            </Button>
          </div>
        </>
      ) : (
        <PermissionGroups codes={role.permissions} catalog={catalog} />
      )}
    </Section>
  );
}

function DeleteRole({ role, onDeleted }: { role: Role; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const remove = useAdminMutation(() => deleteRole(role.code));
  return (
    <Section title="Delete role" description="Only roles that no user holds can be deleted.">
      {remove.error && <div className="mb-3"><Notice tone="error">{describeAdminError(remove.error)}</Notice></div>}
      {confirming ? (
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
            Cancel
          </Button>
          <Button
            size="sm"
            className="bg-destructive text-white hover:bg-destructive/90"
            disabled={remove.isPending}
            onClick={() => remove.mutate(undefined, { onSuccess: onDeleted })}
          >
            Delete {role.name}
          </Button>
        </div>
      ) : (
        <div className="flex justify-end">
          <Button variant="outline" size="sm" onClick={() => setConfirming(true)}>
            Delete role…
          </Button>
        </div>
      )}
    </Section>
  );
}
