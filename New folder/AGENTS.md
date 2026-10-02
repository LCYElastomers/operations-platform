# Operations Platform

## Purpose

Modular operations management platform for Quality, Mechanical
Integrity, Safety, Environmental, Procurement, Sales, and future
operational modules.

## Architecture

Frontend:
- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui
- TanStack Query
- TanStack Table
- Apache ECharts

Backend:
- FastAPI
- Pydantic
- SQLAlchemy 2
- Alembic
- PostgreSQL

Infrastructure:
- Docker Compose
- Nginx reverse proxy
- PostgreSQL is currently host-managed

## Application structure

Quality is a top-level module.

The initial production feature is:

Quality
  -> Raw Materials
     -> Moisture Analysis

Mechanical Integrity is another top-level module.

## Security

Security-first design.

- Never expose database credentials to frontend code.
- Never connect frontend directly to PostgreSQL.
- Never commit secrets.
- All API input must be validated.
- Authorization must ultimately be enforced server-side.
- Containers should run as non-root users.
- Production services bind to localhost behind Nginx.
- Use least-privilege database accounts.
- Log security-relevant and ingestion events.
- Do not log secrets or credentials.

## UI

Use a polished industrial SaaS design.

Preserve the established dashboard layout:

1. Left module navigation
2. Top application/status bar
3. Page header
4. Filter bar
5. KPI cards
6. Operational data table
7. Analytical visualizations

Components must be reusable across future modules.

## Engineering principles

- Modular monolith, not microservices.
- Prefer simple implementations.
- No premature abstractions.
- No mocked production data.
- Development fixtures must be explicitly identified as fixtures.
- Preserve raw source data.
- Null and zero must not be treated as equivalent.