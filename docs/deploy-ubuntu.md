# Ubuntu production deploy (Docker Compose)

How to put Git changes live on the Ubuntu host that runs this stack.

**Stack assumptions**

- App lives in a directory that contains `compose.yml` (call it `$APP` below).
- API and web run in Docker Compose; PostgreSQL is **host-managed** (not in Compose).
- Server `.env` stays on the host and is **never** committed.
- Application DB role is typically `operations_api`; database is typically `operations_platform`.

Replace `/path/to/operations-platform` with the real `$APP` path on the server.

---

## Before every production deploy

1. **Commit and push from your workstation** (this machine). Production only gets what is on the remote.
2. **Confirm the target revision** (`git log -1 --oneline` after push).
3. **Back up** `operations_platform` with the DBA procedure. Do not migrate without a restore-capable backup.
4. Note whether the release needs a **new PostgreSQL schema** (rare; Alembic does not create schemas). If it does, create and grant it as a DBA **before** `alembic upgrade`.

---

## Standard deploy steps (every release)

Run on the Ubuntu server unless noted.

### 1. Pull

```bash
cd /path/to/operations-platform
git status
git pull
git log -1 --oneline
```

Do not edit application files inside the containers. Keep `.env` as-is unless the release notes require new variables.

### 2. Rebuild and restart

```bash
docker compose build
docker compose up -d
docker compose ps
```

Both `api` and `web` should become **healthy**.

### 3. Migrate

```bash
docker compose exec api alembic current
docker compose exec api alembic upgrade head
docker compose exec api alembic current
```

Expect the new revision as `(head)`.

### 4. Readiness

```bash
curl -sS http://127.0.0.1:8000/api/v1/health/ready
```

Want `"status":"ready"`. If you see `migrations_pending`, the upgrade did not finish or the container is still on old code.

### 5. Smoke-check in the browser

Sign in and exercise the pages touched by the release. Prefer a hard refresh after a web rebuild.

### 6. Record what you shipped

Write down: commit SHA, `alembic current`, time, and any compare/import command output.

---

## Rollback (high level)

- **Code only (migration not applied or unused by old code):** redeploy the previous Git revision (`git checkout <sha>`, then `docker compose build && docker compose up -d`).
- **After a migration that holds data:** many revisions **refuse downgrade** once tables have rows. Restore the database backup, then redeploy the matching code. Do not delete production rows by hand.
- Prefer restore over `alembic downgrade` for production.

---

## Release checklist: Incident records as source of truth (migration `0019`)

Use this **in addition to** the standard steps above.

| Item | Notes |
| ---- | ----- |
| Migration | `0019` — junction tables under existing `safety` schema |
| New schema? | **No** — do not create schemas for this release |
| New `.env` keys? | **No** |
| Behavior tagging | Unchanged — leave alone |
| Cutover risk | First record write in a month rebuilds that month’s **derived** monthly cells from active records |

### Recommended order for `0019`

1. Workstation: commit + push the approved change set (includes `0019`, aggregation, UI).
2. Server: backup → pull → build → up → `alembic upgrade head` → ready check.
3. **Before heavy editing**, compare stored monthly totals to what records would produce (read-only, no writes):

   ```bash
   docker compose exec api python -m app.safety.records.compare_derived --year 2026
   # optional: --month 10   or   --json
   ```

   Review: stored vs derived vs difference vs supporting record numbers. Do **not** invent synthetic records to force a match.
4. Browser smoke:
   - Incident & Near Miss Data Entry: top totals open the month record list (cell click and Records row).
   - Lower tables (classification, area, injury cause, body part, event cause, LOPC, PSIF, etc.) are **not** editable.
   - Create/edit a First Aid record: Injury Cause and Body Part required; Event Cause available.
   - Annual Behavior tagging still editable and separate.
   - Safety Performance still uses hours you enter; numerators follow the same monthly classification values as the grids after rebuild.
5. Only after compare review, continue normal record entry. Editing/voiding/reclassifying rebuilds affected months automatically.

### `0019` rollback notes

- Downgrade refuses if any tag rows exist (`Cannot downgrade: incident record tags exist`).
- Rollback after use: restore the pre-deploy backup, then redeploy the previous Git revision.

---

## Useful commands

```bash
# Logs
docker compose logs -f api
docker compose logs -f web

# Shell in API container
docker compose exec api bash

# Migration history
docker compose exec api alembic history

# Host DB as DBA (example; use your real auth method)
sudo -u postgres psql -d operations_platform
```

---

## Related docs

- Local Compose and Alembic overview: [`README.md`](../README.md)
- Older Safety 0009 rollout notes: [`docs/safety-release-0009/rollout-plan.md`](safety-release-0009/rollout-plan.md)
