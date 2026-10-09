"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { buttonVariants, Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";

import { checkPasswordLink, errorMessage, setPasswordWithLink } from "./api";
import { AuthCard, Field, FormError } from "./auth-card";

export const MIN_PASSWORD_LENGTH = 12;

type State =
  | { kind: "checking" }
  | { kind: "invalid"; message: string }
  | { kind: "ready"; token: string; name: string; email: string }
  | { kind: "done" };

/** Reads the one-time token from the address fragment, then removes it from the address bar and history. */
function takeToken(): string | null {
  const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
  window.history.replaceState(null, "", window.location.pathname);
  return token;
}

const INVALID = "This link is invalid, has expired or has already been used. Ask an administrator for a new one.";

export function SetupPasswordForm() {
  const [state, setState] = useState<State>({ kind: "checking" });
  const tokenRef = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    if (tokenRef.current === undefined) tokenRef.current = takeToken();
    const token = tokenRef.current;
    if (!token) {
      queueMicrotask(() => setState({ kind: "invalid", message: INVALID }));
      return;
    }
    checkPasswordLink(token).then(
      (user) => setState({ kind: "ready", token, ...user }),
      (error: unknown) => setState({ kind: "invalid", message: errorMessage(error, INVALID) }),
    );
  }, []);

  if (state.kind === "checking") {
    return (
      <AuthCard title="Set your password">
        <p className="text-sm text-muted-foreground">Checking your link…</p>
      </AuthCard>
    );
  }
  if (state.kind === "invalid") {
    return (
      <AuthCard title="This link cannot be used">
        <FormError>{state.message}</FormError>
        <Link href="/login" className={buttonVariants({ variant: "outline", className: "mt-4 w-full" })}>
          Go to sign in
        </Link>
      </AuthCard>
    );
  }
  if (state.kind === "done") {
    return (
      <AuthCard title="Password set" description="Your password has been saved. Sign in to continue.">
        <Link href="/login" className={buttonVariants({ className: "w-full" })}>
          Sign in
        </Link>
      </AuthCard>
    );
  }
  return <PasswordForm token={state.token} name={state.name} email={state.email} onDone={() => setState({ kind: "done" })} />;
}

function PasswordForm({ token, name, email, onDone }: { token: string; name: string; email: string; onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      await setPasswordWithLink(token, password);
      onDone();
    } catch (caught) {
      setPending(false);
      setError(
        caught instanceof ApiError && caught.detail?.error === "weak_password"
          ? (caught.detail.message ?? "Choose a stronger password.")
          : errorMessage(caught, INVALID),
      );
    }
  };

  return (
    <AuthCard title="Set your password" description={`For ${name} (${email}).`}>
      <form onSubmit={submit} className="space-y-4">
        {error && <FormError>{error}</FormError>}
        <input type="email" name="username" autoComplete="username" value={email} readOnly hidden />
        <Field
          label="New password"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD_LENGTH}
          autoFocus
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={pending}
          hint={`At least ${MIN_PASSWORD_LENGTH} characters. A passphrase of several words works well.`}
        />
        <Field
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
          disabled={pending}
        />
        <Button type="submit" className="w-full" disabled={pending}>
          {pending ? "Saving…" : "Set password"}
        </Button>
      </form>
    </AuthCard>
  );
}
