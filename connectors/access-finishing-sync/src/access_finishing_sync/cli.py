"""Command line: exactly one of --check-config, --check-odbc, --dry-run,
--run-once, plus an optional --config file path.

The connector secret is never accepted as an argument (it would be visible in
process listings and Task Scheduler); see credentials.py.
"""

import argparse
import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NoReturn

from access_finishing_sync import __version__
from access_finishing_sync.config import CONFIG_FILE_VARIABLE, Config, load_config
from access_finishing_sync.credentials import create_credential_provider
from access_finishing_sync.errors import ConfigError, ExitCode
from access_finishing_sync.lock import RunLock
from access_finishing_sync.logs import Redactor, RunLogger, configure_logging
from access_finishing_sync.odbc import AccessRepository
from access_finishing_sync.service import Action, SyncService
from access_finishing_sync.transport import HttpxTransport

ServiceFactory = Callable[[Config, RunLogger, Redactor, Mapping[str, str]], SyncService]

ACTIONS: dict[str, Action] = {
    "check_config": "check-config",
    "check_odbc": "check-odbc",
    "dry_run": "dry-run",
    "run_once": "run-once",
}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse would echo unknown arguments, which could be a pasted secret.
        if message.startswith("unrecognized arguments"):
            message = "unrecognized arguments (not shown)"
        super().error(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="access-finishing-sync",
        description="Sync qryFINISHING-AVG from Microsoft Access to the Operations Platform.",
        allow_abbrev=False,
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--check-config", action="store_true", help="validate configuration")
    actions.add_argument("--check-odbc", action="store_true", help="check Access ODBC access")
    actions.add_argument("--dry-run", action="store_true", help="extract and validate only")
    actions.add_argument("--run-once", action="store_true", help="extract and submit once")
    parser.add_argument(
        "--config",
        type=Path,
        help=f"configuration file (TOML); default: ${CONFIG_FILE_VARIABLE} if set",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def default_service(
    config: Config, log: RunLogger, redactor: Redactor, environ: Mapping[str, str]
) -> SyncService:
    return SyncService(
        config,
        log=log,
        redactor=redactor,
        credential_provider_factory=lambda: create_credential_provider(config, environ),
        repository_factory=lambda: AccessRepository(
            config.access_odbc_driver,
            config.access_database_path,
            config.access_query_name,
            log=log,
        ),
        transport_factory=lambda: HttpxTransport(
            config.http_connect_timeout_seconds, config.http_read_timeout_seconds
        ),
        lock_factory=lambda: RunLock(
            config.lock_directory, config.connector_id, config.source_system
        ),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    service_factory: ServiceFactory = default_service,
) -> int:
    args = build_parser().parse_args(argv)
    action = next(ACTIONS[name] for name in ACTIONS if getattr(args, name))
    environ = os.environ if environ is None else environ
    run_id = uuid.uuid4().hex
    redactor = Redactor()
    logger = configure_logging(redactor)
    bootstrap = RunLogger(logger, run_id=run_id, action=action)

    config_file = args.config or (
        Path(environ[CONFIG_FILE_VARIABLE]) if environ.get(CONFIG_FILE_VARIABLE) else None
    )
    try:
        config = load_config(environ, config_file)
        # check-config touches nothing beyond configuration and the credential store.
        logger = configure_logging(
            redactor,
            log_directory=None if action == "check-config" else config.log_directory,
            max_bytes=config.log_max_bytes,
            backup_count=config.log_backup_count,
        )
    except ConfigError as error:
        bootstrap.error("run_error", reason=error.reason, message=error.message, **error.fields)
        bootstrap.info("run_finished", status="failed", exit_code=int(error.exit_code))
        _summary(action, error.exit_code)
        return error.exit_code
    except OSError as error:
        bootstrap.error(
            "run_error",
            reason="log_directory_unavailable",
            message=f"LOG_DIRECTORY could not be used ({type(error).__name__}).",
        )
        _summary(action, ExitCode.CONFIGURATION)
        return ExitCode.CONFIGURATION

    log = RunLogger(
        logger,
        run_id=run_id,
        connector_id=config.connector_id,
        source_system=config.source_system,
    )
    try:
        code = service_factory(config, log, redactor, environ).execute(action)
    except Exception as error:  # noqa: BLE001 - last-resort mapping to exit code 10
        # Only the type: exception text from drivers or libraries may contain values.
        log.error("run_error", reason="internal_error", error_type=type(error).__name__)
        log.info("run_finished", action=action, status="failed", exit_code=ExitCode.INTERNAL)
        code = ExitCode.INTERNAL
    _summary(action, code)
    return int(code)


def _summary(action: str, code: ExitCode) -> None:
    print(f"{action}: {ExitCode(code).name.lower()} (exit code {int(code)})")


if __name__ == "__main__":
    raise SystemExit(main())
