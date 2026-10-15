"""Durable Safety import-run history (``safety.import_runs``).

``track`` records a run before the import touches anything (status
``running``, committed on its own) and its outcome afterwards, also when the
import raises. The run row never carries imported data: the import writes its
records to their permanent tables in its own transaction, and reports Applied
only after that transaction commits.
"""

import datetime as dt
import getpass
import hashlib
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_sessionmaker
from app.safety.imports.models import ImportRun

MAX_MESSAGES = 200
MAX_MESSAGE_LENGTH = 1000


def operator() -> str:
    """The operating-system account running a command-line import."""
    try:
        return f"operator:{getpass.getuser()}"
    except (OSError, KeyError):
        return "operator"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class RunResult:
    status: str
    inserted: int | None = None
    updated: int | None = None
    skipped: int | None = None
    conflicts: int | None = None
    failed: int | None = None
    messages: Sequence[str] = field(default_factory=tuple)
    change_set_id: uuid.UUID | None = None


class RunRecorder:
    def __init__(self, run_id: uuid.UUID) -> None:
        self.run_id = run_id
        self.result: RunResult | None = None

    def finish(
        self,
        status: str,
        *,
        inserted: int | None = None,
        updated: int | None = None,
        skipped: int | None = None,
        conflicts: int | None = None,
        failed: int | None = None,
        messages: Sequence[str] = (),
        change_set_id: uuid.UUID | None = None,
    ) -> None:
        self.result = RunResult(
            status, inserted, updated, skipped, conflicts, failed, messages, change_set_id
        )


def _messages(lines: Sequence[str]) -> list[str]:
    return [line[:MAX_MESSAGE_LENGTH] for line in lines[:MAX_MESSAGES]]


def _describe(error: BaseException) -> str:
    # Database errors can quote statement parameters; record only their kind.
    if isinstance(error, SQLAlchemyError):
        return f"{type(error).__name__}: database error"
    return f"{type(error).__name__}: {error}"


@contextmanager
def track(
    sessions: Callable[[], Session],
    *,
    importer: str,
    command: str,
    source_file_name: str,
    source_sha256: str,
    initiated_by: str,
    clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
) -> Iterator[RunRecorder]:
    """Record one import run. ``sessions`` opens a session independent of the
    import's own, so the run is kept when the import rolls back."""
    recorder = RunRecorder(uuid.uuid4())
    with sessions() as session:
        session.add(
            ImportRun(
                run_id=recorder.run_id,
                importer=importer,
                command=command,
                source_file_name=source_file_name,
                source_sha256=source_sha256,
                initiated_by=initiated_by,
                started_at=clock(),
                status="running",
            )
        )
        session.commit()
    try:
        yield recorder
    except BaseException as error:
        if recorder.result is None:
            recorder.result = RunResult("failed", messages=(_describe(error),))
        elif recorder.result.status == "applied":
            # The import committed before the error; the run stays applied.
            recorder.result.messages = (*recorder.result.messages, _describe(error))
        raise
    finally:
        result = recorder.result or RunResult(
            "failed", messages=("The import ended without recording a result.",)
        )
        with sessions() as session:
            session.execute(
                update(ImportRun)
                .where(ImportRun.run_id == recorder.run_id)
                .values(
                    status=result.status,
                    finished_at=clock(),
                    inserted_count=result.inserted,
                    updated_count=result.updated,
                    skipped_count=result.skipped,
                    conflict_count=result.conflicts,
                    failed_count=result.failed,
                    messages=_messages(list(result.messages)),
                    change_set_id=result.change_set_id,
                )
            )
            session.commit()


def track_command(importer: str, command: str, path: Path) -> AbstractContextManager[RunRecorder]:
    """``track`` for an operator command run against the configured database."""
    return track(
        get_sessionmaker(),
        importer=importer,
        command=command,
        source_file_name=path.name,
        source_sha256=file_sha256(path),
        initiated_by=operator(),
    )
