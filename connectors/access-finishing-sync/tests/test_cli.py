from pathlib import Path
from typing import Any

import pytest
from support import SECRET, base_env

from access_finishing_sync.cli import build_parser, main
from access_finishing_sync.errors import ExitCode


def test_exit_codes_are_stable() -> None:
    assert {code.name: int(code) for code in ExitCode} == {
        "SUCCESS": 0,
        "CONFIGURATION": 2,
        "LOCK_ACTIVE": 3,
        "ODBC_UNAVAILABLE": 4,
        "EXTRACTION": 5,
        "AUTHENTICATION": 6,
        "API_REJECTED": 7,
        "TRANSIENT": 8,
        "PARTIAL_ACCEPTANCE": 9,
        "INTERNAL": 10,
    }


def test_exactly_four_operating_actions() -> None:
    options = {
        option
        for action in build_parser()._actions
        for option in action.option_strings
        if option not in {"-h", "--help", "--version", "--config"}
    }

    assert options == {"--check-config", "--check-odbc", "--dry-run", "--run-once"}


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--run-once", "--dry-run"],
        ["--run"],  # abbreviations are not accepted
        ["--run-once", "--secret", "x"],
        ["--run-once", "--connector-secret=x"],
    ],
)
def test_invalid_command_lines_are_refused(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        build_parser().parse_args(argv)

    assert caught.value.code == 2


def test_a_secret_passed_as_an_argument_is_refused_and_not_echoed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    for argv in (["--run-once", "--secret", SECRET], ["--run-once", SECRET]):
        with pytest.raises(SystemExit) as caught:
            main(argv, environ={})

        assert caught.value.code == 2
        _, err = capsys.readouterr()
        assert "unrecognized arguments (not shown)" in err
        assert SECRET not in err


def test_no_option_accepts_a_secret() -> None:
    options = " ".join(o for a in build_parser()._actions for o in a.option_strings)

    assert "secret" not in options.lower()
    assert "token" not in options.lower()
    assert "password" not in options.lower()


def development_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    return base_env(
        tmp_path,
        DEVELOPMENT_MODE="true",
        SECRET_SOURCE="environment",
        CONNECTOR_SECRET=SECRET,
        **overrides,
    )


def test_check_config_with_a_test_credential_provider(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--check-config"], environ=development_env(tmp_path))

    out, err = capsys.readouterr()
    assert code == 0
    assert "check-config: success (exit code 0)" in out
    assert '"event": "configuration_valid"' in err
    assert SECRET not in out + err
    # No log file, lock file, Access query, or HTTP request.
    assert not (tmp_path / "logs").exists()
    assert not (tmp_path / "locks").exists()


def test_check_config_fails_without_the_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = development_env(tmp_path)
    del env["CONNECTOR_SECRET"]

    assert main(["--check-config"], environ=env) == ExitCode.CONFIGURATION


def test_check_config_reads_the_config_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file = tmp_path / "connector.toml"
    lines = [f"{key} = '{value}'" for key, value in development_env(tmp_path).items()]
    config_file.write_text(
        "\n".join(line for line in lines if not line.startswith("CONNECTOR_SECRET")),
        encoding="utf-8",
    )

    code = main(
        ["--check-config", "--config", str(config_file)], environ={"CONNECTOR_SECRET": SECRET}
    )

    assert code == 0


def test_invalid_configuration_exits_2_without_echoing_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = development_env(tmp_path, BATCH_SIZE="9999")

    code = main(["--run-once"], environ=env)

    _, err = capsys.readouterr()
    assert code == ExitCode.CONFIGURATION
    assert "BATCH_SIZE must be an integer between 1 and 5000" in err
    assert SECRET not in err


class StubService:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.actions: list[str] = []

    def execute(self, action: str) -> Any:
        self.actions.append(action)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.parametrize(
    ("argv", "action"),
    [
        (["--check-config"], "check-config"),
        (["--check-odbc"], "check-odbc"),
        (["--dry-run"], "dry-run"),
        (["--run-once"], "run-once"),
    ],
)
def test_actions_are_dispatched(tmp_path: Path, argv: list[str], action: str) -> None:
    service = StubService(ExitCode.SUCCESS)

    code = main(argv, environ=development_env(tmp_path), service_factory=lambda *_: service)

    assert code == 0
    assert service.actions == [action]


@pytest.mark.parametrize("code", list(ExitCode))
def test_service_exit_codes_become_process_exit_codes(tmp_path: Path, code: ExitCode) -> None:
    result = main(
        ["--run-once"],
        environ=development_env(tmp_path),
        service_factory=lambda *_: StubService(code),
    )

    assert result == int(code)


def test_unexpected_errors_exit_10_without_their_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    service = StubService(RuntimeError("row LOT-VALUE-9 leaked"))

    code = main(
        ["--run-once"], environ=development_env(tmp_path), service_factory=lambda *_: service
    )

    _, err = capsys.readouterr()
    assert code == ExitCode.INTERNAL
    assert '"error_type": "RuntimeError"' in err
    assert "LOT-VALUE-9" not in err
    assert (tmp_path / "logs" / "access-finishing-sync.log").exists()
