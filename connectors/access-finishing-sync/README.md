# access-finishing-sync

Windows sync agent that reads the Microsoft Access saved query
`qryFINISHING-AVG` through ODBC and submits it to the Operations Platform
ingestion API (`POST /api/v1/ingestion/quality/finishing/batches`) as an
**authoritative date-window reconciliation** (strategy B in the API README).

It is an independent Python application. The API never imports it, and it is
not part of the API Docker image (that image is built from `apps/api` only).
It never connects to PostgreSQL and never modifies the Access database.

Contents:

- [How a run works](#how-a-run-works)
- [Exit codes](#exit-codes)
- [1. Supported Python version](#1-supported-python-version)
- [2. Access Database Engine / ODBC driver](#2-access-database-engine--odbc-driver)
- [3. 32-bit versus 64-bit](#3-32-bit-versus-64-bit)
- [4. Installation](#4-installation-in-a-virtual-environment)
- [5. Configuration](#5-configuration)
- [6. Windows Credential Manager](#6-windows-credential-manager-setup)
- [7-10. Commands](#7-10-commands)
- [11. Task Scheduler](#11-windows-task-scheduler-setup)
- [12. Working directory](#12-recommended-working-directory)
- [13. Service account permissions](#13-service-account-permissions)
- [14. Access file permissions](#14-read-permission-on-the-access-file-and-folder)
- [15. HTTPS certificate trust](#15-https-certificate-trust)
- [16. Credential rotation](#16-credential-rotation)
- [17. Logs](#17-log-location-and-retention)
- [18. Troubleshooting](#18-troubleshooting)
- [19. Disabling the task](#19-disabling-the-scheduled-task)
- [20. Rollback](#20-rolling-back-the-agent)
- [21. Changing RECONCILIATION_DAYS](#21-changing-reconciliation_days)
- [22. Why an empty or incomplete window is never submitted](#22-why-an-empty-or-incomplete-window-is-never-submitted)
- [Data handling](#data-handling)
- [Development](#development)

## How a run works

`--run-once`:

1. Acquires an OS file lock for this connector and source system (exit 3 if
   another run holds it).
2. Reads the connector secret from Windows Credential Manager.
3. Calculates the window: `end` = today's local date, `start` = `end` minus
   `RECONCILIATION_DAYS - 1` days (inclusive).
4. Opens the Access database read-only and runs:

   ```sql
   SELECT [DATE], [CAMPNO], [LOT], [Location], [PRODUCT],
          [AvgOfMOISTURE], [AvgOfCOLOR], [AvgOfCombined_BD]
   FROM [qryFINISHING-AVG]
   WHERE [DATE] >= ? AND [DATE] < ?
   ORDER BY [DATE], [CAMPNO], [LOT], [Location], [PRODUCT]
   ```

   The parameters are midnight on `start` and midnight on the day **after**
   `end`, so `DATE` values carrying a time of day on the last day are included.
5. Maps and validates every row locally (no values are altered; see
   [Data handling](#data-handling)).
6. Fails closed, sending nothing, if the window is empty, any row failed
   local validation, or the window has more rows than `BATCH_SIZE` (the API
   accepts at most 5000 rows per request).
7. Builds **one** request containing the whole window, with
   `reconciliationWindow` set to exactly the extracted range and a fresh
   `batchId` (`<source>:<connector>:<UTC timestamp>:<UUID>`), and serializes
   it once.
8. Submits it with `X-Connector-Id` and `Authorization: Bearer <secret>`.
   Transient failures are retried with the same bytes and the same `batchId`,
   so a retry after an uncertain failure is replayed by the server, not
   applied twice.
9. Validates the server's result, logs the counts, and exits with a
   meaningful code.

**Why one request per window.** The API applies a reconciliation window per
request: rows stored for that range but missing from the request are
superseded. The API has no atomic multi-request reconciliation, so sending
a window in several parts would let each part supersede the others' rows. A
window larger than one request is therefore refused locally. Reduce
`RECONCILIATION_DAYS`, or enhance the server contract atomically first. Append
mode (no window) is never used as a fallback.

## Exit codes

| Code | Meaning | Typical action |
| ---- | ------- | -------------- |
| 0 | Success (also when the server replayed an earlier identical submission) | None |
| 2 | Configuration error, including a missing or invalid secret | Fix configuration or the stored credential |
| 3 | Another run of this connector configuration is active | Usually none; investigate if persistent |
| 4 | ODBC/Access unavailable (driver, architecture, file, query, columns) | See troubleshooting |
| 5 | Extraction or local validation failure, empty window, window too large | Attention required; see the log |
| 6 | Authentication/authorization failure (401, 403) | Check secret, connector ID, allowed source systems |
| 7 | Permanent API rejection (400, 404, 409 `stale_batch` / `batch_id_conflict`, 413, 415, 422) | Attention required |
| 8 | Transient/network failure after all retries (connect, timeout, 429, 502, 503, 504) | Next scheduled run retries; investigate if repeated |
| 9 | Partial acceptance: the server rejected some rows (the window was **not** applied) | Attention required; fix the source rows |
| 10 | Unexpected response or internal connector error | Investigate |

Every run ends with a `run_finished` log event whose `status` is `success`,
`attention_required`, or `failed`.

## 1. Supported Python version

Python **3.12 or later** for Windows (tested with 3.13). Use the python.org
installer or `uv python install 3.13`. The Python architecture must match the
Access ODBC driver (next two sections).

## 2. Access Database Engine / ODBC driver

The connector needs the **Microsoft Access Driver (\*.mdb, \*.accdb)** ODBC
driver. It is provided by Microsoft Access, or by the free *Microsoft Access
Database Engine 2016 Redistributable* on hosts without Office.

List the installed Access drivers:

```powershell
Get-OdbcDriver -Name '*Access*' | Select-Object Name, Platform
```

Set `ACCESS_ODBC_DRIVER` to the exact name shown. The modern driver opens both
`.accdb` and `.mdb` files. The legacy `Microsoft Access Driver (*.mdb)`
(32-bit only) opens `.mdb` files only.

## 3. 32-bit versus 64-bit

ODBC drivers are architecture specific:

- 64-bit Python can only use a 64-bit Access driver.
- 32-bit Python can only use a 32-bit Access driver.

Check the Python architecture:

```powershell
.\.venv\Scripts\python.exe -c "import struct; print(struct.calcsize('P') * 8, 'bit')"
```

`--check-odbc` reports the Python architecture and the Access drivers
visible to it. If the configured driver is missing, it explains that a
driver installed for the other architecture is invisible.

You cannot install the 64-bit Access Database Engine alongside 32-bit Office
(Click-to-Run) and vice versa. On a host with 32-bit Office, use 32-bit
Python. Otherwise prefer 64-bit Python with the 64-bit engine.

## 4. Installation in a virtual environment

Runtime dependencies are `httpx`, `pyodbc`, and `truststore`; exact versions
and hashes are locked in `uv.lock`. Development-only tools (`pytest`,
`ruff`) are in the `dev` dependency group and are not installed in production.

With [uv](https://docs.astral.sh/uv/) (recommended):

```powershell
$base = 'C:\OperationsPlatform\access-finishing-sync'
# Copy this directory (a release of connectors\access-finishing-sync) to $base\app
cd "$base\app"
$env:UV_PROJECT_ENVIRONMENT = "$base\.venv"
uv sync --frozen --no-dev --python 3.13
```

Without uv, export the locked requirements on a build machine and install
them with hash checking:

```powershell
uv export --frozen --no-dev --no-emit-project --format requirements-txt > requirements.txt
py -3.13 -m venv C:\OperationsPlatform\access-finishing-sync\.venv
C:\OperationsPlatform\access-finishing-sync\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt
C:\OperationsPlatform\access-finishing-sync\.venv\Scripts\python.exe -m pip install --no-deps .
```

Either way, the entry point is
`C:\OperationsPlatform\access-finishing-sync\.venv\Scripts\access-finishing-sync.exe`
(`python -m access_finishing_sync` is equivalent).

## 5. Configuration

Settings come from a TOML file (`--config <path>` or the
`ACCESS_SYNC_CONFIG` environment variable) and/or environment variables of
the same names. Environment variables win. Start from
[`connector.example.toml`](connector.example.toml) and save it as
`connector.toml`, which is git-ignored. The file never contains the secret,
and the connector refuses to start if it finds a secret-like key in it.

| Setting | Default | Notes |
| ------- | ------- | ----- |
| `API_BASE_URL` | required | `https://...`. No credentials, query, or fragment in the URL |
| `CONNECTOR_ID` | `lcy-access-sync` | Sent as `X-Connector-Id` |
| `ACCESS_DATABASE_PATH` | required | Absolute `.accdb`/`.mdb` path; use UNC paths for shares. Must not contain `;`, `{` or `}` |
| `ACCESS_ODBC_DRIVER` | required | Exact driver name |
| `ACCESS_QUERY_NAME` | `qryFINISHING-AVG` | Saved query to select from |
| `SOURCE_SYSTEM` | `access-qryFINISHING-AVG` | Must be allowed for the connector on the server |
| `RECONCILIATION_DAYS` | `60` | Window length in calendar days (1-3660) |
| `BATCH_SIZE` | `5000` | Maximum rows in the single window request (1-5000) |
| `HTTP_CONNECT_TIMEOUT_SECONDS` | `10` | Connection timeout |
| `HTTP_READ_TIMEOUT_SECONDS` | `120` | Response timeout (the server processes the whole window) |
| `HTTP_MAX_ATTEMPTS` | `5` | Attempts for transient failures (1-10) |
| `LOG_DIRECTORY` | required | Absolute path |
| `LOCK_DIRECTORY` | required | Absolute path, local disk |
| `LOG_MAX_BYTES` | `10485760` | Rotate the log file at this size |
| `LOG_BACKUP_COUNT` | `10` | Rotated files kept |
| `CREDENTIAL_TARGET` | `operations-platform/<CONNECTOR_ID>` | Credential Manager target name |
| `SECRET_SOURCE` | `credential-manager` | `environment` reads `CONNECTOR_SECRET`; development only |
| `DEVELOPMENT_MODE` | `false` | **Non-production.** Allows `http://localhost` / `http://127.0.0.1` and `SECRET_SOURCE=environment` |

Restrict the file's NTFS permissions to administrators (full control) and
the service account (read). It holds no secret, but it decides where data is
sent.

**Development mode is not for production.** With `DEVELOPMENT_MODE=true`
the connector also accepts plain HTTP, but only to `localhost` or
`127.0.0.1`, and may read the secret from the `CONNECTOR_SECRET` environment
variable. Never enable it on a production host. There is no setting, in any
mode, that disables TLS certificate verification.

## 6. Windows Credential Manager setup

The secret is stored as a *generic credential* in the Credential Manager of
the Windows account that runs the task. Credential Manager is per user, so
store it **as the service account**:

```powershell
# Open a shell as the service account (loads its profile).
runas /user:LCY\svc-ops-access-sync powershell.exe

# In that shell. /pass without a value prompts, so the secret never appears
# on a command line or in history:
cmdkey /generic:operations-platform/lcy-access-sync /user:lcy-access-sync /pass

# Verify (does not show the secret):
cmdkey /list:operations-platform/lcy-access-sync
```

- The target name must match `CREDENTIAL_TARGET`, which defaults to
  `operations-platform/<CONNECTOR_ID>`.
- The user name stored with the credential is informational only; the
  connector ID comes from `CONNECTOR_ID`.
- Never use `cmdkey ... /pass:<secret>`, scripts, or files to store it.
- If the account may not log on interactively, an administrator must grant
  that right temporarily for this step, then remove it again.
- Run `--check-config` (as the service account) to confirm the secret can
  be read.

The secret itself is issued by the platform administrator
(`python -m app.core.machine_auth new-secret` on the API side), who
registers only its SHA-256 digest on the server. Transfer it through an
approved secure channel and type or paste it at the `cmdkey` prompt.

## 7-10. Commands

Run from the working directory, as the service account:

```powershell
cd C:\OperationsPlatform\access-finishing-sync
$exe = '.\.venv\Scripts\access-finishing-sync.exe'
$cfg = 'C:\OperationsPlatform\access-finishing-sync\connector.toml'
```

**7. `--check-config`**: validates configuration and confirms the secret can
be read from Credential Manager. It does not print the secret, query Access,
contact the API, or write log or lock files.

```powershell
& $exe --check-config --config $cfg; "exit code: $LASTEXITCODE"
```

**8. `--check-odbc`**: checks that the driver is visible to this Python
architecture, opens the database read-only, selects the query with
`SELECT TOP 1 *`, verifies the eight expected columns, and retrieves at most
one test row (whose values are never logged). No HTTP request and no secret
are involved.

```powershell
& $exe --check-odbc --config $cfg; "exit code: $LASTEXITCODE"
```

**9. `--dry-run`**: calculates the window and performs the complete
extraction, mapping, validation, and fail-safe checks. It reports counts and
field-level validation failures, sends nothing, and writes no payload to
disk. Use it before the first scheduled run and after any configuration
change.

```powershell
& $exe --dry-run --config $cfg; "exit code: $LASTEXITCODE"
```

**10. `--run-once`**: one full extraction and authenticated, authoritative
submission. This is what Task Scheduler runs.

```powershell
& $exe --run-once --config $cfg; "exit code: $LASTEXITCODE"
```

Each command prints a one-line summary (for example
`run-once: success (exit code 0)`) to standard output and JSON log events to
standard error.

## 11. Windows Task Scheduler setup

Do not schedule the task until `--check-config`, `--check-odbc`, and
`--dry-run` succeed as the service account. Register it as an administrator,
for example with PowerShell:

```powershell
$base = 'C:\OperationsPlatform\access-finishing-sync'
$account = 'LCY\svc-ops-access-sync'

$action = New-ScheduledTaskAction `
    -Execute "$base\.venv\Scripts\access-finishing-sync.exe" `
    -Argument "--run-once --config `"$base\connector.toml`"" `
    -WorkingDirectory $base

# Hourly, starting a few minutes from now.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
    -RepetitionInterval (New-TimeSpan -Hours 1)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable

# Prompted; used only to register the task. Never put it in a script.
$credential = Get-Credential $account
Register-ScheduledTask -TaskPath '\OperationsPlatform\' `
    -TaskName 'Access finishing sync' `
    -Action $action -Trigger $trigger -Settings $settings `
    -User $credential.UserName `
    -Password $credential.GetNetworkCredential().Password `
    -RunLevel Limited
```

What this gives you, and why:

- **Runs whether or not a user is logged on.** Registering with the account's
  password creates a "Run whether user is logged on or not" task. Do **not**
  tick "Do not store password": without a stored password the task cannot
  read Credential Manager.
- **Dedicated least-privilege account** (`-RunLevel Limited`, no
  administrator rights); see section 13.
- **Fixed working directory** (`-WorkingDirectory`) and absolute paths in
  `connector.toml`.
- **No secret in the arguments.** The only argument besides the action is
  the config path.
- **No concurrent runs.** `-MultipleInstances IgnoreNew` skips a trigger
  while a run is active, and the connector's own lock (exit 3) covers manual
  runs.
- **Exit codes are captured.** Task Scheduler records the process exit code
  as *Last Run Result* (for example `0x9` for exit code 9) and in the task
  history (event ID 201, "Action completed", with the return code). Alert
  on any non-zero result.
- **Execution timeout: 30 minutes.** The worst case is the Access extraction
  (usually seconds to a few minutes) plus 5 HTTP attempts of up to
  10 s + 120 s each and up to 4 waits of at most 120 s. That is about
  20 minutes plus extraction.
- **No automatic retry of permanent failures.** Do not configure "If the
  task fails, restart every ...". Transient failures are already retried
  inside the run with bounded backoff. Configuration and authentication
  failures (exit codes 2 and 6) need a person: alert on them, and disable the
  task (section 19) until they are fixed rather than letting it fail every
  hour.

The equivalent settings can be made in the Task Scheduler UI: on the General
tab select "Run whether user is logged on or not"; on the Settings tab choose
"Do not start a new instance", "Stop the task if it runs longer than
30 minutes", and leave "If the task fails, restart" off.

## 12. Recommended working directory

```
C:\OperationsPlatform\access-finishing-sync\
    app\            connector release (this directory)
    .venv\          virtual environment
    connector.toml  local configuration (no secret)
    logs\           LOG_DIRECTORY
    locks\          LOCK_DIRECTORY
```

Use that directory as the task's working directory. Keep `LOCK_DIRECTORY`
on a local disk: byte-range locks on network shares are unreliable.

## 13. Service account permissions

Use a dedicated domain or local account (for example
`LCY\svc-ops-access-sync`), not a personal or administrator account.

| Resource | Permission |
| -------- | ---------- |
| Local security policy | **Log on as a batch job** (required for scheduled tasks) |
| `...\access-finishing-sync\app` and `.venv` | Read & execute |
| `connector.toml` | Read |
| `logs\`, `locks\` | Modify |
| Access database folder and file | Read (see section 14) |
| Network | Outbound HTTPS to the API host only |
| Credential Manager | Its own profile only (section 6) |

The account needs no rights on PostgreSQL, the API server, or any other
part of the platform. It authenticates to the API only with its connector
secret.

## 14. Read permission on the Access file and folder

The account needs **Read** on the `.accdb`/`.mdb` file and **List folder
contents / Read** on its folder (and share-level read access for UNC paths).
Mapped drive letters are not available to scheduled tasks, so use the UNC
path.

The connection string is always exactly:

```text
DRIVER={<ACCESS_ODBC_DRIVER>};DBQ=<ACCESS_DATABASE_PATH>;ReadOnly=1;
```

There is no code path that opens the database without `ReadOnly=1`. On top
of that, the connector first also requests the ODBC read-only access-mode
connection attribute (`SQL_ATTR_ACCESS_MODE`, pyodbc `readonly=True`):

1. If that succeeds, `odbc_connection_opened` logs `readonly_attribute: true`.
2. If the driver rejects the attribute as unsupported or invalid (SQLSTATE
   `HY024`, `HYC00`, `HY092` or `IM001`; the 32-bit Access driver on some
   hosts returns `HY024`), the connector logs
   `odbc_access_mode_attribute_rejected` with that SQLSTATE and retries
   **exactly once** with the same `ReadOnly=1` connection string and no
   attribute. On success, `odbc_connection_opened` logs
   `readonly_attribute: false` and `access_mode_sqlstate`.
3. Any other SQLSTATE on the first attempt (for example a locked, missing
   or corrupt database) is reported as-is and is never retried.

The connector only ever executes single `SELECT` statements. Anything else
is refused before it reaches the driver, so tables, queries and records are
never modified.

Access normally creates a `.laccdb` / `.ldb` lock file next to the database
when it is opened. A reader that cannot create that file can affect how
other users can open the database while the connector is connected. Run
`--check-odbc` and `--dry-run` while users have the database open. If
opening conflicts appear, an administrator may grant the account
permission to create files in that folder (for the lock file only). The
connector's connection stays read-only either way.

## 15. HTTPS certificate trust

The server certificate is validated against the **Windows certificate
store** (via `truststore`), including hostname checking and TLS 1.2 or
newer. If the API uses an internal CA, install the CA certificate in
*Local Computer > Trusted Root Certification Authorities* (or the
intermediate store, as appropriate). There is intentionally no option to
disable certificate validation. A certificate error is retried as a
connection failure and ends with exit code 8 (`failure: connect` in the
log).

Outbound proxies are taken from the standard `HTTPS_PROXY` / `NO_PROXY`
environment variables if set. Redirects are never followed, so the secret is
only sent to `API_BASE_URL`.

## 16. Credential rotation

The server accepts up to five secret digests per connector, so rotation
needs no downtime and no change to the payload format:

1. The platform administrator generates a new secret
   (`python -m app.core.machine_auth new-secret`), adds its digest to the
   connector's `secret_sha256` list next to the old one, and restarts the API.
2. On the Windows host, as the service account, re-run
   `cmdkey /generic:operations-platform/lcy-access-sync /user:lcy-access-sync /pass`
   and enter the new secret. This overwrites the old credential.
3. Run `--check-config`, then `--run-once` (or wait for the next scheduled
   run) and confirm exit code 0.
4. The administrator removes the old digest and restarts the API.

If exit code 6 appears after a rotation, the stored secret and the server
digests do not match.

## 17. Log location and retention

Logs are written to `LOG_DIRECTORY\access-finishing-sync.log` as JSON lines,
and to standard error. The file rotates at `LOG_MAX_BYTES` (10 MiB) and keeps
`LOG_BACKUP_COUNT` (10) old files, so at most about 110 MiB. Adjust both to
your retention policy.

Each event carries `run_id`, `connector_id`, and `source_system`. The main
events are:

| Event | Fields |
| ----- | ------ |
| `run_started` | action, API host, database file name, query name |
| `window_calculated` | `window_start`, `window_end`, `days`, `query_upper_bound_exclusive` |
| `odbc_access_mode_attribute_rejected` | `sqlstate` of the rejected read-only attribute (a single retry follows) |
| `odbc_connection_opened` | `readonly_attribute`, `readonly_connection_string` (always true), `access_mode_sqlstate`, database file name |
| `odbc_probe` | `python_architecture`, `readonly_attribute`, `column_count`, `missing_columns`, `test_row_retrieved` |
| `extraction_finished` | `extracted_rows`, `readonly_attribute` |
| `row_invalid` | `row_index`, source `field`, `reason` (first 100) |
| `request_prepared` | `batch_id`, `row_count`, `body_bytes`, `extracted_at` |
| `http_attempt`, `http_attempt_failed`, `http_retry_scheduled` | `attempt`, `http_status` or `failure`, `error_code`, delay |
| `submission_result` | `batch_id`, `status`, `replayed`, received/inserted/duplicate/rejected/superseded/restored row counts, `window_applied` |
| `row_rejected` | `row_index` and field-level reasons from the server |
| `phase_finished` | `phase` (`odbc_probe`, `extract`, `map`, `submit`), `elapsed_ms` |
| `run_error` | `reason`, `message`, safe details |
| `run_finished` | `status`, `exit_code`, `elapsed_ms` |

Never logged: the connector secret, the `Authorization` header, request
bodies, row values or measurements, Access database contents, server error
messages, and driver exception text (only SQLSTATE codes and exception type
names). As defence in depth the logger also redacts the secret, any
`Bearer ...` value, and fields named like `authorization`, `secret`,
`password`, `token`, `headers`, `body`, `payload`, or `rows`. Paths appear
only as configured metadata: the database **file name**, not its full path.

## 18. Troubleshooting

| Symptom | Likely cause and fix |
| ------- | -------------------- |
| Exit 2, `secret_not_found` | Secret not stored for *this* account, or wrong `CREDENTIAL_TARGET`. Repeat section 6 as the service account |
| Exit 2 in the task but not interactively | Task registered with "Do not store password", or under a different account |
| Exit 2, configuration message | Fix the named setting; the message never echoes values |
| Exit 3 | A run is in progress (or a manual run overlaps the schedule). A crashed run's lock is released by Windows automatically |
| Exit 4, `driver_not_found` | Driver not installed for this Python architecture; see section 3 |
| Exit 4, `architecture_mismatch` (SQLSTATE IM002/IM014) | Python and driver architectures differ |
| Exit 4, `database_not_found` | Wrong path, mapped drive letter instead of UNC, or no read/list permission |
| Exit 4, `connection_failed`, `attempt: access_mode_attribute` | The first open failed for a reason other than the read-only attribute (no retry). Check `sqlstate`: database locked exclusively by a user, corrupt, or unsupported format (`.accdb` with the legacy driver) |
| Exit 4, `connection_failed`, `attempt: connection_string_only` | The driver rejected the read-only attribute (`access_mode_sqlstate`, often `HY024`), and the single retry with only `ReadOnly=1` also failed with `sqlstate`. The attribute is not the cause. Test `DRIVER={...};DBQ=<UNC path>;ReadOnly=1;` directly with pyodbc as the service account, check share and folder permissions (including creating the `.laccdb` lock file, section 14), and check whether a user holds the file exclusively |
| `readonly_attribute: false` in `odbc_connection_opened` / `odbc_probe` | Expected with drivers that reject the ODBC access-mode attribute, for example `HY024` from the 32-bit Access driver. The connection is still opened with `ReadOnly=1` and only `SELECT` is executed. No action needed |
| Exit 4, `query_unavailable` / `missing_columns` | Query renamed, or columns changed |
| Exit 5, `empty_window` | Access returned no rows for the window. Check the source and the PC clock/date. Nothing was sent (section 22) |
| Exit 5, `local_validation_failed` | `row_invalid` events name the row index, field, and reason. Fix the source data |
| Exit 5, `window_too_large` | More rows than `BATCH_SIZE`; reduce `RECONCILIATION_DAYS` (section 21) |
| Exit 6 | 401: wrong or rotated secret, or wrong `CONNECTOR_ID`. 403: `SOURCE_SYSTEM` not allowed for this connector on the server |
| Exit 7, `stale_batch` | The server already applied an overlapping window extracted later, for example by another connector instance or a host with a wrong clock. Check for duplicate deployments and the system time |
| Exit 7, `batch_id_conflict` | Should not occur (batch IDs are unique per run). Report it |
| Exit 7, other | 400/413/415/422: request rejected; `invalid_fields` lists field names for 422 |
| Exit 8 | API unreachable, timeouts, TLS trust failure, or 429/502/503/504 after all attempts. The next scheduled run tries again |
| Exit 9 | The server rejected some rows (`row_rejected`); valid rows were stored but the window was not applied. Fix the source rows |
| Exit 10 | Inconsistent server response or internal error; the log shows the reason or exception type |

Windows Event Viewer: *Applications and Services Logs > Microsoft > Windows
> TaskScheduler > Operational* shows task starts, completions, and return
codes (enable task history in Task Scheduler if it is off).

## 19. Disabling the scheduled task

```powershell
Disable-ScheduledTask -TaskPath '\OperationsPlatform\' -TaskName 'Access finishing sync'
# Re-enable later:
Enable-ScheduledTask  -TaskPath '\OperationsPlatform\' -TaskName 'Access finishing sync'
```

Or in Task Scheduler right-click the task and choose **Disable**. A run that
is already in progress finishes (or is stopped by **End**). Disabling only
stops new submissions. Stored data remains unchanged and the dashboard
keeps serving it.

## 20. Rolling back the agent

1. Disable the task (section 19) and wait for any running instance to end.
2. Keep each release in its own folder (for example `app-0.1.0`). Point
   `app` back to the previous release, then recreate the virtual environment
   from **that** release's `uv.lock` (section 4).
3. Run `--check-config`, `--check-odbc`, and `--dry-run`, then re-enable the
   task.

The connector never deletes server data. Corrections it caused are stored
as superseded versions on the server, so a rollback loses no history. To
stop the integration completely, disable or delete the task, delete the
credential (`cmdkey /delete:operations-platform/lcy-access-sync` as the
service account), and ask the platform administrator to remove the
connector's digests from the server.

## 21. Changing RECONCILIATION_DAYS

`RECONCILIATION_DAYS` sets how far back each run re-reads and reconciles
Access. Choose a value that covers how late corrections can arrive (agree it
with the Quality owner), and keep the window's row count within `BATCH_SIZE`
(at most 5000).

1. Edit `RECONCILIATION_DAYS` in `connector.toml`.
2. Run `--dry-run` and check `extracted_rows` (and that there is no
   `window_too_large` error).
3. The next scheduled run uses the new window.

Effects:

- **Shorter:** rows older than the window are no longer reconciled. They
  keep their last stored version.
- **Longer:** older dates become authoritative again on the next run. Rows
  stored for those dates that no longer exist in Access are superseded on
  the server.

If a window cannot fit in one request, do not raise `BATCH_SIZE` above 5000
or split it. Reduce the window, or enhance the server contract with an
atomic multi-part protocol first.

## 22. Why an empty or incomplete window is never submitted

A reconciliation window tells the server: *this is the complete set of rows
for these dates*. The server supersedes every stored row in the range that
is missing from the request. Therefore:

- **Empty extraction:** sending it would declare that no rows exist and
  supersede everything in the range. A broken query, a wrong database file,
  or a date problem looks exactly like this. The connector logs
  `empty_window` with status `attention_required`, exits with code 5, and
  sends nothing.
- **Rows failing local validation:** dropping them and sending the rest
  would supersede their stored versions. The whole run stops (exit 5).
- **More rows than one request:** sending parts would let each part
  supersede the others. The run stops (exit 5).
- **Extraction failure part-way:** nothing is sent. The window is declared
  only after the complete extraction succeeded.

When the server itself rejects some rows (exit 9), it does not apply the
window. The valid rows are stored and nothing is superseded.

## Data handling

API field mapping:

| Access field | API field |
| ------------ | --------- |
| `DATE` | `sourceDate` |
| `CAMPNO` | `campaignNo` |
| `LOT` | `lot` |
| `Location` | `location` |
| `PRODUCT` | `product` |
| `AvgOfMOISTURE` | `avgMoisture` |
| `AvgOfCOLOR` | `avgColor` |
| `AvgOfCombined_BD` | `avgCombinedBd` |

- **Identifiers** (`CAMPNO`, `LOT`, `Location`, `PRODUCT`) are sent as
  strings exactly as returned. There is no trimming, case change,
  punctuation change, or location normalization. Leading zeroes in text
  fields are kept, and missing values stay `null` (never substituted or
  invented). If a column is numeric in Access, integral values are sent as
  their integer text (`26101`); non-integral numeric identifiers are rejected
  locally. Values longer than 200 characters (the API limit) are rejected.
- **Dates** returned as `date` or `datetime` become ISO calendar dates
  (`YYYY-MM-DD`). A time of day is dropped, and the number of affected rows is
  logged (`date_time_of_day_dropped`). Missing, text, time-zone-aware, or
  out-of-window dates are rejected locally.
- **Measurements** are sent as exact JSON numbers built from `Decimal`.
  `NULL` stays `null`, distinct from `0`. NaN and infinity are rejected
  locally. Values are never rounded, range-checked, or classified, and no
  thresholds or specifications are applied.
- **Float limitation.** The Access ODBC driver returns `Double` and `Single`
  columns as binary floating-point numbers, so their exact decimal form is
  not available to the connector. They are converted with
  `Decimal(str(value))`, which is the shortest text that round-trips
  (`0.43333333333333335`), and never with `Decimal(value)`, which would expose
  binary noise. `Single` columns can show single-precision artefacts (for
  example `0.4000000059604645`). `Decimal` and `Currency` columns arrive
  exactly.
- `sourceRecordId` is not sent: the aggregate query has no confirmed durable
  row identity.
- `extractedAt` is the UTC time the extraction started, with an explicit
  offset.

## Development

```powershell
cd connectors\access-finishing-sync
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

The tests need no Access installation, ODBC driver, Credential Manager
entry, or API: those are replaced by test doubles (`tests/support.py`).
Tests marked for Windows also read a non-existent Credential Manager target
and exercise the OS file lock across processes.

For a local end-to-end check against a development API on the same machine,
set `DEVELOPMENT_MODE=true`, `API_BASE_URL=http://127.0.0.1:8000`,
`SECRET_SOURCE=environment`, and `CONNECTOR_SECRET` in the current shell only.
Never use these settings on a production host.
