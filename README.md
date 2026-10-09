# Operations Platform

Modular operations management platform (Quality, Mechanical Integrity,
Safety, and future modules). See [`docs/AGENTS.md`](docs/AGENTS.md) for architecture,
security, and engineering principles.

This repository currently contains the project skeleton only: no
authentication, no data synchronization, and no module dashboards yet.

## Layout

```
apps/
  web/      Next.js (App Router, TypeScript, Tailwind, TanStack Query, shadcn/ui-ready)
  api/      FastAPI (Pydantic, SQLAlchemy 2, Alembic, pytest), managed with uv
connectors/
  access-finishing-sync/  Windows agent: Access qryFINISHING-AVG -> ingestion API
compose.yml Docker Compose stack for web + api
docs/       Project guidelines
```

Connectors are independent applications that run on source-system hosts and
talk to the API only over HTTPS. They are not imported by the API and not
part of any Docker image. See
[`connectors/access-finishing-sync/README.md`](connectors/access-finishing-sync/README.md).

PostgreSQL is host-managed and is **not** part of the Compose stack.

## Prerequisites

- Docker Engine / Docker Desktop with Compose v2.24+
- For running outside Docker: Node.js 24 and [uv](https://docs.astral.sh/uv/)

## Local startup (Docker Compose)

```bash
cp .env.example .env          # optional; defaults work without it
docker compose build
docker compose up -d
docker compose ps             # both services should report "healthy"
```

Then open:

- Frontend: <http://localhost:3000>
- API health: <http://localhost:8000/api/v1/health>
- API docs (non-production only): <http://localhost:8000/api/docs>

Stop the stack with `docker compose down`.

### How the stack is wired

- Both services join a private bridge network (`app`). Published ports are
  bound to `127.0.0.1` only, so nothing is reachable from other machines.
- The browser only talks to the web origin. Requests to `/api/*` are
  forwarded server-side by Next.js to `http://api:8000`, so no backend
  address or credentials reach client code. In production, Nginx will
  front both services the same way.
- Containers run as non-root users (`app`, UID 10001 for the API; `node`,
  UID 1000 for the web), with a read-only root filesystem, all Linux
  capabilities dropped, and `no-new-privileges`.
- Health checks: the API checks `/api/v1/health`; the web container checks
  `/`. The web service waits for the API to be healthy before starting.
- Both services use `restart: unless-stopped`.

Verify containers are not running as root:

```bash
docker compose exec api id    # uid=10001(app)
docker compose exec web id    # uid=1000(node)
```

## Running without Docker

API:

```bash
cd apps/api
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Web (in a second terminal):

```bash
cd apps/web
npm ci
npm run dev                   # http://localhost:3000, proxies /api to localhost:8000
```

Set `API_INTERNAL_URL` before `npm run dev` / `npm run build` to point the
proxy at a different API address.

## Checks

```bash
# API
cd apps/api
uv run pytest
uv run ruff check .
uv run ruff format --check .

# PostgreSQL integration tests (migrations, persistence, repository) are
# skipped unless TEST_DATABASE_URL is set. Two modes (TEST_DATABASE_MODE):
#
# disposable (default): the suite migrates base -> head -> base and wipes data,
# so it only accepts a generated name op_disposable_test_<12 hex>. The runner
# creates that database (with the managed schemas), runs pytest against it and
# drops it afterwards, also on failure. The admin role needs CREATE DATABASE;
# keep its password in PGPASSWORD or ~/.pgpass, not in the URL you type.
DISPOSABLE_DATABASE_ADMIN_URL=postgresql+psycopg://<admin-user>@localhost:5432/postgres \
  uv run python tests/run_disposable_database.py -q
#
# shared: runs against the populated operations_platform_test without
# migrating or wiping it; tests needing an empty database are deselected and
# writes are rolled back. The database must already be at head
# (`uv run alembic upgrade head` with DATABASE_URL pointing at it).
TEST_DATABASE_MODE=shared TEST_DATABASE_URL=<operations_platform_test url> uv run pytest
#
# operations_platform and operations_platform_test are refused in disposable
# mode, and shared mode accepts only operations_platform_test.

# Web
cd apps/web
npm run lint
npm run typecheck
npm test
npm run build
```

## Frontend structure

```
apps/web/src/
  app/                    Routes (App Router). Every page renders inside AppShell.
  config/navigation.ts    Single source of truth for the sidebar, breadcrumbs,
                          module cards, and module descriptions.
  components/layout/      AppShell, AppSidebar, AppHeader
  components/common/      PageHeader, MetricCard, FilterBar, DataTable,
                          TrendChart, BarChart, MonthlyGrid, StatusBadge,
                          EmptyState, DisplayControls
  components/modules/     ModuleNotConfigured (standard page for modules
                          without a connected data source)
  components/system/      API health status
  components/ui/          shadcn/ui primitives and Dialog (native <dialog>:
                          full screen on phones, centred from `sm`)
  lib/                    API client, navigation helpers, utilities
```

To add a module page: register it in `config/navigation.ts`, then create the
route under `src/app`. Until real data is connected, render
`<ModuleNotConfigured href="..." />` rather than sample data.

Data conventions used by the shared components:

- `MetricCard` takes `value: number | null`. `null` renders as "no data";
  `0` renders as `0`.
- `DataTable` renders `null`/`undefined` cells as an explicit dash.
- `TrendChart` points with a `null` value are drawn as gaps, not zeros.

The sidebar is persistent at `lg` (1024px) and wider. Below that it becomes a
drawer opened from the header menu button.

## Configuration

All configuration is via environment variables; see
[`.env.example`](.env.example). `.env` files are git-ignored and excluded
from Docker build contexts. Never commit real credentials.

| Variable       | Used by | Default       | Notes                                   |
| -------------- | ------- | ------------- | --------------------------------------- |
| `WEB_PORT`     | compose | `3000`        | Host port, bound to 127.0.0.1           |
| `API_PORT`     | compose | `8000`        | Host port, bound to 127.0.0.1           |
| `ENVIRONMENT`  | api     | `development` | `production` disables API docs          |
| `LOG_LEVEL`    | api     | `INFO`        |                                         |
| `DATABASE_URL` | api     | _(unset)_     | SQLAlchemy URL for host PostgreSQL      |
| `MOISTURE_DATA_SOURCE` | api | `fixture` | `fixture` or `database`; `database` requires `DATABASE_URL`. Production must use `database` (`fixture` is refused when `ENVIRONMENT=production`) |
| `INGESTION_AUTH_MODE` | api | `disabled` | `disabled`, `connector`, or `development-unauthenticated` (refused in production); see Ingestion API |
| `INGESTION_CONNECTORS` | api | _(empty)_ | JSON connector registry holding secret **digests** only; see Ingestion API |
| `SESSION_IDLE_MINUTES` | api | `480` | A session ends after this long without a request (5–1440) |
| `SESSION_ABSOLUTE_HOURS` | api | `16` | ...and in any case this long after sign-in (1–168) |
| `SESSION_COOKIE_SECURE` | api | `true` | HTTPS-only session cookie. `false` only for local `http://localhost`; refused in production |
| `PASSWORD_LINK_HOURS` | api | `72` | Lifetime of one-time password setup/reset links (1–168) |
| `LOGIN_MAX_FAILURES` | api | `5` | Failed sign-ins before an account is locked (3–20) |
| `LOGIN_LOCK_MINUTES` | api | `15` | How long a locked account stays locked (1–1440) |

Users, roles, role assignments and permissions are never configured here;
see Authorization. `USER_AUTH_MODE` and `DEVELOPMENT_USER_PERMISSIONS` are
retired and ignored.
| `CAR_DUE_SOON_DAYS` | api | `14` | Window (0–365 days) for "due soon" on Corrective Action Reports |

## Database migrations

Alembic is configured in `apps/api/alembic`. It reads `DATABASE_URL` from the
environment; no URL is stored in `alembic.ini`. Register new models in
`app/models/__init__.py` so autogenerate can see them.

```bash
cd apps/api
uv run alembic history
uv run alembic upgrade head
uv run alembic check            # fails if models and migrations have drifted
uv run alembic revision --autogenerate -m "describe change"

# In the deployed stack
docker compose exec api alembic upgrade head
```

Schema changes happen only through Alembic; the API never creates tables at
startup. Autogenerate only inspects application-owned schemas (`core`,
`quality` and `safety`; `core.alembic_version` itself is excluded).

Use a least-privilege database role for the application. From inside the API
container, the host database is reachable as `host.docker.internal`.

Migration sequence: `0001`–`0002` Quality finishing measurements and
ingestion, `0003` audit events and Incident & Near Miss,
`0004` Observations, `0005` Supervisor Safety Contacts (retired, tables
kept), `0006` Safety Performance, `0007` incident dimensions, `0008`
Behavior, `0009` incident records and TRIR history, `0010` Cost of
Quality monthly inputs (`app.quality.cost.legacy_import`), `0011` Quality
Cost records and their related-record references, `0012` Corrective Action
Reports (`app.quality.car.legacy_import`). Migrations seed
reference data only; legacy values are loaded afterwards with the import
CLIs, in this order: incident totals (`app.safety.legacy_import`), Safety
Performance hours, Behavior, TRIR history, then reviewed incident
narratives. Each has `check`, `plan` and `apply`; `apply` is audited and
idempotent.

**Back up before upgrading production.** Downgrades are not a rollback for
data: `0002`–`0012` each refuse to downgrade while their tables hold data,
so restoring the backup is the rollback once anything was imported.
The release runbook and data-quality report for 0009 are in
[`docs/safety-release-0009/`](docs/safety-release-0009/).

### Schemas

The database uses one PostgreSQL schema per area. The schemas are created
by a DBA, not by the application:

| Schema                 | Contents                                         |
| ---------------------- | ------------------------------------------------ |
| `core`                 | Platform tables, including `core.alembic_version` |
| `quality`              | Quality module tables                            |
| `mechanical_integrity` | Reserved                                         |
| `safety`               | Safety module tables                             |
| `environmental`        | Reserved                                         |

Alembic stores its revision in `core.alembic_version` (configured in
`alembic/env.py` from `app/db/base.py`), not in `public.alembic_version`.
The application role intentionally has no `CREATE` privilege on `public`,
so nothing is created there. Every model and migration names its schema
explicitly; Quality tables always go in `quality`.

Privileges the migrating role (`operations_api`) needs:

- `USAGE, CREATE` on `core` (Alembic creates `core.alembic_version` on the
  first upgrade).
- `USAGE, CREATE` on `quality`.
- `USAGE, CREATE` on `safety`.
- No `CREATE` on `public` and no `CREATE` on the database.

```sql
-- Run as a DBA. Schemas already exist in production.
GRANT USAGE, CREATE ON SCHEMA core, quality, safety TO operations_api;
```

Migration `0001` produces `core.alembic_version` and
`quality.finishing_measurements`. Downgrading it drops
`quality.finishing_measurements` and its data. DBA-owned schemas are never
dropped, and `core.alembic_version` remains (empty).

Current revisions:

| Revision | Changes                                                                 |
| -------- | ----------------------------------------------------------------------- |
| `0001`   | Creates `quality.finishing_measurements`                                |
| `0002`   | Creates `core.ingestion_batches`; adds record identity and versioning columns to `quality.finishing_measurements` |
| `0003`   | Creates `core.audit_events`; creates `safety.metric_sections`, `safety.metric_categories`, `safety.monthly_metric_values`; seeds the Incident & Near Miss section and category definitions (no values) |
| `0004`   | Creates `safety.observation_categories` (seeded) and `safety.observations`; seeds the legacy `observations_legacy` metric sections and categories (no values) |
| `0005`   | Creates `safety.contact_supervisors` and `safety.supervisor_safety_contacts`; seeds nothing (no supervisors, contacts or targets) |
| `0006`   | Creates `safety.performance_hours` and `safety.performance_annual_legacy`; seeds the `performance_legacy` metric sections and categories (no hours, annual figures or values) |
| `0007`   | Creates `safety.areas` (seeded); adds `area_id` and `description` to `safety.metric_categories`; seeds seven Incident & Near Miss dimension sections (no values) |
| `0008`   | Creates `safety.behavior_categories` (24, seeded) and `safety.annual_behavior_counts` (no values) |
| `0009`   | Creates `safety.incident_records` and `safety.trir_annual_facts`; seeds nothing and changes no existing table |

Downgrading `0002` drops `core.ingestion_batches` and the versioning
columns. It refuses to run while superseded measurement versions exist,
because they would otherwise become indistinguishable from current rows.

Downgrading `0003` refuses to run while any Safety monthly value or audit
event exists, so entered data and its history are never dropped silently.
Downgrading `0004` likewise refuses while any observation or legacy
observation value exists. Downgrading `0005` refuses while any supervisor or
supervisor safety contact exists. Downgrading `0006` refuses while any
worked-hours row, annual legacy row or `performance_legacy` value exists.
Downgrading `0007` refuses while dimension or area-linked values exist,
`0008` while Behavior counts exist, and `0009` while any incident record or
TRIR history row exists.

Explicit constraint names in migrations are wrapped in `op.f()`; otherwise the
`ck_%(table_name)s_%(constraint_name)s` naming convention prefixes them a
second time.

## Quality > Raw Materials > Moisture Analysis

The dashboard at `/quality/raw-materials/moisture` reads only from the FastAPI
contract below. Code lives in `apps/api/app/quality/moisture/` and
`apps/web/src/features/quality/moisture/`.

| Endpoint                               | Returns                                                                                      |
| -------------------------------------- | -------------------------------------------------------------------------------------------- |
| `GET /api/v1/quality/moisture/lots`    | Newest Product + Lot master rows first, each with its location records (`limit`, default 50, max 500) |
| `GET /api/v1/quality/moisture/trends`  | All matching Product + Lot master rows oldest first, plus summary means                      |
| `GET /api/v1/quality/moisture/recent`  | Newest matching location-level records first (`limit`, default 50, max 500)                  |
| `GET /api/v1/quality/moisture/filters` | Distinct products and locations, and source date boundaries                                  |

`/lots`, `/trends` and `/recent` accept `product` and `location` (exact
match), `search` (case-insensitive substring of lot or campaign number), and
`startDate` / `endDate` (inclusive, `YYYY-MM-DD`). Unknown or invalid
parameters return HTTP 422.

The dashboard's master grain is **Product + Lot**. Location is not part of
the grouping key: one source lot measured at `PKG/0`, `PKG/1` and `SILO/1`
is one master row, and its location records are shown only when the row is
expanded. Master means, lot counts and charts are built from the matching
location-level records (the finest grain the `qryFINISHING-AVG` source
provides), after filtering, so a date or location filter narrows the records
each lot is built from. The same lot text under different products is
different master rows; records without a lot are never merged with each
other. Charts plot one point per lot at its latest measurement date. The
"Lots in view" count is master rows; the location record count is shown
beside it.

Source field mapping (Access query to API):

| Source             | API             |
| ------------------ | --------------- |
| `DATE`             | `date`          |
| `CAMPNO`           | `campaignNo`    |
| `LOT`              | `lot`           |
| `Location`         | `location`      |
| `PRODUCT`          | `product`       |
| `AvgOfMOISTURE`    | `avgMoisture`   |
| `AvgOfCOLOR`       | `avgColor`      |
| `AvgOfCombined_BD` | `avgCombinedBd` |

Data rules:

- `null` measurements mean missing source values and are never treated as `0`.
  Summary and lot means skip nulls, include zeros, and are `null` when no
  values exist. Each mean is unweighted over location-level values, never a
  mean of lot means.
- Measurements are returned at source precision; the UI rounds for display
  and shows the full value on hover.
- Campaign number, lot, and product are identifiers (strings), never numbers.
- Locations are not normalized (`Silo 1` and `SILO 1` are distinct).
- No specification limits or in/out-of-spec classifications exist yet.

### Persistence

Moisture records are stored in `quality.finishing_measurements`, one row per
source query row:

| Column                                         | Type          | Notes                                  |
| ---------------------------------------------- | ------------- | -------------------------------------- |
| `id`                                           | bigint        | Identity primary key                   |
| `source_date`                                  | date          | Not null                               |
| `campaign_no`, `lot`, `location`, `product`    | text          | Nullable, stored exactly as received   |
| `avg_moisture`, `avg_color`, `avg_combined_bd` | numeric       | Nullable, unconstrained precision      |
| `source_system`                                | text          | Not null; name of the delivering system |
| `source_row_hash`                              | text          | Not null; SHA-256 of the source row    |
| `synced_at`                                    | timestamptz   | Not null; when the row was ingested    |
| `created_at`                                   | timestamptz   | Not null; database default `now()`     |
| `source_record_key`                            | text          | Nullable; durable upstream record ID, when the source has one |
| `ingestion_batch_id`                           | bigint        | Nullable; FK to the `core.ingestion_batches` row that wrote (or restored) this version |
| `superseded_at`                                | timestamptz   | Null while current; set when a correction replaces this version |
| `superseded_by_batch_id`                       | bigint        | Nullable; FK to the batch that superseded it |

Each row is one **content version**. `(source_system, source_row_hash)` is
unique, so re-delivering identical content is a no-op. The hash covers all
eight source fields (plus `source_record_key` when present) after
canonicalization: `26101` and `"26101"` hash alike, but `null` and `0`
differ, and text is never trimmed or case-folded.

The hash is **not** the business identity. Corrections are recognized only
through an explicit identity (a source record key or an authoritative date
window; see Corrections below), never by guessing a key from product and
lot. A replaced version is marked superseded, never deleted. At most one
current version exists per `(source_system, source_record_key)` (partial
unique index). The read API (`/recent`, `/trends`, `/filters`) returns only
current versions (`superseded_at IS NULL`).

Float measurements are stored via their shortest round-trip representation
(`0.43333333333333335` stays exactly that), so values read back unchanged.

The API reads from the fixture or the database depending on
`MOISTURE_DATA_SOURCE`. Both implement the same repository interface
(`repository.py`), so the HTTP contract is identical; only
`dataSource.kind` / `isFixture` / `label` change.

Production uses `MOISTURE_DATA_SOURCE=database`; the API refuses to start
with `fixture` when `ENVIRONMENT=production`. In database mode:

- `/recent` returns current versions newest first (`source_date`, then
  insertion order), at most `limit` records (default 50, maximum 500), with
  `totalMatching`.
- `/trends` returns current versions oldest first, with unweighted means of
  non-null Moisture, Color and Combined BD values and their value counts.
- `/filters` returns the distinct non-null products and locations and the
  earliest/latest `source_date` of current versions.
- Product and location filters match raw stored values exactly; `search` is
  a case-insensitive substring match on lot or campaign number; the date
  filter is inclusive.
- Values are returned as stored: identifiers as strings, locations
  un-normalized, `null` distinct from `0`, no specifications or
  classifications.
- Reads include every source system in the table. Each request uses its own
  session, so a committed ingestion batch is visible on the next request.

The database read path is covered end to end (ingestion endpoint, then the
real read dependency) by `apps/api/tests/test_moisture_database_read_path.py`.

### Development fixture

For development and tests (`MOISTURE_DATA_SOURCE=fixture`, the default
outside production), the API serves
`apps/api/app/quality/moisture/fixtures/moisture_development_fixture.json`:
synthetic rows using the Access field names, including deliberate zeros,
nulls, and an un-normalized location. Every response includes a
`dataSource` object with `isFixture: true`, and the dashboard shows a
"Development fixture" badge and banner. The frontend never imports the
fixture directly.

### Ingestion API

`POST /api/v1/ingestion/quality/finishing/batches` receives calculated
results of the Access query `qryFINISHING-AVG` from a machine connector, in
batches. Code: `ingestion_router.py`, `ingestion_service.py`,
`ingestion_schemas.py`, and `FinishingMeasurementWriter` in `repository.py`.

**Authentication** (`app/core/machine_auth.py`). The endpoint fails closed.
Authentication runs before the request body is read.

| `INGESTION_AUTH_MODE`         | Behaviour                                                        |
| ----------------------------- | ---------------------------------------------------------------- |
| `disabled` (default)          | Every request gets `503 ingestion_disabled`                      |
| `connector`                   | Connector credentials required (below)                           |
| `development-unauthenticated` | Local development only. The API refuses to start with it when `ENVIRONMENT=production`; each request logs a warning |

In `connector` mode each request carries two headers:

```
X-Connector-Id: lcy-access-sync
Authorization: Bearer opc_...
```

The connector ID is public; the secret is a 256-bit random token. The
server stores only SHA-256 digests of secrets, in `INGESTION_CONNECTORS`
(environment, never source control):

```json
{
  "lcy-access-sync": {
    "secret_sha256": ["<64 hex digest>"],
    "source_systems": ["access-qryFINISHING-AVG"]
  }
}
```

- Missing headers, an unknown connector ID, and a wrong secret all return
  the same `401 invalid_credentials` with `WWW-Authenticate: Bearer`.
  Unknown IDs are compared against a dummy digest so that response timing
  does not reveal whether the ID exists. Digests are compared with
  `hmac.compare_digest` against a fixed number of slots.
- An authenticated connector may write only to its listed `source_systems`
  (otherwise `403 source_system_not_allowed`).
- The authenticated connector ID is recorded on every audit row.
- Neither headers nor secrets are logged. Rejections log
  `event=machine_auth result=rejected reason=invalid_credentials` and the
  connector ID only if it is a configured one (otherwise `unrecognized`).
- The API refuses to start if `connector` mode has no connectors, a digest
  is malformed, or the same digest is assigned to two connectors.
  Configuration errors never echo the offending values.

Provisioning and rotation:

```bash
cd apps/api
uv run python -m app.core.machine_auth new-secret   # prints a secret and its digest
uv run python -m app.core.machine_auth digest       # digest of an existing secret (prompted, not echoed)
```

1. Give the secret to the connector host through a secure channel. Store it
   there, for example in Windows Credential Manager. Never put it in a repository.
2. Add the digest to `secret_sha256`. When writing JSON in `.env`, wrap the
   value in single quotes.
3. To rotate, add the new digest alongside the old one (up to 5 per
   connector), restart the API, switch the connector to the new secret, then
   remove the old digest. The payload format does not change.

Nginx (or any proxy) in front of the API must not log the `Authorization`
header.

**Request** (`Content-Type: application/json`, at most 5 MiB):

```json
{
  "sourceSystem": "access-qryFINISHING-AVG",
  "batchId": "2026-10-02T16-40-00Z-0001",
  "extractedAt": "2026-10-02T16:40:00Z",
  "reconciliationWindow": { "sourceDateFrom": "2026-09-01", "sourceDateTo": "2026-09-30" },
  "rows": [
    {
      "sourceDate": "2026-09-01",
      "campaignNo": "26101",
      "lot": "A260901-01",
      "location": "Silo 1",
      "product": "PRD-A",
      "avgMoisture": 0,
      "avgColor": null,
      "avgCombinedBd": 0.7123456789012345678
    }
  ]
}
```

| Field          | Rules                                                                    |
| -------------- | ------------------------------------------------------------------------ |
| `sourceSystem` | 1-100 chars: letters, digits, `.` `_` `:` `-`; starts with letter/digit   |
| `batchId`      | Same rules. Chosen by the connector; unique per `sourceSystem` (see Batch auditing) |
| `extractedAt`  | ISO 8601 date-time **with** a timezone offset; when the source was read  |
| `reconciliationWindow` | Optional. `sourceDateFrom` / `sourceDateTo` (`YYYY-MM-DD`, inclusive, from <= to). Declares the batch the complete source content for that range (strategy B) |
| `rows`         | 1 to 5000 row objects                                                    |

| Row field       | Source (`qryFINISHING-AVG`) | Rules                                                     |
| --------------- | --------------------------- | --------------------------------------------------------- |
| `sourceDate`    | `DATE`                      | Required, non-null, `YYYY-MM-DD`                          |
| `campaignNo`    | `CAMPNO`                    | String or null (integers accepted, stored as exact text)  |
| `lot`           | `LOT`                       | String or null, at most 200 chars                         |
| `location`      | `Location`                  | String or null, at most 200 chars                         |
| `product`       | `PRODUCT`                   | String or null, at most 200 chars                         |
| `avgMoisture`   | `AvgOfMOISTURE`             | JSON number or null                                       |
| `avgColor`      | `AvgOfCOLOR`                | JSON number or null                                       |
| `avgCombinedBd` | `AvgOfCombined_BD`          | JSON number or null                                       |
| `sourceRecordId` | —                         | Optional. Durable upstream record ID (strategy A); non-empty string or integer, at most 200 chars |
| `sourceRowHash` | —                           | Optional. If sent, must equal the server-computed hash    |

Every row field except `sourceRecordId` and `sourceRowHash` must be present;
send `null` explicitly for a missing value. Unknown fields are rejected. Values are
stored exactly as sent: no trimming, case changes, or location
normalization; JSON numbers are parsed as exact decimals (no float
rounding); `null` is stored as NULL, never as 0. Numbers are not
range-checked: there are no specifications, thresholds, or outlier rules.

**Idempotency.** The server computes `source_row_hash` (SHA-256 over the
canonicalized row; see `compute_source_row_hash`). Content versions are
unique on `(sourceSystem, source_row_hash)`, so re-sending rows or
overlapping batches never creates duplicates. Re-sending a completed batch
with the same `batchId` and identical content replays the stored result
(`replayed: true`) without touching data.

**Corrections.** `qryFINISHING-AVG` is an aggregate. Correcting an
underlying record changes an existing aggregate row, so the corrected row
hashes differently. The hash alone cannot tell a correction from a new row.
The service therefore treats content (`source_row_hash`) and identity
separately and supports three modes, chosen by the connector per batch or
row:

| Mode | Triggered by | Behaviour |
| ---- | ------------ | --------- |
| A. Record identity | `sourceRecordId` on a row | The row is the current version of that record. A different current version is superseded; an identical one is a duplicate; an earlier version is restored. One record may not appear twice with different values in a batch |
| B. Authoritative window | `reconciliationWindow` on the batch | The batch is the complete content for that source-date range. Rows outside the range are rejected. Current rows in the range whose content is not in the batch are superseded; earlier versions present in the batch are restored. Applied **only if no row in the batch was rejected** (`windowApplied`); otherwise valid rows are inserted and nothing is superseded |
| Append (legacy) | neither | Rows are added idempotently and never supersede anything. A changed row becomes an additional current row. Not suitable for corrections |

Safeguards:

- Nothing is deleted. Superseded versions keep `superseded_at` and
  `superseded_by_batch_id` for history and audit.
- Batches for one `sourceSystem` are applied one at a time
  (transaction-scoped advisory lock).
- Out-of-order delivery is refused with `409 stale_batch`. This applies to a
  window batch when an overlapping window from a later `extractedAt` has
  already been applied, and to a keyed row when its record already has a
  version from a later extraction. Nothing is written, and the audit row
  records `error_code = stale_batch`.
- A window batch must contain at least one row, so a faulty empty extract
  cannot supersede a whole range.
- No business key is guessed: the same product and lot on different dates
  or locations are distinct rows.

**Recommended strategy for `qryFINISHING-AVG`: B (authoritative window).**
The query's output has no durable row identity. Its rows are averages
grouped by date, campaign, lot, location and product, and identical lots
can occur across dates and locations. The sync agent should, on each run:

1. Re-run the query for a trailing date range long enough to cover
   late corrections (for example the last 60 days; agree the length with
   the Quality owner).
2. Send all result rows for that range with `reconciliationWindow` set to
   exactly the range queried. Split by date into consecutive windows if it
   exceeds 5000 rows, and never split one date across batches.
3. Use a deterministic `batchId` per run and window, so a retried request
   replays instead of re-applying.
4. Treat `windowApplied: false` as an alert: fix the rejected rows at the
   source and re-send the window with a new `batchId`.

Use strategy A only if the source owner confirms a column that uniquely and
permanently identifies each output row. Append mode remains only for
compatibility with the original contract.

**Batch auditing.** Every batch that passes authentication and envelope
validation gets one row in `core.ingestion_batches`. The row stores
metadata only: `batch_id`, `source_system`, `connector_id`, `extracted_at`,
`received_at`, `completed_at`, `status`, row counts (`received`, `inserted`,
`duplicate`, `rejected`, `restored`, `superseded`), the declared window and
whether it was applied, `attempt_count`, `error_code`, and `created_at`.
It also stores `request_digest`, a one-way SHA-256 of the request used to
recognize resubmissions. The table never holds payloads, row values,
credentials, or secrets.

- `(source_system, batch_id)` is unique. The same `batchId` in another
  source system is a different batch.
- The audit row is written first, in its own transaction, so attempts that
  later fail are still recorded (`status = failed`, with `error_code`
  `database_error` or `stale_batch`; nothing is written). It is then
  completed in the same transaction as the data, so the audit outcome and
  the stored rows always agree.
- A failed batch can be retried with the same `batchId` and content.
  `attempt_count` increases.
- Reusing a `batchId` with different content, or from a different
  connector, returns `409 batch_id_conflict` and changes nothing.
- Not audited: requests rejected before a trusted `batchId` exists (failed
  authentication, malformed or oversized bodies, invalid envelopes, source
  systems the connector may not write). Auditing them would let
  unauthenticated callers fill the table or reserve batch IDs. They are
  logged instead. If the database is unreachable, no audit row can be
  written; the failure is logged.

| `status`                   | Meaning                                         |
| -------------------------- | ----------------------------------------------- |
| `received`                 | Claimed, processing not finished                |
| `accepted`                 | All rows valid                                  |
| `accepted_with_rejections` | Valid rows applied, some rows rejected          |
| `rejected`                 | Every row invalid; nothing written              |
| `failed`                   | Not applied; see `error_code`; may be retried   |

**Response** `200` when the batch was processed:

```json
{
  "batchId": "2026-10-02T16-40-00Z-0001",
  "sourceSystem": "access-qryFINISHING-AVG",
  "status": "accepted_with_rejections",
  "receivedRows": 3,
  "insertedRows": 1,
  "duplicateRows": 1,
  "rejectedRows": 1,
  "restoredRows": 0,
  "supersededRows": 0,
  "windowApplied": false,
  "replayed": false,
  "rejections": [
    { "rowIndex": 2, "errors": [{ "field": "sourceDate", "message": "Value error, is not a valid calendar date" }] }
  ],
  "rejectionsTruncated": false
}
```

- `status`: `accepted` (no rejections), `accepted_with_rejections`, or
  `rejected` (every row invalid; nothing written).
- `receivedRows = insertedRows + restoredRows + duplicateRows + rejectedRows`.
  `duplicateRows` counts rows already stored or repeated within the batch.
  `restoredRows` counts earlier versions made current again.
  `supersededRows` counts previously current versions replaced by this batch.
- `windowApplied`: `null` without a window. Otherwise it says whether the
  window reconciliation ran.
- `replayed`: `true` when this is the stored result of an earlier identical
  submission. Rejections are recomputed and reported again.
- Rejected rows are reported by zero-based `rowIndex` with field-level
  messages. Submitted values are never echoed back. At most 100 rejections
  are listed (`rejectionsTruncated` tells you whether more exist).
- Valid rows in the batch are stored even when other rows are rejected.
  Fixing the rejected rows and re-sending the whole batch is safe.

**Errors.** Bodies have the form
`{"detail": {"error": "<code>", "message": "..."}}`.

| Status | `error`                  | Meaning                                                            |
| ------ | ------------------------ | ------------------------------------------------------------------ |
| 400    | `invalid_json`           | Not JSON, duplicate keys, `NaN`/`Infinity`                         |
| 401    | `invalid_credentials`    | Missing or invalid connector credentials (deliberately unspecific) |
| 403    | `source_system_not_allowed` | Connector may not write this `sourceSystem`                     |
| 409    | `batch_id_conflict`      | `batchId` already used with different content or another connector |
| 409    | `stale_batch`            | Newer data already applied for this scope; nothing written         |
| 413    | `payload_too_large`      | Body over 5 MiB                                                    |
| 415    | `unsupported_media_type` | Content-Type is not `application/json`                             |
| 422    | `validation_error`       | Envelope invalid (metadata, empty batch, too many rows); nothing processed. Includes `errors` |
| 503    | `ingestion_disabled`     | Ingestion is not enabled on this server                            |
| 503    | `database_unavailable`   | Database failure. Nothing from the batch was committed; resubmit   |

**Transactions.** All changes of a batch (inserts, supersessions,
restorations, and audit completion) are written in one database
transaction. Inserts are split into multi-row statements of 1000 rows. A
database failure at any point rolls back the whole batch; only the audit
row remains, marked `failed`.

**Logging.** One line per batch, for example:
`event=finishing_ingestion result=accepted batch_id=... source_system=...
connector=... attempt=1 extracted_at=... window=2026-09-01..2026-09-30
window_applied=True received=3 inserted=1 duplicates=1 restored=0
superseded=0 rejected=1 rejected_fields=sourceDate:1`. Replays, conflicts
and stale batches log `result=replayed`, `batch_id_conflict` or
`stale_batch`. The same fields are attached to the log record
as `record.ingestion`. Row values, request bodies, headers, and database
error text (which can contain SQL parameters) are never logged. Database
failures log only the exception type.

## Quality > Cost of Quality

One set of **Quality Cost records** (`quality.cost_records`, migration 0011)
feeds three pages under Quality. There are no separate COPQ and COQ records:
COPQ is the Internal Failure and External Failure records; the COQ Matrix is
all four classes.

- **Quality Cost Register** (`/quality/cost/register`): every record, newest
  first, filterable by date range, area, class, category, product, owner,
  financial status, status and a search (title, description, lot, customer,
  record ID such as `QC-00042`). A row opens the record: every section, related
  records, audit metadata, history and Edit.
- **Cost of Poor Quality** (`/quality/cost/copq`): confirmed COPQ, potential
  exposure, net, recovered, avoided, COPQ % of sales, internal failure $ per
  lb produced, open and overdue items; a category Pareto; a monthly trend; a
  monthly table; open-item aging; open failure items. A second tab is the
  **incident estimator**.
- **COQ Matrix** (`/quality/cost/matrix`): Total COQ, Good COQ (P + A), Poor
  COQ (IF + EF), Poor COQ %; the 2×2 matrix (select a class to list its
  items); the mix; a trend by class; a category table.

**+ Add Quality Cost Item** is on all three pages (for users with
`quality.cost.edit`) and opens the same form (`record-form.tsx`): what
happened, where, COQ classification and category, nine cost components with
a live total, financial status, ownership and status, recovery and
avoidance, and a related reference. Classes, categories, statuses and cost
components are defined once in `app/quality/cost/classification.py` and
served by `/records/options`.

The dashboards share one filter bar (year, month range, area, class,
category, product, owner, financial status); it applies to every KPI, chart
and list on the page.

### Rules and calculations (`records.py`, `calculations.py`, `service.py`)

- A record needs a date (not in the future), title, area, class, a category
  of that class and a description. Amounts are non-negative decimals; a blank
  component is not entered (null), never $0.
- Total cost = the sum of the entered components (null when none is entered).
  Net = total − recovered. Avoided cost is reported on its own and never
  subtracted.
- Financial status Confirmed and Closed count as **confirmed cost**;
  Potential and Validating are **potential exposure**. The two are always
  reported separately and never added together silently.
- Status Closed requires a date closed (on or after the date, not in the
  future); other statuses have none. Days open = (date closed or today) −
  date; overdue = open and past the due date.
- Good COQ, Total COQ and Poor COQ % are null when no confirmed Prevention or
  Appraisal cost is recorded, never $0. COPQ % of sales and $ per lb use the
  monthly production and sales inputs in `quality.cost_monthly_facts`
  (migration 0010), counting only months that report them.
- Creates and edits are audited (`quality.cost_record`, actor from the
  current identity mechanism) with optimistic concurrency: a stale edit
  answers 409 with the current record and nothing is saved.
- References (`quality.cost_record_references`) are generic
  `(type, key, label)` links so later modules (for example Corrective Action
  Reports) can be related without changing the record table.

### API

| Endpoint | Description |
| -------- | ----------- |
| `GET /api/v1/quality/cost/records` | Register list. Filters: `from`, `to`, `areaId`, `coqClass` (repeatable), `category`, `product`, `owner`, `financialStatus` (repeatable), `status` (repeatable), `open`, `search`, `limit` (≤ 500), `offset` |
| `GET /api/v1/quality/cost/records/options` | Areas, classes with categories, statuses, cost components, reference types, known products and owners, and whether the user may edit |
| `GET /api/v1/quality/cost/records/{id}` | One record |
| `GET /api/v1/quality/cost/records/{id}/history` | Its audit history |
| `POST /api/v1/quality/cost/records` | Create (`quality.cost.edit`) |
| `PUT /api/v1/quality/cost/records/{id}` | Edit with `version` (`quality.cost.edit`) |
| `GET /api/v1/quality/cost/summary` | COPQ and COQ Matrix figures. `year`, `from`, `through`, the dimension filters, and `poorOnly` for COPQ. Defaults: latest year with records, January through the latest month with a record |
| `GET /api/v1/quality/cost/estimator` | Products, package types, assumptions and guidance for the estimator |
| `POST /api/v1/quality/cost/estimate` | Estimate one incident. Nothing is stored |

Reads require `quality.cost.view`. Rule failures answer 422 with
`{error, message, field}`. Responses carry no workbook cell references.

### Incident estimator (`app/quality/cost/estimator.py`)

Reproduces the formulas of `Cost for Poor Quality Control-R0-08122025.xlsx`
(downtime, lower production rate, scrap, C-grade, rework, repack, in kUSD)
with the workbook's parameters, kept with their source in
`app/quality/cost/copq_estimator_reference.json`. The tests check every line
and the workbook's example total (284.5448 kUSD). Known workbook behaviour
kept as written: the rework total excludes its steam and power cost (shown
separately); pounds are converted with 0.454 in some formulas and 2.2 in
others. Products must match exactly (the workbook's approximate VLOOKUP is
not reproduced); product 3142 has no standard rate and is not offered.

### Importing the COQ workbook

`apps/api/import_templates/quality_cost_of_quality_2026.mapping.json` is the
reviewed mapping of `COQ Matrix.xlsx`: one entry per month with figures
(Jan and Feb 2026), each value with its source cell, plus the workbook's own
monthly totals, which `check` recalculates and compares (to the cent) but
never stores.

```powershell
cd apps/api
uv run python -m app.quality.cost.legacy_import check import_templates/quality_cost_of_quality_2026.mapping.json
uv run python -m app.quality.cost.legacy_import plan  import_templates/quality_cost_of_quality_2026.mapping.json
uv run python -m app.quality.cost.legacy_import apply import_templates/quality_cost_of_quality_2026.mapping.json
```

`apply` writes in one audited transaction (`quality.cost_monthly_fact` and
`quality.cost_record`, actor `legacy-import`): the monthly production and
sales inputs, plus each month's scrap loss, off-spec loss and customer
complaint costs as **Imported** Quality Cost records (Internal or External
Failure, Confirmed, Closed, no area, keyed `coq-workbook/YYYY-MM/...`). Stored
months or records that differ from the file block it, and re-running is a
no-op; a database that already holds the 0010 months gets only the records.
Imported records may be edited (area, product, owner, actions) in the
Register. See `docs/quality-cost-0010/data-quality-report.md`.

## Quality > Corrective Action Reports

Corrective Action Reports (CARs, migration 0012) live under Quality next to
Cost of Quality and reuse its patterns (audited saves with a `version`,
controlled lists served by `/options`, null never shown as zero).

- **Dashboard** (`/quality/cars`): Open, Past due, Due soon, Awaiting
  effectiveness and Closed YTD; CARs by status, department, source and root
  cause; opened vs closed per month; aging of open CARs; effectiveness results;
  repeat CARs; cost impact by department; a past-due list. Filters: request
  date range, department, source, assigned to. Empty states, no placeholder
  figures.
- **CAR Register** (`/quality/cars/register`): CAR number, request date,
  subject, department, source, assigned to, due date, status, effectiveness,
  days open, cost impact and action progress. Filters (kept in the URL):
  search, date range, status, department, source, assigned to, root cause,
  effectiveness, past due, previous/repeat. A row opens the CAR at
  `/quality/cars/register/{id}`.
- **+ New CAR** (`/quality/cars/new`): only the subject and request date are
  needed to save; the CAR number (`Q-YYYY-NNN`) is assigned on save, one after
  the highest used that year (gaps are left).

A CAR is worked through eight steps: Identify, Contain, Investigate (Why-Why
analysis), Evaluate (systemic review), Correct (actions and plan), Verify
(effectiveness), Cost, Close (approvals and closure). Each step can be saved
incomplete. The record page also shows an overview, evidence and related
records, imported legacy fields, and the full history. Controlled lists
(sources, departments, root causes, dispositions, statuses, approval
functions) are defined once in `app/quality/car/reference.py`; values used
only by older forms stay readable and are marked "(older form)".

### Rules (`calculations.py`, `service.py`)

- Corrective actions are separate records (`quality.car_actions`) with their
  own owner, target date, status and completion date; adding, editing and
  completing one does not change the CAR's status. The register shows
  "x/y complete" and overdue actions.
- A CAR can be closed only when every action is complete, an effectiveness
  result is recorded (a follow-up is required when Not Effective), a date
  closed (not in the future, not before the request) and a closure approver
  are entered. Completing actions never records effectiveness.
- Past due = not closed and the due date has passed; due soon = not closed
  and due within `CAR_DUE_SOON_DAYS`. Neither is stored.
- Yes/No questions and every other field distinguish "not recorded" from
  "No"; blank cost lines are not entered, never $0. Total cost impact is the
  sum of the entered lines (material, production time, other).
- Approvals are names and dates recorded by the signed-in user, stored per
  function with who recorded them. They are not digital signatures.
- Evidence and attachments are references (document names, locations); no
  files are stored and no links are generated.
- A CAR can create a Quality Cost record from its cost impact (area, COQ
  class, category and financial status chosen by the user) or link an
  existing one (`quality.cars.quality_cost_record_id`, one CAR per record).
  The record then counts in COPQ and the COQ Matrix like any other; its
  dialog links back to the CAR.

### API

| Endpoint | Description |
| -------- | ----------- |
| `GET /api/v1/quality/cars` | Register list. Filters: `from`, `to`, `status`, `department`, `source`, `rootCause`, `effectiveness` (each repeatable, `not_recorded` allowed), `assignedTo`, `pastDue`, `repeat`, `search`, `limit`, `offset` |
| `GET /api/v1/quality/cars/options` | Controlled lists, known names, due-soon window and edit rights |
| `GET /api/v1/quality/cars/dashboard` | Dashboard figures. `from`, `to`, `department`, `source`, `assignedTo` |
| `GET /api/v1/quality/cars/linked?costRecordId=` | The CAR linked to a Quality Cost record |
| `GET /api/v1/quality/cars/{id}` / `.../history` | One CAR with its actions / its audit history |
| `POST /api/v1/quality/cars` | Create (`quality.cars.edit`) |
| `PUT /api/v1/quality/cars/{id}` | Edit with `version` (`quality.cars.edit`); a stale edit answers 409 |
| `POST /api/v1/quality/cars/{id}/actions` | Add an action |
| `PUT /api/v1/quality/cars/{id}/actions/{actionId}` | Edit an action |
| `POST /api/v1/quality/cars/{id}/actions/{actionId}/complete` | Complete an action |
| `POST /api/v1/quality/cars/{id}/quality-cost` | Create and link a Quality Cost record (also `quality.cost.edit`) |
| `PUT /api/v1/quality/cars/{id}/quality-cost` | Link (`recordId`) or unlink (null) a Quality Cost record (also `quality.cost.view`) |

Rule failures answer 422 with `{error, message, field}`. Responses carry no
workbook cell references.

### Importing historical CAR workbooks

The CAR workbooks in `docs/cars` are source records: they are opened
read-only and never modified, moved or renamed. A workbook with no CAR
number (the blank QMS-006-1 template) is skipped. On a development machine,
`extract` reads them and writes the reviewed mapping file and the migration
report (`docs/quality-car-0012/migration-report.md`); blanks stay not
recorded and older-form answers without a current field are kept verbatim
as legacy fields. The server only needs the mapping file:

```powershell
cd apps/api
uv run python -m app.quality.car.legacy_import check import_templates/quality_cars_2026.mapping.json
uv run python -m app.quality.car.legacy_import plan  import_templates/quality_cars_2026.mapping.json
uv run python -m app.quality.car.legacy_import apply import_templates/quality_cars_2026.mapping.json
```

`apply` writes in one audited transaction (`quality.car`, `quality.car_action`,
actor `legacy-import`), keyed `car-workbook/<CAR number>`. CAR numbers are
kept as in the workbooks; a stored import that differs from the file blocks
it, and re-running is a no-op.

In the deployed stack, mount the mapping read-only into a one-off container:

```bash
docker compose run --rm -v "$PWD/apps/api/import_templates:/app/import_templates:ro" \
  api python -m app.quality.car.legacy_import plan import_templates/quality_cars_2026.mapping.json
```

## Authorization

Users sign in with platform accounts (email and password). Users, roles,
role assignments and permissions live in the database and are managed in
**Administration**; none of them are configured in `.env`. Quality, Safety and
every later module share this one sign-in and permission model.

### Sign-in and sessions (`app/auth/`)

- **Accounts** (`core.users`): id, name, email (stored normalized to lower
  case, unique), optional https image URL, status `active`/`inactive`,
  `last_login_at`, created/updated timestamps. Users are never deleted, so
  their names stay on the records and history they touched. An inactive user
  cannot sign in, and their sessions end at once.
- **Passwords** are hashed with Argon2id (`argon2-cffi`); at least 12
  characters. Passwords and hashes are never logged, returned by the API,
  written to audit records or kept in settings. After `LOGIN_MAX_FAILURES`
  failed sign-ins an account is locked for `LOGIN_LOCK_MINUTES`; the API
  answers a locked account exactly like a wrong password (`401
  sign_in_failed`), so it never reveals whether an email has an account.
- **Password links.** Nobody chooses a password for someone else. An
  administrator creates the account and gives the user a one-time setup link
  (or later a reset link); the user sets their own password. Links expire
  after `PASSWORD_LINK_HOURS`, work once, and issuing a new one cancels the
  previous one. Only a SHA-256 digest of the link token is stored. The token
  travels in the URL fragment (`/setup-password#token=...`), which browsers
  do not send to servers or logs, and the page removes it from the address bar.
- **Sessions** (`core.sessions`) are opaque random tokens, stored only as
  SHA-256 digests, in an HttpOnly, SameSite=Lax cookie (`__Host-op_session`;
  `op_session` when `SESSION_COOKIE_SECURE=false`). A session ends after
  `SESSION_IDLE_MINUTES` without a request and `SESSION_ABSOLUTE_HOURS` after
  sign-in; signing out deletes it. The browser never sees the token.
- **Cross-site requests.** Every write must carry `X-Requested-With:
  operations-platform`, which browsers do not allow other sites to add; the
  web client sends it automatically.
- **HTTPS.** Production is reached by hostname over HTTPS (Nginx). The
  session cookie is `Secure`; `SESSION_COOKIE_SECURE=false` is refused when
  `ENVIRONMENT=production` and is meant only for local `http://localhost`.

| Endpoint | Purpose |
| -------- | ------- |
| `POST /api/v1/auth/sign-in` | `{email, password}` → `204` and the session cookie; `401 sign_in_failed` otherwise |
| `POST /api/v1/auth/sign-out` | Ends the session |
| `GET /api/v1/auth/me` | The signed-in user (id, name, email, image, status), role names and effective permissions |
| `POST /api/v1/auth/password-link/check` | `{token}` → the name and email the link is for; `400 link_invalid` if expired or used |
| `POST /api/v1/auth/password-link` | `{token, password}` sets the password; `422 weak_password` |
| `POST /api/v1/auth/password` | `{currentPassword, newPassword}`, signed in; other sessions of the user end |

### First administrator and recovery

There is no built-in account, default password or email allowlist. On a new
installation, with shell access to the server, create the first
administrator once:

```bash
docker compose exec api python -m app.auth.cli bootstrap-admin \
  --email first.admin@example.com --name "First Admin" \
  --base-url https://operations.example.com
```

It prints a one-time setup link to the terminal (not to any log); send it to
that person. The command refuses to run once any active user holds
`users.manage` and `roles.manage`, so it cannot be used to add administrators
later; do that in Administration → Users.

If every administrator is locked out, an operator with server access can issue
a new link for an existing active user:

```bash
docker compose exec api python -m app.auth.cli password-link \
  --email first.admin@example.com --base-url https://operations.example.com
```

Both commands are audited as `operator-cli`.

### Roles and permissions

`User → UserRole → Role → RolePermission → Permission`. A user may hold
several roles; their effective permissions are the union of the permissions
of their **active** roles (an inactive role grants nothing). There are no
combination roles. Permissions are defined once in `app/core/permissions.py`
(`<group>.<action>`, e.g. `car.close`); the web copy in
`apps/web/src/lib/permissions.ts` is kept identical by a test. Nothing is
implied by a name: `qualityCost.edit` does not include `qualityCost.view`
unless a role grants both.

Migration 0013 seeds the standard roles (`app/auth/roles.py`):

| Role | Grants |
| ---- | ------ |
| `ADMIN` | Every permission. The only standard role with `users.manage` and `roles.manage`. |
| `QUALITY_ADMIN` | All of Quality (Quality Cost, CARs, approval, closure, reopening), all assignments |
| `QUALITY_USER` | Quality viewing, entering Quality Cost records and CARs, working CAR actions; no approval or closure |
| `SAFETY_ADMIN` | All of Safety (records, incidents, near misses, observations), all assignments |
| `SAFETY_USER` | Safety viewing and entering records and observations; no approval or closure |
| `CONTRIBUTOR` | Their own assignments only |
| `VIEWER` | Read-only Quality and Safety |

Administrators may change a role's permissions afterwards. Rules enforced by
the API (`app/auth/admin.py`):

- Only permissions in the catalog can be granted, and only known roles assigned.
- No escalation: without `users.manage` you may only assign roles whose
  permissions you hold; without `roles.manage` you may only grant permissions
  you hold.
- `ADMIN` always holds every permission and cannot be deactivated. Standard
  roles keep their names and cannot be deleted. A role held by any user cannot
  be deleted.
- There is always at least one active user holding `users.manage` and
  `roles.manage`: deactivating them, removing their roles or changing roles in
  a way that would leave none is refused (`422 last_administrator`). You
  cannot deactivate yourself.
- Every change to users, roles, role assignments, role permissions and
  password links is audited (no secrets in the audit record).

Administration endpoints (`/api/v1/admin/...`): `GET/POST users`, `GET/PUT
users/{id}`, `POST users/{id}/activate|deactivate`, `PUT users/{id}/roles`,
`POST users/{id}/password-link` (`users.edit`), `GET/POST roles`, `PUT
roles/{code}`, `PUT roles/{code}/permissions`, `DELETE roles/{code}`, `GET
permissions`, `GET audit`. Each needs its own permission (`users.view`,
`users.create`, `users.edit`, `users.activate`, `users.deactivate`,
`users.assignRoles`, `roles.view`, `roles.create`, `roles.edit`,
`roles.assignPermissions`, `roles.delete`, `audit.view`).
`GET /api/v1/users/directory` (`app.view`) lists names for person pickers.

### Enforcement

Every protected request resolves the session user, checks the account is
active, loads their active roles, computes their permissions, checks the
endpoint's permission (`require_permission`, `require_all_permissions`,
`require_any_permission` in `app/core/authorization.py`), applies the
record's own rules, makes the change, and audits it with the signed-in user.
Code checks permissions, never role names. Hidden buttons and filtered
navigation in the web app are a convenience only.

