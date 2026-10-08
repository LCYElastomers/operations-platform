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

# Optional: PostgreSQL integration tests (migrations, persistence, repository).
# Point at a disposable database whose name contains "test"; the tests run
# migrations up and down against it. Set it up like production: the `core`,
# `quality` and `safety` schemas exist and the role has USAGE, CREATE on them
# (the `core` schema is required; the tests refuse to run without it).
# The session ends at base, so run `alembic upgrade head` against it afterwards
# if you use it for local development. The 0003 downgrade refuses while Safety
# values or audit events exist, so clear those first. Skipped when unset.
TEST_DATABASE_URL=postgresql+psycopg://<user>:<password>@localhost:5432/operations_platform_test uv run pytest

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
                          EmptyState
  components/modules/     ModuleNotConfigured (standard page for modules
                          without a connected data source)
  components/system/      API health status
  components/ui/          shadcn/ui primitives
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
| `USER_AUTH_MODE` | api | `disabled` | `disabled` or `development-unauthenticated` (refused in production); see Authorization |
| `DEVELOPMENT_USER_PERMISSIONS` | api | `["safety.view","safety.edit"]` | JSON list of permissions held by the development user |

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

Downgrading `0002` drops `core.ingestion_batches` and the versioning
columns. It refuses to run while superseded measurement versions exist,
because they would otherwise become indistinguishable from current rows.

Downgrading `0003` refuses to run while any Safety monthly value or audit
event exists, so entered data and its history are never dropped silently.
Downgrading `0004` likewise refuses while any observation or legacy
observation value exists. Downgrading `0005` refuses while any supervisor or
supervisor safety contact exists. Downgrading `0006` refuses while any
worked-hours row, annual legacy row or `performance_legacy` value exists.

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

## Authorization

There is no login yet. Interactive endpoints are protected by
`require_permission(...)` (`app/core/authorization.py`), which resolves the
user through `get_user_principal`. Adding authentication later replaces only
`get_user_principal`; endpoints and permission checks stay unchanged.

Permissions are defined once in `app/core/permissions.py` as
`<module>[.<function>].<action>`. A grant covers its scope and every function
under it, and `edit` implies `view`:

| Granted                    | Satisfies                                                         |
| -------------------------- | ----------------------------------------------------------------- |
| `safety.view`              | `safety.view`, `safety.incidents.view`, `safety.observations.view`, `safety.contacts.view`, `safety.performance.view` |
| `safety.edit`              | everything above plus `safety.edit`, `safety.incidents.edit`, `safety.observations.edit`, `safety.contacts.edit`, `safety.performance.edit` |
| `safety.incidents.view`    | `safety.incidents.view` only                                      |
| `safety.incidents.edit`    | `safety.incidents.view`, `safety.incidents.edit`                  |
| `safety.observations.view` | `safety.observations.view` only                                   |
| `safety.observations.edit` | `safety.observations.view`, `safety.observations.edit`            |
| `safety.contacts.view`     | `safety.contacts.view` only                                       |
| `safety.contacts.edit`     | `safety.contacts.view`, `safety.contacts.edit`                    |
| `safety.performance.view`  | `safety.performance.view` only                                    |
| `safety.performance.edit`  | `safety.performance.view`, `safety.performance.edit`              |

Endpoints always require the most specific permission (for example
`safety.incidents.view` or `safety.observations.edit`), so grants can be
narrowed to one function without changing endpoints.

| `USER_AUTH_MODE`              | Behaviour                                                       |
| ----------------------------- | --------------------------------------------------------------- |
| `disabled` (default)          | Requests are anonymous; protected endpoints return `401 authentication_required` |
| `development-unauthenticated` | Local development only (refused in production). Requests act as `development-user` with `DEVELOPMENT_USER_PERMISSIONS` |

A user lacking a permission receives `403 permission_denied`. Denials are
logged as `event=authorization result=denied`.

## Audit trail

`core.audit_events` is the platform audit trail for user data changes. One
row per changed entity records `actor_id`, `occurred_at`, `action`
(`create`/`update`/`delete`), `entity_type`, `entity_key`, `old_value` and
`new_value` (JSONB), and a `change_set_id` grouping all rows of one save.
Audit rows are written in the same transaction as the change. Write them with
`app.audit.recorder.record_changes`. The Audit Log page does not display them
yet.

