# Operations Platform

Modular operations management platform (Quality, Mechanical Integrity, and
future modules). See [`docs/AGENTS.md`](docs/AGENTS.md) for architecture,
security, and engineering principles.

This repository currently contains the project skeleton only: no
authentication, no data synchronization, and no module dashboards yet.

## Layout

```
apps/
  web/      Next.js (App Router, TypeScript, Tailwind, TanStack Query, shadcn/ui-ready)
  api/      FastAPI (Pydantic, SQLAlchemy 2, Alembic, pytest), managed with uv
compose.yml Docker Compose stack for web + api
docs/       Project guidelines
```

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
# migrations up and down against it. Set it up like production: the `core`
# and `quality` schemas exist and the role has USAGE, CREATE on them.
# Skipped when unset.
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
                          TrendChart, StatusBadge, EmptyState
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
| `MOISTURE_DATA_SOURCE` | api | `fixture` | `fixture` or `database`; `database` requires `DATABASE_URL` |
| `INGESTION_AUTH_MODE` | api | `disabled` | `disabled` or `development-unauthenticated` (refused in production); see Ingestion API |

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
startup. Autogenerate only inspects application-owned schemas (`quality`).

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
| `safety`               | Reserved                                         |
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
- No `CREATE` on `public` and no `CREATE` on the database.

```sql
-- Run as a DBA. Schemas already exist in production.
GRANT USAGE, CREATE ON SCHEMA core, quality TO operations_api;
```

Migration `0001` produces `core.alembic_version` and
`quality.finishing_measurements`. Downgrading it drops
`quality.finishing_measurements` and its data. DBA-owned schemas are never
dropped, and `core.alembic_version` remains (empty).

Current revisions:

| Revision | Creates                           |
| -------- | --------------------------------- |
| `0001`   | `quality.finishing_measurements`  |

## Quality > Raw Materials > Moisture Analysis

The dashboard at `/quality/raw-materials/moisture` reads only from the FastAPI
contract below. Code lives in `apps/api/app/quality/moisture/` and
`apps/web/src/features/quality/moisture/`.

| Endpoint                              | Returns                                                         |
| ------------------------------------- | --------------------------------------------------------------- |
| `GET /api/v1/quality/moisture/recent`  | Newest matching records first (`limit`, default 50, max 500)    |
| `GET /api/v1/quality/moisture/trends`  | All matching records oldest first, plus summary means           |
| `GET /api/v1/quality/moisture/filters` | Distinct products and locations, and source date boundaries     |

`/recent` and `/trends` accept `product` and `location` (exact match),
`search` (case-insensitive substring of lot or campaign number), and
`startDate` / `endDate` (inclusive, `YYYY-MM-DD`). Unknown or invalid
parameters return HTTP 422.

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
  Summary means skip nulls, include zeros, and are `null` when no values exist.
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

`(source_system, source_row_hash)` is unique, so re-delivering an identical
row is a no-op (`insert_source_rows` in `ingestion.py` uses
`ON CONFLICT DO NOTHING`). The hash covers all eight source fields after
canonicalization: `26101` and `"26101"` hash alike, but `null` and `0`
differ, and text is never trimmed or case-folded. A row whose values change
in the source therefore produces a new hash and a new row; reconciling
corrections is a decision for the future sync agent.

Float measurements are stored via their shortest round-trip representation
(`0.43333333333333335` stays exactly that), so values read back unchanged.

The API reads from the fixture or the database depending on
`MOISTURE_DATA_SOURCE`. Both implement the same repository interface
(`repository.py`), so the HTTP contract is identical; only
`dataSource.kind` / `isFixture` / `label` change. No historical data has
been imported yet, so keep `MOISTURE_DATA_SOURCE=fixture` until it has.

### Development fixture

Until synchronization exists, the API serves
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

**Authentication.** Connector credentials are not implemented yet, so the
endpoint fails closed: with `INGESTION_AUTH_MODE=disabled` (the default)
every request gets `503 ingestion_disabled` before the body is read.
`INGESTION_AUTH_MODE=development-unauthenticated` opens it for local
development only. The API refuses to start with that mode when
`ENVIRONMENT=production`, and each request through it logs a warning. Real
connector credentials will replace it behind the same dependency
(`app/core/machine_auth.py`).

**Request** (`Content-Type: application/json`, at most 5 MiB):

```json
{
  "sourceSystem": "access-qryFINISHING-AVG",
  "batchId": "2026-10-02T16-40-00Z-0001",
  "extractedAt": "2026-10-02T16:40:00Z",
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
| `batchId`      | Same rules. Chosen by the connector; used for tracing, not identity      |
| `extractedAt`  | ISO 8601 date-time **with** a timezone offset                             |
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
| `sourceRowHash` | —                           | Optional. If sent, must equal the server-computed hash    |

Every row field except `sourceRowHash` must be present; send `null`
explicitly for a missing value. Unknown fields are rejected. Values are
stored exactly as sent: no trimming, case changes, or location
normalization; JSON numbers are parsed as exact decimals (no float
rounding); `null` is stored as NULL, never as 0. Numbers are not
range-checked: there are no specifications, thresholds, or outlier rules.

**Identity and idempotency.** The server computes `source_row_hash`
(SHA-256 over the canonicalized row; see `compute_source_row_hash`). Rows
are unique on `(sourceSystem, source_row_hash)`, so re-sending a batch, a
row, or overlapping batches never creates duplicates. `batchId` is not part
of the identity. A row whose values change in Access hashes differently and
is stored as a new row.

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
  "rejections": [
    { "rowIndex": 2, "errors": [{ "field": "sourceDate", "message": "Value error, is not a valid calendar date" }] }
  ],
  "rejectionsTruncated": false
}
```

- `status`: `accepted` (no rejections), `accepted_with_rejections`, or
  `rejected` (every row invalid; nothing written).
- `receivedRows = insertedRows + duplicateRows + rejectedRows`.
  `duplicateRows` counts rows already stored or repeated within the batch.
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
| 413    | `payload_too_large`      | Body over 5 MiB                                                    |
| 415    | `unsupported_media_type` | Content-Type is not `application/json`                             |
| 422    | `validation_error`       | Envelope invalid (metadata, empty batch, too many rows); nothing processed. Includes `errors` |
| 503    | `ingestion_disabled`     | Ingestion is not enabled on this server                            |
| 503    | `database_unavailable`   | Database failure. Nothing from the batch was committed; resubmit   |

**Transactions.** All valid rows of a batch are written in one database
transaction, split into multi-row statements of 1000 rows. A database
failure at any point rolls back the whole batch.

**Logging.** One line per batch, for example:
`event=finishing_ingestion result=accepted batch_id=... source_system=...
connector=... extracted_at=... received=3 inserted=1 duplicates=1 rejected=1
rejected_fields=sourceDate:1`. The same fields are attached to the log record
as `record.ingestion`. Row values, request bodies, headers, and database
error text (which can contain SQL parameters) are never logged. Database
failures log only the exception type.

## shadcn/ui

`apps/web/components.json`, the `cn()` helper in `src/lib/utils.ts`, and the
theme variables in `src/app/globals.css` are in place. Add components with:

```bash
cd apps/web
npx shadcn@latest add button
```