- `401 authentication_required`: not signed in or session ended (the web app
  returns to the sign-in page and then to the page you were on).
- `403 permission_denied`: signed in without the permission. The message
  never says who could do it. Denials are logged as `event=authorization
  result=denied`.

The browser is never trusted for who is acting: the acting user, roles,
permissions, `createdBy`/`updatedBy`, approver, closer, completer and
reviewer are all taken from the session. Record-level rules include:

- **CARs**: completing a corrective action needs `car.completeAction` and
  being its owner (or `car.admin`); an approval is recorded as the signed-in
  user for one function (`car.approve`) and may be withdrawn only by that
  user (or `car.admin`); changing the assignee needs `car.assign`; recording
  the effectiveness review needs `car.reviewEffectiveness`; closing needs
  `car.close` and reopening `car.reopen`. The reviewer and closure approver
  are the signed-in user.
- **Quality Cost**: changing the owner needs `qualityCost.assign`, confirming
  costs `qualityCost.confirmFinancial`, closing `qualityCost.close`.
- **Safety**: incidents and near misses each have their own
  `view/create/edit/delete` permissions; reclassifying needs
  `incident.classify`; closing or changing a closed performance month needs
  `safetyRecord.close`. Dashboards also need `qualityDashboard.view` or
  `safetyDashboard.view`.

