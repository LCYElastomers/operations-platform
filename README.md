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
# migrations up and down against it. Skipped when unset.
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

Privileges needed by the role that runs migrations:

- `CREATE` on the database, unless a DBA pre-creates the `quality` schema
  and grants the role `USAGE, CREATE` on it.
- `CREATE` on schema `public` for Alembic's `alembic_version` table (or
  pre-create that table).

Downgrading revision `0001` drops `quality.finishing_measurements` and its
data. It drops the `quality` schema only when that schema is empty and owned
by the migrating role.

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

## shadcn/ui

`apps/web/components.json`, the `cn()` helper in `src/lib/utils.ts`, and the
theme variables in `src/app/globals.css` are in place. Add components with:

```bash
cd apps/web
npx shadcn@latest add button
```
