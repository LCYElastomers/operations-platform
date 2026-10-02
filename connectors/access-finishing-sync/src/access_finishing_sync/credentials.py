"""Connector secret retrieval.

Production reads a generic credential from Windows Credential Manager (per
Windows user profile). Development and tests may read an environment variable.
The secret is wrapped in `Secret` so it cannot leak through repr, str, or
string formatting, and no error message ever contains it.
"""

import os
import re
import sys
from collections.abc import Callable, Mapping
from typing import Protocol

from access_finishing_sync.config import Config
from access_finishing_sync.errors import ConfigError

SECRET_ENVIRONMENT_VARIABLE = "CONNECTOR_SECRET"  # noqa: S105 - a variable name
MAX_SECRET_LENGTH = 256  # the API's limit for presented secrets
MIN_SECRET_LENGTH = 16
_SECRET_PATTERN = re.compile(r"[\x21-\x7e]+")  # printable ASCII, no spaces: header safe


class CredentialError(ConfigError):
    def __init__(self, message: str, *, reason: str = "secret_unavailable") -> None:
        super().__init__(message, reason=reason)


class Secret:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not (MIN_SECRET_LENGTH <= len(value) <= MAX_SECRET_LENGTH) or not (
            _SECRET_PATTERN.fullmatch(value)
        ):
            raise CredentialError(
                "The stored connector secret has an invalid format "
                f"(expected {MIN_SECRET_LENGTH}-{MAX_SECRET_LENGTH} printable characters).",
                reason="secret_invalid",
            )
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret('**********')"

    __str__ = __repr__

    def __format__(self, format_spec: str) -> str:
        return repr(self)

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("Secret cannot be pickled")


class CredentialProvider(Protocol):
    description: str

    def get_secret(self) -> Secret: ...


class EnvironmentCredentialProvider:
    """For controlled development and testing only (requires DEVELOPMENT_MODE)."""

    def __init__(
        self, environ: Mapping[str, str], variable: str = SECRET_ENVIRONMENT_VARIABLE
    ) -> None:
        self._environ = environ
        self._variable = variable
        self.description = f"environment variable {variable}"

    def get_secret(self) -> Secret:
        value = self._environ.get(self._variable, "")
        if not value:
            raise CredentialError(f"The connector secret is not set in {self._variable}.")
        return Secret(value)


CredentialReader = Callable[[str], bytes | None]


class WindowsCredentialManagerProvider:
    def __init__(self, target: str, reader: CredentialReader | None = None) -> None:
        self._target = target
        self._reader = reader or read_generic_credential
        self.description = f"Windows Credential Manager target {target}"

    def get_secret(self) -> Secret:
        blob = self._reader(self._target)
        if not blob:
            raise CredentialError(
                f"No connector secret found in Windows Credential Manager for target "
                f"'{self._target}' under the current Windows account.",
                reason="secret_not_found",
            )
        return Secret(decode_credential_blob(blob))


def decode_credential_blob(blob: bytes) -> str:
    """cmdkey stores passwords as UTF-16-LE; other tools may store UTF-8."""
    candidates = []
    if len(blob) % 2 == 0:
        candidates.append("utf-16-le")
    candidates.append("utf-8")
    for encoding in candidates:
        try:
            text = blob.decode(encoding).rstrip("\x00")
        except UnicodeDecodeError:
            continue
        if text and _SECRET_PATTERN.fullmatch(text):
            return text
    raise CredentialError(
        "The stored connector secret could not be decoded.", reason="secret_invalid"
    )


def read_generic_credential(target: str) -> bytes | None:
    """Read a CRED_TYPE_GENERIC credential blob; None if it does not exist."""
    if sys.platform != "win32":
        raise CredentialError(
            "Windows Credential Manager is only available on Windows.",
            reason="credential_store_unavailable",
        )
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    cred_type_generic = 1
    error_not_found = 1168

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    cred_read = advapi32.CredReadW
    cred_read.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(CREDENTIALW)),
    ]
    cred_read.restype = wintypes.BOOL
    cred_free = advapi32.CredFree
    cred_free.argtypes = [ctypes.c_void_p]
    cred_free.restype = None

    credential = ctypes.POINTER(CREDENTIALW)()
    if not cred_read(target, cred_type_generic, 0, ctypes.byref(credential)):
        error = ctypes.get_last_error()
        if error == error_not_found:
            return None
        raise CredentialError(
            f"Windows Credential Manager could not be read (Windows error {error}).",
            reason="credential_store_error",
        )
    try:
        return ctypes.string_at(
            credential.contents.CredentialBlob, credential.contents.CredentialBlobSize
        )
    finally:
        cred_free(credential)


def create_credential_provider(
    config: Config, environ: Mapping[str, str] | None = None
) -> CredentialProvider:
    if config.secret_source == "environment":  # noqa: S105 - a mode name
        return EnvironmentCredentialProvider(os.environ if environ is None else environ)
    return WindowsCredentialManagerProvider(config.credential_target)