**People on records.** CAR requester, assignee, containment owner and action
owners, and the Quality Cost owner, are user IDs chosen from active users;
the API stores the name alongside. Names on records from before user
accounts (imported workbooks) are kept exactly as written and shown as
"recorded before user accounts"; they were linked to a user only where the
match was unambiguous, never guessed. **My Assignments** (`GET
/api/v1/assignments/mine`, `assignments.viewOwn`) lists open CARs, CAR
actions and Quality Cost items assigned to the signed-in user's ID.

### Retired settings

`USER_AUTH_MODE` and `DEVELOPMENT_USER_PERMISSIONS` (the pre-sign-in
development user) are gone. The API ignores them and logs
`event=retired_setting` if they are still set; remove them from `.env`.
The old `safety.*.edit`/`quality.*.edit` style permission names were
replaced by the catalog above.

<details>
<summary>Former permission names (before migration 0013)</summary>

| Granted                    | Satisfies                                                         |
| -------------------------- | ----------------------------------------------------------------- |
| `safety.view`              | every Safety `view` permission, including `safety.incidents.records.view`, `safety.incidents.history.view` and `safety.trir.view` |
| `safety.edit`              | everything above plus every Safety `edit` permission, including `safety.incidents.records.edit` |
| `safety.manage`            | everything above plus `safety.incidents.records.manage` and `safety.trir.manage` |
| `safety.incidents.view`    | `safety.incidents.view` and the nested `records.view`, `history.view` |
| `safety.incidents.edit`    | the above plus `safety.incidents.edit`, `safety.incidents.records.edit` |
| `safety.incidents.records.view` / `.edit` / `.manage` | Individual records: read / create and edit / void and reclassify |
| `safety.incidents.history.view` | A record's audit history                                  |
| `safety.observations.view` | `safety.observations.view` only                                   |
| `safety.observations.edit` | `safety.observations.view`, `safety.observations.edit`            |
| `safety.performance.view`  | `safety.performance.view` only                                    |
| `safety.performance.edit`  | `safety.performance.view`, `safety.performance.edit`              |
| `safety.trir.view`         | TRIR Experience                                                   |
| `safety.trir.manage`       | TRIR history imports (operator CLI; no endpoint writes TRIR facts) |
| `quality.view`             | every Quality `view` permission, including `quality.cost.view` and `quality.cars.view` |
| `quality.edit`             | everything above plus every Quality `edit` permission, including `quality.cost.edit` and `quality.cars.edit` |
| `quality.manage`           | everything above plus `quality.cost.manage` and `quality.cars.manage` |
| `quality.cost.view`        | Quality Cost Register, Cost of Poor Quality, COQ Matrix and the incident cost estimator |
| `quality.cost.edit`        | the above plus adding and editing Quality Cost records            |
| `quality.cost.manage`      | the above plus Cost of Quality imports (operator CLI)             |
| `quality.cars.view`        | CAR dashboard, CAR Register, CAR records and their history        |
| `quality.cars.edit`        | the above plus creating and editing CARs and their actions        |
| `quality.cars.manage`      | the above plus CAR workbook imports (operator CLI)                |

