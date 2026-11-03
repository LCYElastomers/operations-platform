---
name: deploy-ubuntu
description: >-
  Ubuntu production deploy for the Operations Platform Docker Compose stack
  (git pull, build, alembic upgrade, readiness, cutover compare). Use when the
  user asks how to deploy, ship, release, or roll out changes to production or
  the Ubuntu server, or how to run migrations on the live host.
---

# Deploy Ubuntu

Canonical runbook: [`docs/deploy-ubuntu.md`](../../../docs/deploy-ubuntu.md).

When the user asks how to deploy:

1. Open that runbook and follow it (do not invent a different host layout).
2. Remind them: **commit and push from the workstation first** — production only pulls from Git.
3. Always include: backup → `git pull` → `docker compose build` → `up -d` → `alembic upgrade head` → `/api/v1/health/ready`.
4. Call out release-specific extras (new schema, `.env`, compare/import) from the runbook or the current change set.
5. For Incident record SOT / migration `0019`, use the **0019 checklist** in the runbook (`compare_derived` before heavy edits).
6. Do not echo production passwords or full `DATABASE_URL` values into chat or commands.

If `$APP` path on the server is unknown, use `/path/to/operations-platform` and ask them to substitute the real directory that contains `compose.yml`.
