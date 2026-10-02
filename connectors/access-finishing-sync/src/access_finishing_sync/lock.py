"""Single-instance run lock.

Uses an OS byte-range lock (LockFileEx via msvcrt on Windows, flock elsewhere)
on a lock file named after the connector and source system. The lock belongs
to the open file handle, so the operating system releases it when the process
exits or crashes; a leftover lock file never blocks a later run.
"""

import os
import re
import sys
from pathlib import Path
from types import TracebackType
from typing import IO

from access_finishing_sync.errors import ConfigError, LockActiveError

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def lock_file_name(connector_id: str, source_system: str) -> str:
    return (
        f"access-finishing-sync.{_UNSAFE.sub('_', connector_id)}."
        f"{_UNSAFE.sub('_', source_system)}.lock"
    )


class RunLock:
    def __init__(self, directory: Path, connector_id: str, source_system: str) -> None:
        self.path = directory / lock_file_name(connector_id, source_system)
        self._identity = f"connector={connector_id} source_system={source_system}"
        self._handle: IO[bytes] | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            raise RuntimeError("lock already held by this object")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(self.path, "a+b")  # noqa: SIM115 - held until release()
        except OSError as error:
            raise ConfigError(
                f"The lock file could not be opened ({type(error).__name__}); "
                "check LOCK_DIRECTORY permissions.",
                reason="lock_directory_unavailable",
            ) from None
        try:
            _lock(handle)
        except OSError:
            handle.close()
            raise LockActiveError(
                "Another run of this connector configuration is active.",
                reason="lock_active",
                lock_file=self.path.name,
            ) from None
        handle.seek(0)
        handle.truncate()
        handle.write(f"{self._identity} pid={os.getpid()}\n".encode())
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            _unlock(self._handle)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "RunLock":
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()


if sys.platform == "win32":
    import msvcrt

    # Windows byte-range locks are mandatory, so lock a byte far beyond the
    # identity text to keep the file readable while the lock is held.
    _LOCK_OFFSET = 1 << 30

    def _lock(handle: IO[bytes]) -> None:
        handle.seek(_LOCK_OFFSET)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(handle: IO[bytes]) -> None:
        handle.seek(_LOCK_OFFSET)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
