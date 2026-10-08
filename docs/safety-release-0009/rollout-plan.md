# Safety release 0009: production rollout plan

**Prepared, not executed.** Nothing in this plan has been run against
production (`operations_platform`). Run it only after review and an explicit
go-ahead. Never type passwords or full connection strings into commands or
tickets: load `DATABASE_URL` from the protected environment file the
operator already uses, and do not echo it.

## Gaps to close first

- **No documented production backup procedure.** The repository has no
  backup or restore runbook, and PostgreSQL is host-managed. Step 2 needs
  the DBA's procedure; this plan does not invent one.
- **No documented production deployment procedure.** The README describes
  Docker Compose for local use and says Nginx "will" front production.
  Step 11 needs the actual deployment procedure.
- Owner decisions listed in `data-quality-report.md` (undated narrative
  passages, ambiguous classifications, the 2022 TRIR conflict, contractor
  hours). Records can be imported later; the release does not depend on
  them.

## Steps

1. **Git review and approved commit.** Review the diff (migration 0009,
   records, TRIR, display controls, SSC retirement, docs). The owner commits;
   record the commit SHA. Check that no `.env`, workbook or generated files
   (`.next`, `__pycache__`, `.pytest_cache`, `.ruff_cache`) are included.
2. **Production backup.** Take a full backup of `operations_platform` with
   the DBA's procedure (gap above) and confirm it can be restored. Do not
   continue without it: 0009's downgrade refuses once records or TRIR
   history exist, so a restore is the rollback for imported data.
3. **Current revision and audit state.** Read-only:
   `uv run alembic current` (expect `0008`), and record row counts of
   `core.audit_events`, `safety.monthly_metric_values`,
   `safety.annual_behavior_counts`, `safety.performance_hours`,
   `safety.contact_supervisors` and `safety.supervisor_safety_contacts`.
4. **Application build.** On the build host: `uv run ruff check .`,
   `uv run ruff format --check .`, `uv run pytest -q` (API);
   `npm ci`, `npm run lint`, `npm run typecheck`, `npm test`,
   `npm run build` (web). All must pass.
5. **Migration.** `uv run alembic upgrade head` (in the deployed stack:
   `docker compose exec api alembic upgrade head`). Expect
   `Running upgrade 0008 -> 0009`. It creates two tables and seeds nothing.
6. **Read-only schema verification.** `uv run alembic current` shows
   `0009 (head)`; `uv run alembic check` reports no drift; the tables
   `safety.incident_records` and `safety.trir_annual_facts` exist and are
   empty; the step 3 counts are unchanged (the SSC tables in particular).
7. **Import check** (no database):
   `uv run python -m app.safety.trir.legacy_import check import_templates/safety_trir_experience_history_lcy_ehs.mapping.json`.
   For narratives, only a reviewed file:
   `uv run python -m app.safety.records.legacy_import check <reviewed review.json>`.
8. **Import plan review.** Run `plan` for each. TRIR expects
   `To insert: [2021, 2022, 2023, 2024, 2025, 2026]`, nothing differing.
   For records, review the per-month documented counts against the totals.
   The owner approves the plan output.
9. **Approved import apply.** Run `apply` for the approved files only
   (audited as `legacy-import`). The narrative import is optional for this
   release; do not apply unreviewed recommendations.
10. **Idempotent re-plan.** Re-run `plan`: TRIR shows
    `To insert: []` with all six years stored; records shows
    `To create: 0`.
11. **Deployment.** Deploy the approved build with the production procedure
    (gap above). The API needs no new settings. Grant the new permissions
    as intended (`safety.incidents.records.view/edit/manage`,
    `safety.incidents.history.view`, `safety.trir.view`, `safety.trir.manage`
    for import operators); `safety.view` / `safety.edit` / `safety.manage`
    cover them.
12. **Browser smoke tests.** Safety overview; Incident & Near Miss Data
    Entry (Records row buttons open the month dialog by mouse and keyboard);
    Dashboard tabs Overview, Area, Incident Analysis, Incident Register,
    Behavior (`?view=` follows the tab, an invalid view shows Overview);
    display controls and "Show all"; a 390 px wide phone viewport without
    horizontal page scrolling.
13. **TRIR source and calculation verification.** `/safety/trir`: YTD
    TRIR for 2026 through the latest closed month; "View calculation"
    numerator and denominator equal the Incident & Near Miss recordables and
    the Safety Performance hours for the same months; history 2021–2024 and
    2025 show calculated values matching the legacy figures except as
    documented; no TIR is labelled TRIR.
14. **Incident Register verification.** Month groups show total versus
    documented and the reconciliation state; filters and search work; with
    a manage permission, Void and Reclassify appear and no Delete appears;
    without it they are hidden.
15. **SSC retirement verification.** `/safety/contacts` and
    `/safety/contacts/dashboard` redirect to `/safety`; no navigation entry
    or card; `GET /api/v1/safety/contacts` returns `404`; the SSC table row
    counts equal step 3.
16. **Workbook unchanged.** `Get-FileHash -Algorithm SHA256` of the source
    workbook equals
    `0B94C09BEDF3C343D3250496780A2D3B66671B55741ABA0391FDE81BE8B51C10`.
17. **Final Git and database status.** `git status` clean at the approved
    commit; `alembic current` = `0009 (head)`; record the counts of
    `safety.incident_records` and `safety.trir_annual_facts` and the
    `legacy-import` audit change sets created.

## Rollback

- Before any import: `uv run alembic downgrade 0008` drops the two new
  tables; redeploy the previous build.
- After an import: the 0009 downgrade refuses (`Cannot downgrade: incident
  records exist` / `TRIR history exists`). Roll back by restoring the step 2
  backup, or keep the schema and redeploy the previous build (it does not
  read the new tables; verify it starts against a 0009 database before
  relying on this). Do not delete rows by hand.
- The SSC retirement changes no data; restoring the previous build restores
  its pages.