`quality.cars.*` and `quality.cost.*` are independent: creating a Quality
Cost record from a CAR needs `quality.cars.edit` **and** `quality.cost.edit`;
linking an existing one needs `quality.cars.edit` and `quality.cost.view`.

</details>

## Audit trail

`core.audit_events` is the platform audit trail for user data changes. One
row per changed entity records `actor_id`, `occurred_at`, `action`
(`create`/`update`/`delete`), `entity_type`, `entity_key`, `old_value` and
`new_value` (JSONB), and a `change_set_id` grouping all rows of one save.
When the actor is a platform user, `actor_user_id` links to `core.users` and
`actor_name` keeps their name as it was at the time, so history still reads
correctly after a rename or deactivation. System actors (`legacy-import`,
`operator-cli`) have only `actor_id`. Audit rows are written in the same
transaction as the change; write them with
`app.audit.recorder.record_changes`. User and role administration is audited
here too (`core.user`, `core.role`). Values never contain passwords, hashes or
tokens. The Audit Log page (`/system/audit`, `audit.view`) lists events
newest first, filterable by record type.

## Safety > Incident & Near Miss

Routes: `/safety` (overview), `/safety/incidents/data-entry`,
`/safety/incidents/dashboard` (Incident & Near Miss Dashboard). The retired
`/safety/incidents/analytics` page URL redirects (`308`) to the Dashboard
(`next.config.ts`). Code lives in `apps/api/app/safety/` and
`apps/web/src/features/safety/incidents/`; the spreadsheet grid
(`MonthlyGrid`) and `BarChart` are shared components in
`apps/web/src/components/common/`.

