import sys
from pathlib import Path

import pytest
from support import base_env, make_config

from access_finishing_sync.config import KNOWN_KEYS, Config, load_config, read_config_file
from access_finishing_sync.errors import ConfigError, ExitCode


def test_defaults(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    assert config.connector_id == "lcy-access-sync"
    assert config.access_query_name == "qryFINISHING-AVG"
    assert config.source_system == "access-qryFINISHING-AVG"
    assert config.reconciliation_days == 60
    assert config.batch_size == 5000
    assert config.secret_source == "credential-manager"
    assert config.credential_target == "operations-platform/lcy-access-sync"
    assert config.development_mode is False
    assert config.ingestion_url == (
        "https://ops.example.test/api/v1/ingestion/quality/finishing/batches"
    )


def test_required_settings_are_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as caught:
        load_config({})

    for key in (
        "API_BASE_URL",
        "ACCESS_DATABASE_PATH",
        "ACCESS_ODBC_DRIVER",
        "LOG_DIRECTORY",
        "LOCK_DIRECTORY",
    ):
        assert key in caught.value.message
    assert caught.value.exit_code == ExitCode.CONFIGURATION


@pytest.mark.parametrize("value", ["0", "5001", "-1", "abc", "1.5", ""])
def test_batch_size_must_be_between_1_and_5000(tmp_path: Path, value: str) -> None:
    env = base_env(tmp_path, BATCH_SIZE=value)
    if value == "":
        assert load_config(env).batch_size == 5000  # blank falls back to the default
        return
    with pytest.raises(ConfigError, match="BATCH_SIZE must be an integer between 1 and 5000"):
        load_config(env)


@pytest.mark.parametrize("value", ["1", "5000"])
def test_batch_size_boundaries_are_accepted(tmp_path: Path, value: str) -> None:
    assert make_config(tmp_path, BATCH_SIZE=value).batch_size == int(value)


@pytest.mark.parametrize("value", ["0", "3661", "x"])
def test_reconciliation_days_is_validated(tmp_path: Path, value: str) -> None:
    with pytest.raises(ConfigError, match="RECONCILIATION_DAYS"):
        make_config(tmp_path, RECONCILIATION_DAYS=value)


@pytest.mark.parametrize("key", ["HTTP_CONNECT_TIMEOUT_SECONDS", "HTTP_READ_TIMEOUT_SECONDS"])
@pytest.mark.parametrize("value", ["0", "-5", "abc", "100000"])
def test_timeouts_are_validated(tmp_path: Path, key: str, value: str) -> None:
    with pytest.raises(ConfigError, match=key):
        make_config(tmp_path, **{key: value})


def test_timeouts_are_separate(tmp_path: Path) -> None:
    config = make_config(
        tmp_path, HTTP_CONNECT_TIMEOUT_SECONDS="5", HTTP_READ_TIMEOUT_SECONDS="90.5"
    )

    assert (config.http_connect_timeout_seconds, config.http_read_timeout_seconds) == (5.0, 90.5)


@pytest.mark.parametrize(
    "url",
    [
        "http://ops.example.test",
        "http://localhost:8000",  # localhost still needs DEVELOPMENT_MODE
        "ftp://ops.example.test",
        "ops.example.test",
    ],
)
def test_production_requires_https(tmp_path: Path, url: str) -> None:
    with pytest.raises(ConfigError, match="must use https"):
        make_config(tmp_path, API_BASE_URL=url)


@pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1:8000/"])
def test_development_mode_allows_http_to_localhost(tmp_path: Path, url: str) -> None:
    config = make_config(tmp_path, API_BASE_URL=url, DEVELOPMENT_MODE="true")

    assert config.ingestion_url.startswith(url.rstrip("/") + "/api/v1/")


@pytest.mark.parametrize("url", ["http://ops.example.test", "http://10.0.0.5", "http://[::1]"])
def test_development_mode_does_not_allow_http_to_other_hosts(tmp_path: Path, url: str) -> None:
    with pytest.raises(ConfigError, match="must use https"):
        make_config(tmp_path, API_BASE_URL=url, DEVELOPMENT_MODE="true")


def test_url_credentials_are_rejected_without_echo(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as caught:
        make_config(tmp_path, API_BASE_URL="https://user:hunter2-pass@ops.example.test")

    assert "must not contain user names or passwords" in caught.value.message
    assert "hunter2-pass" not in str(caught.value)


def test_url_query_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="query string"):
        make_config(tmp_path, API_BASE_URL="https://ops.example.test/?token=x")


def test_https_base_path_is_kept(tmp_path: Path) -> None:
    config = make_config(tmp_path, API_BASE_URL="https://ops.example.test/platform/")

    assert config.ingestion_url == (
        "https://ops.example.test/platform/api/v1/ingestion/quality/finishing/batches"
    )


def test_environment_secret_source_requires_development_mode(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="requires DEVELOPMENT_MODE=true"):
        make_config(tmp_path, SECRET_SOURCE="environment")

    config = make_config(tmp_path, SECRET_SOURCE="environment", DEVELOPMENT_MODE="true")
    assert config.secret_source == "environment"


def test_unknown_secret_source_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="SECRET_SOURCE"):
        make_config(tmp_path, SECRET_SOURCE="file")


