"""The test-database guards: the suite never migrates or wipes a protected database."""

import pytest
from postgres_support import (
    DISPOSABLE_PREFIX,
    UnsafeTestDatabaseError,
    check_disposable_database,
    check_shared_database,
)
from run_disposable_database import disposable_name


@pytest.mark.parametrize("name", ["operations_platform", "operations_platform_test"])
def test_disposable_mode_refuses_protected_databases(name: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError, match="protected"):
        check_disposable_database(name)


@pytest.mark.parametrize(
    "name",
    [
        None,
        "",
        "my_test",
        "operations_platform_test_copy",
        f"{DISPOSABLE_PREFIX}xyz",
        f"{DISPOSABLE_PREFIX}0123456789ab; DROP DATABASE x",
    ],
)
def test_disposable_mode_accepts_only_generated_names(name: str | None) -> None:
    with pytest.raises(UnsafeTestDatabaseError):
        check_disposable_database(name)


def test_generated_names_are_disposable_and_unique() -> None:
    first, second = disposable_name(), disposable_name()

    assert first.startswith(DISPOSABLE_PREFIX)
    assert check_disposable_database(first) == first
    assert first != second


def test_shared_mode_refuses_production() -> None:
    with pytest.raises(UnsafeTestDatabaseError):
        check_shared_database("operations_platform")


def test_shared_mode_accepts_only_the_shared_test_database() -> None:
    assert check_shared_database("operations_platform_test") == "operations_platform_test"
    with pytest.raises(UnsafeTestDatabaseError):
        check_shared_database(f"{DISPOSABLE_PREFIX}0123456789ab")