| Endpoint                                   | Permission              | Purpose |
| ------------------------------------------ | ----------------------- | ------- |
| `GET /api/v1/safety/incidents/metrics?year=` | `safety.incidents.view` | Sections, categories, 12 monthly values and calculated YTD per category, `canEdit`, `yearsWithData` |
| `PATCH /api/v1/safety/incidents/metrics`   | `safety.incidents.edit` | Set or clear cells: `{"year": 2026, "changes": [{"categoryId", "month", "value", "previousValue"}]}` |
| `GET /api/v1/safety/incidents/analytics?year=&through=` | `safety.incidents.view` | Incident Analytics read model behind the Dashboard, January..`through`; see "Dashboard" below |

Data Entry and the Dashboard read the same stored rows.

### Data model

| Table                          | Contents |
| ------------------------------ | -------- |
| `safety.metric_sections`       | Blocks of a Safety function: `metric_set` (`incidents`), `code`, `name`, `display_order`, `active` |
| `safety.metric_categories`     | Rows of a block: `section_id`, `code`, `name`, `display_order`, `active` |
| `safety.monthly_metric_values` | One row per `(category_id, reporting_year, reporting_month)` (unique): `value` (integer, `>= 0`), `created_at/by`, `updated_at/by` |

- There are no month columns. Jan–Dec is presentation only.
- **No row means unreported**, which is distinct from a stored `0`. Clearing a
  cell deletes its row; the previous value remains in `core.audit_events`.
