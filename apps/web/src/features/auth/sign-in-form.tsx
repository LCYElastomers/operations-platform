"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";

import { signIn } from "./api";
import { AuthCard, Field, FormError } from "./auth-card";

function signInError(error: unknown): string {
  if (!(error instanceof ApiError)) return "The sign-in service could not be reached. Try again shortly.";
  if (error.status === 401 || error.status === 422) return "The email or password is incorrect.";
  if (error.status === 503) return "Sign-in is unavailable because the database could not be reached.";
  return "Sign-in failed. Try again.";
}

export function SignInForm({ next }: { next: string }) {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await signIn(email, password);
      queryClient.clear();
      window.location.assign(next);
    } catch (caught) {
      setPassword("");
      setError(signInError(caught));
      setPending(false);
    }
  };

  return (
    <AuthCard title="Sign in" description="Use the account your platform administrator created for you.">
      <form onSubmit={submit} className="space-y-4">
        {error && <FormError>{error}</FormError>}
        <Field
          label="Email address"
          type="email"
          name="email"
          autoComplete="username"
          required
          autoFocus
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          disabled={pending}
        />
        <Field
          label="Password"
          type="password"
          name="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={pending}
        />
        <Button type="submit" className="w-full" disabled={pending}>
          {pending ? "Signing in…" : "Sign in"}
        </Button>
        <p className="text-xs text-muted-foreground">
          Forgotten your password, or need an account? Ask a platform administrator for a password setup link.
        </p>
      </form>
    </AuthCard>
  );
}