## Safety > Incident & Near Miss

Routes: `/safety` (overview), `/safety/incidents/data-entry`,
`/safety/incidents/dashboard`, `/safety/incidents/analytics`. Code lives in `apps/api/app/safety/` and
`apps/web/src/features/safety/incidents/`; the spreadsheet grid
(`MonthlyGrid`) and `BarChart` are shared components in
`apps/web/src/components/common/`.

| Endpoint                                   | Permission              | Purpose |
| ------------------------------------------ | ----------------------- | ------- |
| `GET /api/v1/safety/incidents/metrics?year=` | `safety.incidents.view` | Sections, categories, 12 monthly values and calculated YTD per category, `canEdit`, `yearsWithData` |
| `PATCH /api/v1/safety/incidents/metrics`   | `safety.incidents.edit` | Set or clear cells: `{"year": 2026, "changes": [{"categoryId", "month", "value", "previousValue"}]}` |
| `GET /api/v1/safety/incidents/analytics?year=&through=` | `safety.incidents.view` | Read-only analytics January..`through`; see "Analytics" below |

Data Entry, Dashboard and Analytics read the same stored rows.

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
Incident. Dashboard Incident and Near Miss KPIs and trends read only the
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

### Analytics (Phase 1)

`/safety/incidents/analytics` (Incident & Near Miss > Analytics) and
`GET /api/v1/safety/incidents/analytics?year=&through=` are read-only. They
calculate everything on each request from the stored `incidents` monthly
values (`app/safety/analytics.py`); nothing is stored, copied or imported,
and the workbook is never read. The GET writes no rows and no audit events.
Both require `safety.incidents.view`; there is no separate permission. The
navigation entry is shown like the other Safety entries; without the
permission the page shows "not available to you" (the API answers `403`).

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
  by Analytics, so PIT is never counted twice.
- **Damage**: `property_damage` and `equipment_damage_failure`, shown side by
  side. Combined damage = Property Damage + Equipment Damage classifications,
  not a count of distinct events. A combined month is null only when both
  parts are unreported, and reported only when both are. The stale
  `property_equipment_damage` section is not read by Analytics.
- **PIT Incidents YTD** and **Property & Equipment Damage YTD** cards use the
  same series as the charts. The damage card shows its composition (e.g.
  "6 property · 8 equipment"); when either part has unreported months its
  total adds the reported months and is labelled partial, never complete.
- **PSIF** is shown as recorded. The application does not define PSIF, and
  shows no PSIF frequency, share, ratio, severity or rating; it is not
  merged with the Near Miss Potential "SIF".
- No targets, scores or red/yellow/green colours. Every chart has a data
  table alternative.

Phase 1 does **not** contain area analytics (incidents or near misses by
area, area by classification), Near Miss Cause, Near Miss Potential, LOPC
contributing factors, Process Safety Incidents, or the Behavior Pareto. These
need structured data the platform does not hold and are deferred to Phase 2.
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
  Observations month and observed date, the Contacts date, the Incident &
  Near Miss Analytics through month) move to the new
  day; a value the user chose is kept until they change it or press "Use
  today". A default never moves while it holds unsaved work (Incident &
  Near Miss or Safety Performance hours being edited, an Observation being
  edited or deleted, a chosen "through" month).
- Year selectors always offer the current Baytown year, the four before it,
  and every year with data, from each module's first year: 2026 for Incident
  & Near Miss, 2000 for Observations, Contacts and Safety Performance.

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

## Safety > Supervisor Safety Contacts

Routes: `/safety/contacts` (tally board, recent contacts, supervisor list) and
`/safety/contacts/dashboard`. Code lives in `apps/api/app/safety/contacts/`
and `apps/web/src/features/safety/contacts/`.

Each contact is one record: one contact credited to one supervisor on one
date. Nothing else is captured (no contacted person, area, notes, type or
checklist). Supervisors are a program list maintained in the application,
not an employee directory or user accounts.

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

## shadcn/ui

`apps/web/components.json`, the `cn()` helper in `src/lib/utils.ts`, and the
theme variables in `src/app/globals.css` are in place. Add components with:

```bash
cd apps/web
npx shadcn@latest add button
```