- YTD is calculated per category (sum of its reported months; null when
  nothing is reported) and never stored. Categories are never summed into a
  section total.
- Inactive sections and categories are hidden from the grid and the dashboard.
- There is no site dimension: the platform has no site entity yet. When one
  exists, add a `site_id` reference and include it in the unique constraint.

Seeded blocks (`metric_set = incidents`), in order: Incident & Near Miss
Totals (Near Miss, Incident), Incident Classification (13 categories), LOPC,
Property / Equipment Damage, PIT, PSIF. LOPC, Property / Equipment Damage, PIT
and PSIF currently have one category each, pending confirmation of the
workbook's row breakdown for those blocks. Further categories are added by
migration.

**Incident and Near Miss are explicit source metrics.** The monthly Incident
total is entered as its own value, never derived from Incident
Classification. Classifications are a separate breakdown and are not mutually
exclusive (one incident may carry several), so their sum can differ from
Incident. The Dashboard's Incident and Near Miss KPIs and trends read only the
explicit metrics.

### Saving

- A save is all-or-nothing and serialized per metric set and year
  (transaction-scoped advisory lock).
- Each change carries `previousValue`, the value the client loaded. If any
  stored value differs, nothing is written and the API returns
  `409 edit_conflict` with the conflicting cells. The page offers to reload
  the latest values while keeping the user's edits.
- Counts are strict JSON integers from 0 to 100,000; strings, fractions and
  booleans are rejected (`422`). Unknown or inactive categories return
  `422 unknown_category`.
- Unchanged cells are ignored. Every changed cell produces one audit event
  (`entity_type = safety.monthly_metric_value`, `entity_key =
  incidents/<section>/<category>/<year>-<month>`).
- Saves log `event=safety_metrics_saved` with counts only, never values.

### Importing the 2026 EHS workbook

Historical values are loaded with a separate CLI, never by the pages:

```bash
cd apps/api
uv run python -m app.safety.legacy_import check mapping.json   # validate file, no database
uv run python -m app.safety.legacy_import plan  mapping.json   # compare with stored values
uv run python -m app.safety.legacy_import apply mapping.json   # write, audited as "legacy-import"
```

Start from the template
[`apps/api/import_templates/safety_incidents.template.json`](apps/api/import_templates/safety_incidents.template.json),
copy it outside the repository, transcribe the workbook into the copy and have
it reviewed before use. The template lists every seeded section and category
with all months `null`; it contains no source values. Shape (illustrative, not
real data):

```json
{
  "source": "2026 LCY EHS Dashboard.xlsx, sheet <name>",
  "metricSet": "incidents",
  "year": 2026,
  "notes": ["How the Incident total discrepancy was resolved"],
  "sections": [
    {
      "section": "incident_near_miss_totals",
      "categories": [
        { "category": "incident", "months": [0, null, null, null, null, null, null, null, null, null, null, null] }
      ]
    }
  ],
  "expectedYtd": [
    { "section": "incident_near_miss_totals", "category": "incident", "value": 0, "statedIn": "<cell or label>" }
  ]
}
```

- `months` is January to December. `null` means unreported and is never
  written; `0` is a reported zero. Never replace `null` with `0`.
- `expectedYtd` records per-category totals stated elsewhere in the workbook
  (for example the stated Incident total). Any difference from the monthly
  values is printed and blocks `apply`.
- `apply` never overwrites or clears: a stored value that differs from the
  file, including one the file marks `null`, blocks it.

**Known reconciliation issue.** In the 2026 workbook the monthly Incident
source grid totals 41 for the populated months, while "Total EHS Incidents
2026" shows 40. The application does not adjust either figure. Resolve it
with the Safety owner, record the decision in the mapping file's `notes`, and
add the agreed Incident figure to `expectedYtd` before running `apply`.
Incident is the explicit metric, so Incident Classification totals are not
used to reconcile it.

### Annual Behavior tagging

Behavior counts are annual tags, not monthly values. Migration `0008` adds
`safety.behavior_categories` (the 24 workbook behaviors, seeded) and
`safety.annual_behavior_counts` (one row per category and year, no month
column). No row means not reported; `0` is an explicit zero. One incident
report can carry several tags, so the tags may exceed the Incident total.

- `GET /api/v1/safety/incidents/behavior?year=` and `PATCH` with
  `{ year, changes: [{ categoryId, value, previousValue }] }`: the same
  validation, `409 edit_conflict` and audit rules as monthly saves
  (`entity_type = safety.annual_behavior_count`, `entity_key =
  incidents/behavior/<category>/<year>`).
- The Incident Analytics response carries `behavior`: the Pareto (count,
  share of tags, share of incident reports, cumulative share of tags). The
  denominator is the stored Incident total for the whole year; no percentage
  or denominator is stored.
- The 2026 workbook counts are loaded with their own CLI:

```bash
cd apps/api
uv run python -m app.safety.behavior.legacy_import check import_templates/safety_behavior_2026_lcy_ehs.mapping.json
uv run python -m app.safety.behavior.legacy_import plan  import_templates/safety_behavior_2026_lcy_ehs.mapping.json
uv run python -m app.safety.behavior.legacy_import apply import_templates/safety_behavior_2026_lcy_ehs.mapping.json
```

Blank workbook cells stay `null` and are never written. The sheet labels its
denominator "Total Number of Incident Reports 2025", but it is the 2026
Incident total; the owner confirmed the counts are 2026 and the label is kept
in the mapping as a recorded discrepancy.

### Individual Incident and Near Miss records

Migration `0009` adds `safety.incident_records`: one row per documented
Incident or Near Miss. **The monthly totals stay authoritative**; records
document them and never change them, and no total is derived from records.

| Endpoint (`/api/v1/safety/incidents/...`)    | Permission                        | Purpose |
| -------------------------------------------- | --------------------------------- | ------- |
| `GET records?year=&through=&month=&eventType=&areaId=&classificationId=&status=&search=` | `safety.incidents.records.view` | Records oldest first, `total`, and `canEdit` / `canManage` / `canViewHistory`. Active only unless `status` (repeatable) says otherwise. `search` matches the description or the number in any accepted form |
| `GET records/options`                        | `safety.incidents.records.view`   | Areas and Incident Classifications a record can reference |
| `GET records/reconciliation?year=`           | `safety.incidents.records.view`   | Per month and event type: total, documented count, state (below) |
| `GET records/{id}`                           | `safety.incidents.records.view`   | One record |
| `GET records/{id}/history`                   | `safety.incidents.history.view`   | Its audit events, oldest first |
| `POST records`                               | `safety.incidents.records.edit`   | Create, for a given reporting month |
| `PUT records/{id}`                           | `safety.incidents.records.edit`   | Edit; send the loaded `version` |
| `POST records/{id}/void`                     | `safety.incidents.records.manage` | Void with a reason; send `version` |
| `POST records/{id}/reclassify`               | `safety.incidents.records.manage` | Mark it reclassified to the other event type, creating the replacement or linking an existing active one |

- Fields: optional `incidentNumber` (normalized, e.g. `lcy 2026 37` becomes
  `LCY-2026-037`; unique when present), `eventType` (`incident` /
  `near_miss`), required `incidentDate`, non-blank `description`, nullable
  area and classification (an active Incident Classification category),
  `status` (`active` / `voided` / `reclassified`) with reason and related
  record, `source` (`manual` / `legacy_import`), created/updated by and at,
  and `version`.
- The reporting month is the date's month. The date must fall in the month
  the record is entered for (`422 date_outside_month`) and not after today in
  Baytown (`422 future_date`); an edit never moves a record to another
  month. Other `422` errors:
  `duplicate_incident_number`, `invalid_classification`, `record_inactive`
  (only active records change), `invalid_replacement`.
- A stale `version` returns `409 edit_conflict` with the current record and
  writes nothing.
- There is no hard delete. Voided and reclassified records are kept and
  hidden unless "Show voided and reclassified" / "Show inactive" is on.
- Every write is audited in the same transaction (`safety.incident_record` /
  `incident-records/<id>`). The legacy `source_reference` (workbook location
  and passage hash) is stored and audited but never returned by any endpoint,
  including history.
- The UI hides each action the user's `can*` flags do not allow; the API
  enforces the same permissions.

**Reconciliation** compares each month's stored total with its active
records. States: `reconciled`, `records_missing` (total > documented),
`records_exceed_total`, `total_unreported_with_records` (records but no
total), `explicit_zero_with_records` (a reported 0 with records), and
`no_total_and_no_records`. They are warnings only: nothing is blocked and
nothing is adjusted.

**Data Entry.** On the Incident & Near Miss Totals grid, the Incident and
Near Miss rows have a "Records" sub-row with a visible button per started
month: "Add" when nothing is documented, otherwise the documented count
(with "!" on a warning state). Its accessible name says what it does, e.g.
"Manage 3 Incident records for January 2026". It opens a dialog titled
"January 2026 Incidents" with the total, documented count, reconciliation
status, Add record, View history, Edit, Void, Reclassify and an "Open
Incident Register" link. No action is labelled Delete, and nothing relies on
right-click.

### Incident Register

The Dashboard's Incident Register tab (`?view=register`, also
`&month=&eventType=`) lists records in month groups, newest month first. Each
group shows the month's total against the documented count and its
reconciliation state. Columns: number, date, type, classification, area,
description, status. Filters: Year and Through (the page filters), Month,
Event type, Area, Classification, Status, Search, Show inactive. Actions: Add
Incident, Add Near Miss, Edit, History, Void, Reclassify. Below the `md`
breakpoint the table becomes a card list.

### Importing legacy narratives as records

The workbook's narrative comments are a legacy source, read from a copy and
never modified. Nothing is imported without review:

```bash
cd apps/api
uv run python -m app.safety.records.legacy_import extract import_templates/safety_incident_records_2026_lcy_ehs.extract.json <copy of workbook.xlsx> <out-dir>
#   -> <out-dir>/incident_records_review.json and .csv (for reviewers)
uv run python -m app.safety.records.legacy_import check  <review.json>   # no database
uv run python -m app.safety.records.legacy_import report <review.json>   # no database
uv run python -m app.safety.records.legacy_import plan   <review.json>   # documented vs totals
uv run python -m app.safety.records.legacy_import apply  <review.json>   # audited as legacy-import
```

`extract` verifies the workbook's SHA-256 is unchanged and recommends
`include` only for passages with an event date in their month; everything
else is `exclude` with a reason. Reviewers edit the JSON (`decision`, and
dates or fields only from the source). Dates, numbers, areas and
classifications are never invented. `apply` is idempotent (a stored source
reference is skipped) and blocked by a number used by another record.

### Dashboard

The Incident & Near Miss Dashboard (`/safety/incidents/dashboard`,
Incident & Near Miss > Dashboard; `IncidentDashboard` in
`incident-dashboard.tsx`) is the only Incident & Near Miss reporting page.
Its read model is the Incident Analytics API,
`GET /api/v1/safety/incidents/analytics?year=&through=`; there is no
separate dashboard API and one calculation path (`app/safety/analytics.py`).
Both are read-only and calculate everything on each request from the
stored `incidents` monthly values; nothing is stored, copied or imported,
and the workbook is never read. The GET writes no rows and no audit events.
Both require `safety.incidents.view`; there is no separate permission. The
navigation entry is shown like the other Safety entries; without the
permission the page shows "not available to you" (the API answers `403`).

The page has Year and Through month filters, six YTD cards (Incidents, Near
Misses, LOPC, PSIF, PIT Incidents, Property & Equipment Damage), monthly
charts for Incidents vs Near Misses, Incident Classification, LOPC, Property
vs Equipment Damage, PIT and PSIF, each with a data table, and a methodology
and data-completeness section. The earlier Dashboard (full-year totals from
the `metrics` endpoint, including the `pit` and `property_equipment_damage`
sections) has been retired.

