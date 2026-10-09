"use client";

import { useState } from "react";

import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { UserAvatar } from "@/components/layout/user-menu";
import { Notice, PermissionGroups, Section, TextField } from "@/features/admin/admin-shared";
import { ApiError } from "@/lib/api-client";

import { changePassword, errorMessage } from "./api";
import { MIN_PASSWORD_LENGTH } from "./setup-password-form";
import { useSession } from "./use-session";

export function ProfilePage({ title, description }: { title: string; description?: string }) {
  const session = useSession();
  if (!session.data) return null;
  const { user, roles, permissions } = session.data;

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Account" title={title} description={description} />
      <Section title="Your account">
        <div className="flex items-center gap-3">
          <UserAvatar user={user} className="size-12 text-base" />
          <div className="min-w-0">
            <p className="font-semibold">{user.name}</p>
            <p className="text-sm text-muted-foreground">{user.email}</p>
          </div>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          Your name, email address and roles are managed by platform administrators.
        </p>
      </Section>
      <Section title="Roles" description="Your access is the combination of these roles.">
        {roles.length === 0 ? (
          <p className="text-sm text-muted-foreground">No roles assigned.</p>
        ) : (
          <ul className="flex flex-wrap gap-1.5">
            {roles.map((role) => (
              <li key={role.code}>
                <StatusBadge tone="info">{role.name}</StatusBadge>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Permissions">
        <PermissionGroups codes={[...permissions]} />
      </Section>
      <ChangePassword email={user.email} />
    </div>
  );
}

function ChangePassword({ email }: { email: string }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<{ field: string | null; message: string } | null>(null);
  const [done, setDone] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setDone(false);
    if (next !== confirm) {
      setError({ field: "confirm", message: "The two new passwords do not match." });
      return;
    }
    setPending(true);
    setError(null);
    try {
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      setDone(true);
    } catch (caught) {
      const field = caught instanceof ApiError && typeof caught.detail?.field === "string" ? caught.detail.field : null;
      setError({ field, message: errorMessage(caught, "The password could not be changed.") });
    } finally {
      setPending(false);
    }
  };

  return (
    <Section title="Change password" description="Changing your password signs you out everywhere else.">
      <form onSubmit={submit} className="max-w-md space-y-3">
        {done && <Notice tone="success">Your password was changed. Your other sessions were signed out.</Notice>}
        {error && error.field === null && <Notice tone="error">{error.message}</Notice>}
        <input type="email" name="username" autoComplete="username" value={email} readOnly hidden />
        <TextField
          label="Current password"
          type="password"
          autoComplete="current-password"
          required
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
          disabled={pending}
          error={error?.field === "currentPassword" ? error.message : null}
        />
        <TextField
          label="New password"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD_LENGTH}
          value={next}
          onChange={(event) => setNext(event.target.value)}
          disabled={pending}
          hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
          error={error?.field === "newPassword" ? error.message : null}
        />
        <TextField
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
          disabled={pending}
          error={error?.field === "confirm" ? error.message : null}
        />
        <Button type="submit" disabled={pending}>
          {pending ? "Changing…" : "Change password"}
        </Button>
      </form>
    </Section>
  );
}
