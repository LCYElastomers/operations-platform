"use client";

import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import { usePermissions } from "@/features/auth/use-session";

import { describeNotificationsError, updateSettings } from "./api";
import { Notice, Section } from "./notifications-shared";
import { useNotificationSettings, useNotificationsMutation } from "./use-notifications";

export function SettingsPage({ title, description }: { title: string; description?: string }) {
  const { has } = usePermissions();
  const canManage = has("notifications.settings.manage");
  const settings = useNotificationSettings();
  const [pause, setPause] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (settings.data) setPause(settings.data.emergencyPause);
  }, [settings.data]);

  const save = useNotificationsMutation(() => updateSettings({ emergencyPause: pause }));

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Administration" title={title} description={description} />

      {settings.isError ? (
        <EmptyState
          icon={AlertTriangle}
          title="Settings could not be loaded"
          description={describeNotificationsError(settings.error)}
        />
      ) : settings.isPending ? (
        <p className="py-6 text-sm text-muted-foreground">Loading settings…</p>
      ) : (
        <>
          {message && <Notice tone={message.tone}>{message.text}</Notice>}

          <Section
            title="Environment configuration"
            description="These values come from server environment variables and cannot be changed in the UI."
          >
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <Field label="Provider" value={settings.data.provider || "none"} />
              <Field
                label="API key"
                value={settings.data.apiKeyConfigured ? "Configured" : "Not configured"}
                badge={
                  <StatusBadge tone={settings.data.apiKeyConfigured ? "success" : "danger"}>
                    {settings.data.apiKeyConfigured ? "Set" : "Missing"}
                  </StatusBadge>
                }
              />
              <Field label="Email enabled" value={settings.data.emailEnabled ? "Yes" : "No"} />
              <Field label="Delivery mode" value={settings.data.deliveryMode} />
              <Field label="From name" value={settings.data.emailFromName ?? "—"} />
              <Field label="From address" value={settings.data.emailFromAddress ?? "—"} />
              <Field label="Reply-To" value={settings.data.emailReplyTo ?? "—"} />
              <Field label="Redirect to" value={settings.data.emailRedirectTo ?? "—"} />
            </dl>
          </Section>

          <Section
            title="Emergency pause"
            description="When paused, the worker will not send new email. Existing business events are still recorded."
          >
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4"
                checked={pause}
                disabled={!canManage}
                onChange={(e) => setPause(e.target.checked)}
              />
              Pause all shared email delivery
            </label>
            {canManage && (
              <div className="mt-3">
                <Button
                  disabled={save.isPending || pause === settings.data.emergencyPause}
                  onClick={() =>
                    save.mutate(undefined, {
                      onSuccess: () =>
                        setMessage({
                          tone: "success",
                          text: pause ? "Emergency pause is on." : "Emergency pause is off.",
                        }),
                      onError: (error) => setMessage({ tone: "error", text: describeNotificationsError(error) }),
                    })
                  }
                >
                  Save pause setting
                </Button>
              </div>
            )}
          </Section>
        </>
      )}
    </div>
  );
}

function Field({ label, value, badge }: { label: string; value: string; badge?: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs tracking-wide text-muted-foreground uppercase">{label}</dt>
      <dd className="mt-0.5 flex flex-wrap items-center gap-2">
        <span>{value}</span>
        {badge}
      </dd>
    </div>
  );
}