- `year`: the reporting-year limits (2000–2100). The page offers 2026 to the
  current Baytown year. `through`: 1–12, default the latest month of the year
  that has started in Baytown (`America/Chicago`; 12 for a past year). A
  `through` month that has not started is refused (`422 month_not_started`);
  a future year without `through` returns no months.
- Response: `year`, `throughMonth`, `latestMonth`, `availableYears`, six
  `kpis` (`incidents`, `near_misses`, `lopc`, `psif`, `pit`,
  `combined_damage`: `value`, `monthsReported`, `throughMonth`, `complete`,
  and `parts`, the Property Damage and Equipment Damage components of
  `combined_damage`, empty for the others), and series for Incidents,
  Near Misses, LOPC, PSIF, PIT, Property Damage, Equipment Damage, combined
  damage, and each classification. A series has one value per month
  January..through, `total`, `monthsReported`, `unreportedMonths`, `complete`.

Definitions:

- **Null versus zero.** A month with no stored value is unreported (null),
  never zero; the page shows it as "Not reported" (no bar). A total is the sum
  of the reported months, or null when none are; it is `complete` only when
  every month January..through is reported. An unreported current month makes
  the total incomplete. Prior years are never used to fill a year.
- **Incidents / Near Misses YTD**: the explicit `incident` and `near_miss`
  series.
- **Classifications are not exclusive**: an incident may have more than one
  classification, so classification counts may exceed the number of
  incidents. They are shown as counts in a bar chart, never summed, compared
  with Incident or shown as shares. The chart lists the configured
  Incident Classification categories, with their configured names, then PSIF.
- **LOPC** is the `lopc` series. `spill_release` records the same events and
  is shown only as a classification; the two are never added.
- **PIT** is the `pit_accident` classification ("Powered Industrial Vehicle
  (PIT) Incidents"). The `pit` section holds the same counts and is not read
  by the Dashboard, so PIT is never counted twice.
- **Damage**: `property_damage` and `equipment_damage_failure`, shown side by
  side. Combined damage = Property Damage + Equipment Damage classifications,
  not a count of distinct events. A combined month is null only when both
  parts are unreported, and reported only when both are. The stale
  `property_equipment_damage` section is not read by the Dashboard.
- **PIT Incidents YTD** and **Property & Equipment Damage YTD** cards use the
  same series as the charts. The damage card shows its composition (e.g.
  "6 property · 8 equipment"); when either part has unreported months its
  total adds the reported months and is labelled partial, never complete.
- **PSIF** is shown as recorded. The application does not define PSIF, and
  shows no PSIF frequency, share, ratio, severity or rating; it is not
  merged with the Near Miss Potential "SIF".
- No targets, scores or red/yellow/green colours. Every chart has a data
  table alternative.

**Tabs.** Overview, Area, Incident Analysis, Incident Register, Behavior. The
tab is kept in `?view=` (`overview`, `area`, `incident-analysis`, `register`,
`behavior`); an unknown value shows Overview.

**Display controls** (`DisplayControls` in
`apps/web/src/components/common/display-controls.tsx`) on Area, Incident
Analysis, Behavior, the Incident Register and TRIR Experience:

| Control             | Default | Effect |
| ------------------- | ------- | ------ |
| Hide empty rows     | on      | Hides a row only when every cell is null (unreported) |
| Show reported zeros | on      | Off also hides rows holding only reported 0s and blanks |
| Hide empty months   | off     | Hides months with no reported value in any row |
| Series              | all     | Chooses the plotted series, e.g. Incidents / Near Misses |
| Reset               |         | Back to the defaults |

They change what is shown, never the data: totals and KPIs always include
hidden rows and months, null is never shown as 0, and a notice such as
"5 empty rows hidden" offers "Show all". Preferences are kept per surface
in the browser's `localStorage` (`display:safety.incidents.area`,
`…analysis`, `…behavior`, `…register`, `display:safety.trir`). They are
presentation preferences, not safety data, so they are not stored on the
server or audited; they do not follow the user to another browser, and
clearing site data resets them.

Future work (Phase 2): area analytics (incidents or near misses by area,
area by classification, PSIF by area), Near Miss Cause, Near Miss Potential,
LOPC contributing factors, Process Safety Incidents, and the Behavior Pareto.
These need structured data the platform does not hold yet.
A 2025 LOPC comparison from `performance_legacy` is also deferred.

## Safety site calendar

"Today" and the current reporting year are the Baytown site's calendar date
in `America/Chicago`, never the UTC date, the browser's time zone or the
server's. A new reporting year starts at midnight in Baytown on 1 January
with no deployment, seed or migration. One implementation on each side:
`app/safety/site_calendar.py` (`site_today`) and
`apps/web/src/features/safety/site-calendar.ts` (`siteIsoDate`, `siteYear`).
The platform has one site; move the time zone into site configuration if it
becomes multi-site. Audit timestamps stay UTC.

- The API uses it for future-date checks, months started, and which
  Safety Performance months can be entered or closed.
- The year-scoped Safety pages are rendered per request (`connection()`),
  and pass the server's Baytown date to the page for hydration, so no
  build-time year is baked into HTML.
- While a page stays open, `useSiteToday` re-checks the Baytown date every
  minute and when the tab becomes visible. Defaults (reporting year, the
  Observations month and observed date, the Incident & Near Miss Dashboard
  through month) move to the new
  day; a value the user chose is kept until they change it or press "Use
  today". A default never moves while it holds unsaved work (Incident &
  Near Miss or Safety Performance hours being edited, an Observation being
  edited or deleted, a chosen "through" month).
- Year selectors always offer the current Baytown year, the four before it,
  and every year with data, from each module's first year: 2026 for Incident
  & Near Miss, 2000 for Observations and Safety Performance, 2021 for TRIR
  Experience.

## Safety > Safety Observations

Routes: `/safety/observations` (record and review a month) and
`/safety/observations/dashboard`. Code lives in
`apps/api/app/safety/observations/` and
`apps/web/src/features/safety/observations/`.

Each observation is one record: observed date, Safe or Unsafe, Act or
Condition, and a category are required; area / location, description and
corrective action are optional. There is no person, site or
corrective-action workflow yet.

| Endpoint                                              | Permission                 | Purpose |
| ----------------------------------------------------- | -------------------------- | ------- |
| `GET /api/v1/safety/observations/categories`          | `safety.observations.view` | Active categories in display order |
| `GET /api/v1/safety/observations`                     | `safety.observations.view` | Newest first; filters `year`, `month`, `observedFrom`, `observedTo`, `outcome`, `kind`, `categoryId`; `limit` (default 50, max 500), `offset` |
| `GET /api/v1/safety/observations/summary?year=&month=` | `safety.observations.view` | Total, Safe, Unsafe, the four Act / Condition counts, and per-category counts |
| `GET /api/v1/safety/observations/dashboard?year=`     | `safety.observations.view` | Year counts, Unsafe share, monthly and per-category counts (months not yet started are `null`) |
| `POST /api/v1/safety/observations`                    | `safety.observations.edit` | Record one observation |
| `PUT /api/v1/safety/observations/{id}`                | `safety.observations.edit` | Replace its fields; send `expectedUpdatedAt` from the loaded record |
| `DELETE /api/v1/safety/observations/{id}`             | `safety.observations.edit` | Delete it |

- `observedOn` is a `YYYY-MM-DD` date from 2000-01-01 up to today (the
  Baytown date; see "Safety site calendar").
  Optional text is trimmed; blank becomes `null`. Area / location allows 200
  characters, description and corrective action 2,000 each. The database
  enforces the same rules with check constraints.
- Categories are referenced by id. Retired (inactive) categories are rejected
  for new observations; an existing observation keeps its retired category
  unless the editor picks another.
- An update whose `expectedUpdatedAt` no longer matches returns
  `409 edit_conflict` with the current record; nothing is written.
- Every create, update and delete writes one `core.audit_events` row in the
  same transaction (`entity_type = safety.observation`, `entity_key =
  observations/<id>`, full before/after values). Unchanged updates are not
  written or audited. Logs carry ids and counts only, never free text.
- Every count derives from the same records, so Safe + Unsafe and
  Act + Condition both equal Total.

Category display names correct the workbook's spelling ("Housekeepng",
"Tools") and spacing; the workbook labels belong in import mappings only.
**Fire and Fire System are separate categories** because the workbook's Safe
table lists "Fire" and its Unsafe table "Fire system"; merging them needs the
Safety owner's confirmation and a migration.

### Legacy 2026 workbook tallies

The workbook's sheet `SSO-Site -25` holds monthly aggregates, not individual
observations, and its views do not reconcile (category tables 38 Safe + 69
Unsafe = 107; Act / Condition 37 + 79 = 116; typed Total Observations 99).
They are therefore never converted into observations. Migration `0004` seeds
them as four separate sections of the `observations_legacy` metric set (Safe
by category, Unsafe by category, Act / Condition, Total Observations), with no
values. The template
[`apps/api/import_templates/safety_observations_legacy.template.json`](apps/api/import_templates/safety_observations_legacy.template.json)
names the source cells for every category; fill in a reviewed copy and load
it with the same `legacy_import` CLI as Incident & Near Miss. No legacy
observation values have been imported, and the application shows none of
them.

## Retired: Supervisor Safety Contacts

Supervisor Safety Contacts (SSC) was retired in this release. **Its data is
kept**; only the pages and API were removed.

- Removed: the navigation entry, the Safety overview card, the pages
  `/safety/contacts` and `/safety/contacts/dashboard`, the
  `/api/v1/safety/contacts/...` endpoints (now `404`), the
  `safety.contacts.view/edit` permissions, and their tests.
- `/safety/contacts` and anything under it redirect (temporary, `307`) to
  `/safety` (`next.config.ts`), following the retired Incident Analytics
  pattern.
- Kept unchanged: the tables `safety.contact_supervisors` and
  `safety.supervisor_safety_contacts` (migration `0005`), their constraints
  and indexes, their rows, and their audit events. The SQLAlchemy models in
  `apps/api/app/safety/contacts/models.py` stay so the schema remains mapped;
  `tests/test_safety_contacts_database.py` checks the tables and that stored
  rows stay readable, and `tests/test_safety_contacts_retired.py` checks
  that no endpoint or permission remains.
- No migration drops or changes them. Removing the data would need its own
  reviewed migration and an export first.

The previous documentation follows for reference to the stored data.

<details>
<summary>Former Supervisor Safety Contacts reference</summary>

Each contact is one record: one contact credited to one supervisor on one
date. Nothing else is captured (no contacted person, area, notes, type or
checklist). Supervisors are a program list maintained in the application,
not an employee directory or user accounts. The endpoints below no longer
exist.

| Endpoint                                                | Permission             | Purpose |
| ------------------------------------------------------- | ---------------------- | ------- |
| `GET /api/v1/safety/contacts/supervisors`               | `safety.contacts.view` | Every supervisor, active and inactive, alphabetical |
| `POST /api/v1/safety/contacts/supervisors`              | `safety.contacts.edit` | Add a supervisor |
| `PUT /api/v1/safety/contacts/supervisors/{id}`          | `safety.contacts.edit` | Correct name, active, eligibility or effective dates; send `expectedUpdatedAt` |
| `DELETE /api/v1/safety/contacts/supervisors/{id}`       | `safety.contacts.edit` | Remove a supervisor added by mistake; `409 supervisor_has_contacts` once contacts exist |
| `GET /api/v1/safety/contacts`                           | `safety.contacts.view` | Newest first; filters `year`, `month`, `contactFrom`, `contactTo`, `supervisorId`; `limit` (default 50, max 500), `offset` |
| `POST /api/v1/safety/contacts`                          | `safety.contacts.edit` | Credit one contact; an optional `requestId` makes retries return the first contact (`200`) instead of a duplicate |
| `PUT /api/v1/safety/contacts/{id}`                      | `safety.contacts.edit` | Change date or supervisor; send `expectedUpdatedAt` |
| `DELETE /api/v1/safety/contacts/{id}`                   | `safety.contacts.edit` | Delete it (also used by Undo) |
| `GET /api/v1/safety/contacts/summary?year=&month=`      | `safety.contacts.view` | Contacts per supervisor; participation when a month is given |
| `GET /api/v1/safety/contacts/dashboard?year=`           | `safety.contacts.view` | Year total, monthly contacts and participation (months not yet started are `null`), supervisor × month counts |

