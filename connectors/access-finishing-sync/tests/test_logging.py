import json
import logging
from pathlib import Path

from support import SECRET, LogCapture

from access_finishing_sync.logs import (
    LOG_FILE_NAME,
    Redactor,
    RunLogger,
    configure_logging,
)


def test_events_are_json_lines_with_run_context() -> None:
    capture = LogCapture()

    capture.log.info("extraction_finished", extracted_rows=3)

    (event,) = capture.events
    assert event["event"] == "extraction_finished"
    assert event["run_id"] == "test-run"
    assert event["extracted_rows"] == 3
    assert event["level"] == "INFO"


def test_registered_secret_is_redacted_everywhere() -> None:
    capture = LogCapture()
    capture.redactor.add(SECRET)

    capture.log.error("run_error", message=f"failed with {SECRET}", detail={"nested": SECRET})

    assert SECRET not in capture.text
    assert capture.text.count("[REDACTED]") == 2


def test_bearer_values_and_generated_tokens_are_redacted() -> None:
    capture = LogCapture()

    capture.log.warning("x", note="Authorization: Bearer abc.def-123", other="opc_AbCdEf123456789")

    assert "abc.def-123" not in capture.text
    assert "opc_AbCdEf123456789" not in capture.text


def test_sensitive_field_names_are_redacted() -> None:
    capture = LogCapture()

    capture.log.info(
        "x",
        Authorization="Bearer zzz",
        headers={"a": "b"},
        body='{"rows": []}',
        rows=[1],
        secret="s3",
        password="p4",
    )

    (event,) = capture.events
    for key in ("Authorization", "headers", "body", "rows", "secret", "password"):
        assert event[key] == "[REDACTED]"


def test_exception_text_is_not_logged_only_its_type() -> None:
    capture = LogCapture()
    try:
        raise ValueError("row value LOT-123 and C:\\private\\path")
    except ValueError:
        capture.logger.exception("failure", extra={"fields": {}})

    (event,) = capture.events
    assert event["exception_type"] == "ValueError"
    assert "LOT-123" not in capture.text
    assert "private" not in capture.text


def test_log_file_rotates(tmp_path: Path) -> None:
    logger = configure_logging(
        Redactor(), log_directory=tmp_path, max_bytes=64 * 1024, backup_count=2
    )
    log = RunLogger(logger, run_id="r")
    for i in range(1200):
        log.info("filler", index=i, padding="x" * 100)
    for handler in logger.handlers:
        handler.close()

    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == [LOG_FILE_NAME, f"{LOG_FILE_NAME}.1", f"{LOG_FILE_NAME}.2"]
    assert all((tmp_path / name).stat().st_size <= 64 * 1024 + 512 for name in files)
    first = (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8").splitlines()[0]
    assert json.loads(first)["event"] == "filler"


def test_http_library_logging_is_quiet() -> None:
    LogCapture()

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
