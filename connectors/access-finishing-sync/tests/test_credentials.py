import pickle
import sys
from pathlib import Path

import pytest
from support import SECRET, make_config

from access_finishing_sync.credentials import (
    CredentialError,
    EnvironmentCredentialProvider,
    Secret,
    WindowsCredentialManagerProvider,
    create_credential_provider,
    decode_credential_blob,
    read_generic_credential,
)
from access_finishing_sync.errors import ExitCode


def test_secret_is_hidden_from_repr_str_and_formatting() -> None:
    secret = Secret(SECRET)

    for text in (repr(secret), str(secret), f"{secret}", "%s" % (secret,), format(secret)):  # noqa: UP031
        assert SECRET not in text
    assert secret.reveal() == SECRET


def test_secret_cannot_be_pickled() -> None:
    with pytest.raises(TypeError):
        pickle.dumps(Secret(SECRET))


@pytest.mark.parametrize(
    "value", ["short", "has a space in it 12345", "x" * 257, "tab\tsecret12345678"]
)
def test_invalid_secret_is_rejected_without_echo(value: str) -> None:
    with pytest.raises(CredentialError) as caught:
        Secret(value)

    assert value not in str(caught.value)
    assert caught.value.exit_code == ExitCode.CONFIGURATION


def test_environment_provider_reads_the_variable() -> None:
    provider = EnvironmentCredentialProvider({"CONNECTOR_SECRET": SECRET})

    assert provider.get_secret().reveal() == SECRET
    assert SECRET not in provider.description


def test_environment_provider_reports_a_missing_secret() -> None:
    with pytest.raises(CredentialError, match="not set in CONNECTOR_SECRET"):
        EnvironmentCredentialProvider({}).get_secret()


def test_credential_manager_provider_decodes_cmdkey_blobs() -> None:
    targets: list[str] = []

    def reader(target: str) -> bytes:
        targets.append(target)
        return SECRET.encode("utf-16-le")

    provider = WindowsCredentialManagerProvider("operations-platform/lcy-access-sync", reader)

    assert provider.get_secret().reveal() == SECRET
    assert targets == ["operations-platform/lcy-access-sync"]


def test_credential_manager_provider_accepts_utf8_blobs() -> None:
    provider = WindowsCredentialManagerProvider("t", lambda _: (SECRET + "x").encode("utf-8"))

    assert provider.get_secret().reveal() == SECRET + "x"


def test_credential_manager_provider_reports_a_missing_credential() -> None:
    provider = WindowsCredentialManagerProvider(
        "operations-platform/lcy-access-sync", lambda _: None
    )

    with pytest.raises(CredentialError) as caught:
        provider.get_secret()

    assert caught.value.reason == "secret_not_found"
    assert "operations-platform/lcy-access-sync" in caught.value.message


def test_undecodable_blob_is_rejected() -> None:
    with pytest.raises(CredentialError, match="could not be decoded"):
        decode_credential_blob(b"\xff\xfe\x00")


def test_provider_follows_configuration(tmp_path: Path) -> None:
    production = make_config(tmp_path)
    development = make_config(tmp_path, SECRET_SOURCE="environment", DEVELOPMENT_MODE="true")

    assert isinstance(create_credential_provider(production), WindowsCredentialManagerProvider)
    provider = create_credential_provider(development, {"CONNECTOR_SECRET": SECRET})
    assert isinstance(provider, EnvironmentCredentialProvider)
    assert provider.get_secret().reveal() == SECRET


def test_custom_credential_target(tmp_path: Path) -> None:
    config = make_config(tmp_path, CREDENTIAL_TARGET="ops/finishing-sync")

    provider = create_credential_provider(config)

    assert provider.description.endswith("ops/finishing-sync")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Credential Manager")
def test_reading_a_nonexistent_windows_credential_returns_none() -> None:
    assert read_generic_credential("operations-platform/test-target-that-does-not-exist") is None


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows behaviour")
def test_credential_manager_is_unavailable_off_windows() -> None:
    with pytest.raises(CredentialError, match="only available on Windows"):
        read_generic_credential("anything")