- `contactDate` is a `YYYY-MM-DD` date from 2000-01-01 up to today. A
  contact must fall within its supervisor's effective period.
- "Today" follows the Safety site calendar (see above). New contacts
  cannot be credited to an inactive supervisor; an existing contact keeps its
  supervisor when edited.
- Supervisor names are trimmed and whitespace-collapsed, at most 100
  characters, and unique ignoring case. An inactive supervisor needs an
  effective end date. Dates cannot be narrowed so that existing contacts fall
  outside them. Inactive supervisors remain in history and the dashboard.
- Stale `expectedUpdatedAt` returns `409 edit_conflict` with the current
  record; nothing is written.
- Every create, update and delete writes one `core.audit_events` row in the
  same transaction (`safety.contact` / `contacts/<id>` and
  `safety.contact_supervisor` / `contact-supervisors/<id>`). Unchanged updates
  are not written or audited. Logs carry ids only, never names.

**Participation** for a month = eligible supervisors with at least one contact
in that month ÷ supervisors eligible for that month. A supervisor counts as
eligible when marked participation-eligible and their effective period
overlaps the month. Both numbers are returned with the rate; the rate is
`null` when no supervisor is eligible. No target is configured or shown, and
supervisors are listed alphabetically without ranking.

### Legacy workbook tallies

The workbook's hidden sheet `SSC-Site -21` holds monthly tallies per
supervisor with no contact dates and no stated year, so they are never
converted into contacts. Migration `0005` seeds no supervisors, contacts or
targets. The template
[`apps/api/import_templates/safety_contacts_legacy.template.json`](apps/api/import_templates/safety_contacts_legacy.template.json)
names the source cells only; nothing in the platform reads it. No legacy
contact data has been imported.

</details>

## Safety > Safety Performance

Routes: `/safety/performance/data-entry` and `/safety/performance/dashboard`.
Code lives in `apps/api/app/safety/performance/` and
`apps/web/src/features/safety/performance/`.

The module stores only monthly worked hours (and, for years before monthly
records, accepted annual figures). Event counts are read, never copied: from
Incident & Near Miss for 2026 onward, and from the `performance_legacy`
metric set for earlier years. No rate, YTD total or rolling total is stored.

| Endpoint                                                          | Permission                | Purpose |
| ----------------------------------------------------------------- | ------------------------- | ------- |
| `GET /api/v1/safety/performance/months?year=`                     | `safety.performance.view` | Each month's hours, status (Not Reported / Reported / Closed) and read-only counts |
| `PUT /api/v1/safety/performance/months/{year}/{month}`            | `safety.performance.edit` | Save total hours, optional hourly/salary split and `monthClosed`; send `expectedUpdatedAt` when the month already has hours |
| `DELETE /api/v1/safety/performance/months/{year}/{month}?expectedUpdatedAt=` | `safety.performance.edit` | Clear a month back to Not Reported |
| `GET /api/v1/safety/performance/dashboard?year=&throughMonth=`    | `safety.performance.view` | YTD and 12MRA rates, YTD hours, monthly trends and annual TRIR |

- `safety.performance_hours`: one row per (year, month); `total_hours`
  `numeric(10,2)` ≥ 0; `hourly_hours` and `salary_hours` optional, ≥ 0, and
  summing to the total when both are given; `month_closed` defaults to false.
  There is no contractor column.
- A month without a row is not reported. A month counts in a rate only when
  it has hours above zero **and** is closed; an open month is never treated
  as zero, and a closed zero-hour month is ineligible (it also ends the
  default YTD). Hours can be entered once a month has started and a month
  can be closed once it has ended (Baytown site date).
- Closing an Incident & Near Miss month (2026 on) confirms its counts are
  complete, so a blank count then means zero. Closing a legacy month (before
  2026) confirms its hours only. **Legacy completeness rule:** a legacy count
  is known only when a value is stored, either typed in the source or a zero
  proven by an independent typed source total. A blank stays unconfirmed,
  and any window for that measure containing it is unavailable
  (`count_not_confirmed`). Other measures are unaffected.
- Every rate is events × 200,000 ÷ worked hours over the same months. YTD
  runs January through the selected month (default: the latest month for
  which January onward is eligible). The 12-Month Rolling Average (12MRA) is
  the 12 months ending in the selected month and is unavailable, with a
  reason, unless all 12 are eligible.
- Numerators: TRIR = recordable injuries + occupational illnesses; First Aid
  = first aid; Loss of Primary Containment (LOPC) = LOPC; Property &
  Equipment Damage = `property_damage + equipment_damage_failure`. The
  current Incident & Near Miss model holds monthly aggregate counts and
  cannot deduplicate an event classified in both, so such an event counts
  twice and the rate is not a count of distinct events. Both counts are
  returned separately. Revisit if Incident & Near Miss becomes
  individual-record based. Legacy years use the
  `performance_legacy` categories `recordable`, `first_aid`, `lopc` and
  `property_equipment_damage`.
- Saves and clears take a per-month advisory lock, return `409 edit_conflict`
  with the current row on a stale `expectedUpdatedAt`, and write one
  `core.audit_events` row (`safety.performance_hours` /
  `performance-hours/YYYY-MM`) in the same transaction. Unchanged saves are
  not written.

### Importing hours and legacy figures

Reviewed mappings live in `apps/api/import_templates/`:
`safety_performance_hours_lcy_ehs.mapping.json` (2025 and January–August
2026 monthly hours; 2021, 2023 and 2024 annual recordables and hours; 2022
excluded) and `safety_performance_legacy_2025_lcy_ehs.mapping.json` (2025
counts, for the Incident & Near Miss CLI). Migration `0006` applies neither.

```bash
cd apps/api
uv run python -m app.safety.performance.legacy_import check <mapping.json>  # validate file, no database
uv run python -m app.safety.performance.legacy_import plan  <mapping.json>  # compare with stored rows
uv run python -m app.safety.performance.legacy_import apply <mapping.json>  # write, audited as "legacy-import"
uv run python -m app.safety.legacy_import plan  <legacy-counts mapping.json>
uv run python -m app.safety.legacy_import apply <legacy-counts mapping.json>
```

`plan` and `apply` refuse when a stored row differs from the mapping, when a
year would have both monthly and annual figures, or when a future month
would be closed. Closure is never inferred from hours: every closed month
in a mapping states its `closedBasis`, which is audited with its `statedIn`
cell. In the 2025 counts mapping, recordables are explicit zeros (TRIR
EXP.!L8 types 0 for 2025). Blank First Aid months (Jan, Feb, May, Sep, Nov)
and blank damage months (Feb, Oct) stay null, so the First Aid and Damage
12MRA through August 2026 are unavailable. Rates!I28 (December 2025
equipment failure) is excluded as a conflict. The workbook does not state
which workers the hours cover. There is no contractor-hours field.

## Safety > TRIR Experience

Route: `/safety/trir` (Safety > TRIR Experience > Experience). A standalone
module comparing LCY's Total Recordable Incident Rate with the industry
benchmark. Code lives in `apps/api/app/safety/trir/` and
`apps/web/src/features/safety/trir/`; the shared rate arithmetic is
`app/safety/rates.py`.

**TRIR = recordable cases × 200,000 ÷ worked hours.** TIR (all incidents ×
200,000 ÷ hours) is a different measure: it appears only as the legacy
workbook figure and is never used or labelled as TRIR.

- **Numerator:** from 2026, Incident & Near Miss Recordable Injury +
  Occupational Illness; before 2026, the pre-platform recordable counts.
- **Denominator:** Safety Performance "Monthly Hours Worked (Total)". TRIR
  Experience stores no monthly hours and never copies them; there is one
  hours source. Years with no monthly hours (2021–2024) use the annual
  man-hours of the approved history.
- **Cutoff:** year to date runs January through the Through month (default:
  the latest month for which every month from January is closed in Safety
  Performance); the rolling 12-month rate needs all 12 months complete. An
  open, unreported, zero-hour or unconfirmed month is never zero: the rate is
  unavailable and the blocking months are listed.
- **Precision:** calculated with `Decimal` at full precision, displayed
  rounded half-up to 2 places. Every displayed TRIR has "View calculation"
  showing the formula, numerator and denominator with their sources, the
  period, the exact and displayed values, and any missing months. The page
  has a Methodology section; `GET /methodology` returns the same text.
- **Benchmark:** the Bureau of Labor Statistics industry average recorded in
  the history per year. The industry (NAICS) and BLS release year are not
  stated in the source. A year without a benchmark shows the latest earlier
  one, labelled with its year.

| Endpoint (`/api/v1/safety/trir/...`, `safety.trir.view`) | Purpose |
| --------------------------- | ------- |
| `experience?year=&through=` | Everything the page shows |
| `current?year=&through=`    | Year-to-date calculation |
| `calculation?year=&through=` | YTD and rolling-12 calculation detail |
| `history?year=&through=`    | One row per year, the selected year live |
| `monthly?year=`             | Per month: hours, recordables, status, YTD |
| `benchmarks`                | Benchmark by year |
| `status?year=&through=`     | Whether the current figure is complete |
| `reconciliation?year=&through=` | Recalculated vs legacy, live vs workbook snapshot, history vs Safety Performance annual rows (warnings only) |
| `methodology`               | Formula, sources, cutoff, rounding, tolerance |

All endpoints are read-only. No workbook cell coordinates are returned; the
source cells stay in the mapping file and the audit trail.

### Importing TRIR history

Migration `0009` adds `safety.trir_annual_facts` (one row per year: annual
recordables, Incident count, annual man-hours, benchmark, legacy displayed
TRIR and TIR). It is seeded only from the reviewed mapping
`apps/api/import_templates/safety_trir_experience_history_lcy_ehs.mapping.json`
(2021–2026), with an operator command that requires `safety.trir.manage` by
policy:

```bash
cd apps/api
uv run python -m app.safety.trir.legacy_import check import_templates/safety_trir_experience_history_lcy_ehs.mapping.json  # no database
uv run python -m app.safety.trir.legacy_import plan  import_templates/safety_trir_experience_history_lcy_ehs.mapping.json
uv run python -m app.safety.trir.legacy_import apply import_templates/safety_trir_experience_history_lcy_ehs.mapping.json  # audited as legacy-import
```

`check` recalculates every year and blocks `apply` on a mismatch with the
legacy figure. A stored year that differs from the file blocks `apply`;
equal years are skipped, so it is idempotent. Blank source cells stay null.

TRIR EXP. is an annual source: each column heading (2021–2026) is the
temporal key of the values under it. Rows are keyed by integer
`reporting_year` only. No month or day is required or invented (no
31 December dates), and annual rows are never reported as missing dates.
That applies only to this history: individual Incident and Near Miss records
still need a real `incidentDate`.

2025 and 2026 are calculated live from Safety Performance. Their history
rows are the workbook snapshot, kept for provenance and reconciliation. The
2026 man-hours (145,194, January–August) are a snapshot, never an annual
denominator: from 2026, a year without Safety Performance monthly hours
shows TRIR as unavailable instead of falling back to the history row.

## shadcn/ui

`apps/web/components.json`, the `cn()` helper in `src/lib/utils.ts`, and the
theme variables in `src/app/globals.css` are in place. Add components with:

```bash
cd apps/web
npx shadcn@latest add button
```
