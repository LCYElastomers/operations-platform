"""Password hashing and random tokens.

Passwords are hashed with Argon2id (``argon2-cffi`` defaults, RFC 9106). Session
and password-link tokens are 256-bit random values; only their SHA-256 is
stored, so a database read does not yield a usable token. Nothing here logs or
returns a password, hash or token beyond handing a new token to its caller once.
"""

import hashlib
import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256

_hasher = PasswordHasher()


class WeakPasswordError(ValueError):
    pass


def check_password_policy(password: str, *, email: str) -> None:
    """Refuse passwords that are too short, too long or trivially guessable."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPasswordError(f"Use at most {MAX_PASSWORD_LENGTH} characters.")
    if len(set(password)) < 4:
        raise WeakPasswordError("Use a less repetitive password.")
    lowered = password.lower()
    local_part = email.split("@", 1)[0].lower()
    if lowered == email.lower() or (len(local_part) >= 4 and local_part in lowered):
        raise WeakPasswordError("Do not use your email address in your password.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


@lru_cache
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(16))


def verify_password(password_hash: str | None, password: str) -> bool:
    """True when ``password`` matches. With no hash (unknown user, no password
    set) a dummy hash is checked, so the response time does not reveal it."""
    try:
        return _hasher.verify(password_hash or _dummy_hash(), password) and bool(password_hash)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()