@pytest.mark.parametrize("key", ["ACCESS_DATABASE_PATH", "LOG_DIRECTORY", "LOCK_DIRECTORY"])
def test_paths_must_be_absolute(tmp_path: Path, key: str) -> None:
    relative = "relative/Finishing.accdb" if key == "ACCESS_DATABASE_PATH" else "relative"
    with pytest.raises(ConfigError, match=f"{key} must be an absolute path"):
        make_config(tmp_path, **{key: relative})


@pytest.mark.parametrize("name", ["Finishing.accdb", "Legacy.MDB"])
def test_accdb_and_mdb_are_accepted(tmp_path: Path, name: str) -> None:
    config = make_config(tmp_path, ACCESS_DATABASE_PATH=str(tmp_path / name))

    assert config.access_database_path.name == name


def test_other_database_types_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"\.accdb or \.mdb"):
        make_config(tmp_path, ACCESS_DATABASE_PATH=str(tmp_path / "Finishing.xlsx"))


@pytest.mark.parametrize("name", ["qry]X", "qry[X", "a`b"])
def test_query_name_cannot_break_out_of_brackets(tmp_path: Path, name: str) -> None:
    with pytest.raises(ConfigError, match="ACCESS_QUERY_NAME"):
        make_config(tmp_path, ACCESS_QUERY_NAME=name)


def test_driver_name_cannot_inject_connection_attributes(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="ACCESS_ODBC_DRIVER"):
        make_config(tmp_path, ACCESS_ODBC_DRIVER="x};DBQ=other.accdb;{")


@pytest.mark.parametrize("key", ["CONNECTOR_ID", "SOURCE_SYSTEM"])
def test_identities_follow_the_api_name_rule(tmp_path: Path, key: str) -> None:
    with pytest.raises(ConfigError, match=key):
        make_config(tmp_path, **{key: "has space"})


def test_identities_must_leave_room_for_the_batch_id(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="batch IDs fit"):
        make_config(tmp_path, CONNECTOR_ID="c" * 30, SOURCE_SYSTEM="s" * 30)


def test_config_file_is_loaded_and_environment_overrides_it(tmp_path: Path) -> None:
    file = tmp_path / "connector.toml"
    file.write_text(
        "\n".join(
            [
                'API_BASE_URL = "https://file.example.test"',
                f"ACCESS_DATABASE_PATH = '{tmp_path / 'Finishing.accdb'}'",
                f'ACCESS_ODBC_DRIVER = "{"Microsoft Access Driver (*.mdb, *.accdb)"}"',
                f"LOG_DIRECTORY = '{tmp_path / 'logs'}'",
                f"LOCK_DIRECTORY = '{tmp_path / 'locks'}'",
                "RECONCILIATION_DAYS = 30",
                "DEVELOPMENT_MODE = false",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config({"RECONCILIATION_DAYS": "14", "UNRELATED": "x"}, file)

    assert config.api_base_url == "https://file.example.test"
    assert config.reconciliation_days == 14


@pytest.mark.parametrize("key", ["CONNECTOR_SECRET", "API_TOKEN", "password"])
def test_config_file_must_not_hold_secrets(tmp_path: Path, key: str) -> None:
    file = tmp_path / "connector.toml"
    file.write_text(f'{key} = "do-not-store-me"\n', encoding="utf-8")

    with pytest.raises(ConfigError) as caught:
        load_config({}, file)

    assert "secrets must not be stored in the configuration file" in caught.value.message
    assert "do-not-store-me" not in str(caught.value)


def test_config_file_rejects_unknown_settings(tmp_path: Path) -> None:
    file = tmp_path / "connector.toml"
    file.write_text('VERIFY_TLS = "false"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="VERIFY_TLS: unknown setting"):
        load_config({}, file)


def test_missing_config_file_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config({}, tmp_path / "missing.toml")


def test_secret_in_environment_is_not_part_of_the_configuration(tmp_path: Path) -> None:
    config = load_config(base_env(tmp_path, CONNECTOR_SECRET="EnvSecretValue-123456789"))

    assert "EnvSecretValue" not in repr(config)


EXAMPLE = Path(__file__).resolve().parents[1] / "connector.example.toml"


def test_example_config_holds_only_known_non_secret_settings() -> None:
    values = read_config_file(EXAMPLE)

    assert set(values) <= KNOWN_KEYS
    assert values["SECRET_SOURCE"] == "credential-manager"
    assert values["DEVELOPMENT_MODE"] == "false"


@pytest.mark.skipif(sys.platform != "win32", reason="example uses Windows paths")
def test_example_config_is_valid() -> None:
    config = load_config({}, EXAMPLE)

    assert config.api_base_url.startswith("https://")
    assert config.access_database_path.name == "Finishing.accdb"


def test_there_is_no_setting_to_disable_tls_verification() -> None:
    names = " ".join(Config.__dataclass_fields__).lower()

    for word in ("verify", "insecure", "tls", "ssl", "cert"):
        assert word not in names
