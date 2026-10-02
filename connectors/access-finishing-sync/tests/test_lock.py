import subprocess
import sys
from pathlib import Path

import pytest

from access_finishing_sync.errors import ExitCode, LockActiveError
from access_finishing_sync.lock import RunLock, lock_file_name


def test_lock_file_name_includes_connector_and_source() -> None:
    assert lock_file_name("lcy-access-sync", "access-qryFINISHING-AVG") == (
        "access-finishing-sync.lcy-access-sync.access-qryFINISHING-AVG.lock"
    )
    assert lock_file_name("a:b", "c/d") == "access-finishing-sync.a_b.c_d.lock"


def test_second_holder_is_refused(tmp_path: Path) -> None:
    first = RunLock(tmp_path, "lcy-access-sync", "access-qryFINISHING-AVG")
    second = RunLock(tmp_path, "lcy-access-sync", "access-qryFINISHING-AVG")

    with first:
        with pytest.raises(LockActiveError) as caught:
            second.acquire()
        assert caught.value.exit_code == ExitCode.LOCK_ACTIVE

    with second:  # released on normal exit
        pass


def test_different_configurations_do_not_block_each_other(tmp_path: Path) -> None:
    with (
        RunLock(tmp_path, "lcy-access-sync", "source-a"),
        RunLock(tmp_path, "lcy-access-sync", "source-b"),
    ):
        pass


def test_an_existing_lock_file_alone_does_not_block(tmp_path: Path) -> None:
    lock = RunLock(tmp_path, "c", "s")
    lock.path.write_text("connector=c source_system=s pid=999999\n")

    with lock:
        assert "connector=c source_system=s" in lock.path.read_text()


def test_lock_is_released_when_the_holding_process_dies(tmp_path: Path) -> None:
    script = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "from access_finishing_sync.lock import RunLock\n"
        "lock = RunLock(Path(sys.argv[1]), 'c', 's')\n"
        "lock.acquire()\n"
        "print('locked', flush=True)\n"
        "time.sleep(60)\n"
    )
    holder = subprocess.Popen(  # noqa: S603 - fixed interpreter and script
        [sys.executable, "-c", script, str(tmp_path)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(LockActiveError):
            RunLock(tmp_path, "c", "s").acquire()
    finally:
        holder.kill()  # simulated crash: no release() runs
        holder.wait(timeout=30)

    with RunLock(tmp_path, "c", "s"):
        pass
