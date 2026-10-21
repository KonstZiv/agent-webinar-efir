"""Addresses (requirements, section 5): normalised, checked as v1 checks them, the allowlist."""

import pytest

from app.core.registration.addresses import is_allowed, is_valid_email, normalize_email

ALLOWLIST = ("tester@example.com", "kos@team.example.com")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  Ivan@Example.COM ", "ivan@example.com"),
        ("ivan@example.com", "ivan@example.com"),
        ("", ""),
    ],
)
def test_addresses_are_trimmed_and_lowered(value: str, expected: str) -> None:
    assert normalize_email(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "name@example.com",
        "name.surname+tag@example.com",
        "a!#$%&'*+/=?^_`{|}~-@example.com",
        "name@sub-domain.example.com",
        f"{'a' * 64}@example.com",
    ],
)
def test_valid_addresses(value: str) -> None:
    assert is_valid_email(value)


@pytest.mark.parametrize(
    "value",
    [
        "name@example",
        "name@",
        "@example.com",
        "name",
        "name..dot@example.com",
        ".name@example.com",
        "name.@example.com",
        "ім'я@example.com",
        "name@приклад.example.com",
        "name@-sub.example.com",
        "name@sub-.example.com",
        "name@example.123",
        "na me@example.com",
        f"{'a' * 65}@example.com",
        f"name@{'a' * 64}.com",
        f"{'a' * 64}@{'b' * 63}.{'c' * 63}.{'d' * 63}.com",  # longer than 254 characters
        f"{'a' * 64}@{'b' * 63}.{'c' * 63}.{'d' * 50}.example.com",  # 255 characters
    ],
)
def test_invalid_addresses(value: str) -> None:
    assert not is_valid_email(value)


def test_maximum_length_is_254() -> None:
    """The limit of v1 and of ``varchar(254)`` in the shared database; 255 is refused above."""
    address = f"{'a' * 64}@{'b' * 63}.{'c' * 63}.{'d' * 49}.example.com"

    assert len(address) == 254
    assert is_valid_email(address)


@pytest.mark.parametrize(
    "value",
    [
        "tester@example.com",
        "Tester@Example.com",
        "tester+rehearsal@example.com",
        "tester+a+b@example.com",
        "kos+1@team.example.com",
    ],
)
def test_entries_and_their_plus_variants_are_allowed(value: str) -> None:
    assert is_allowed(value, ALLOWLIST)


@pytest.mark.parametrize(
    "value",
    [
        "stranger@example.com",
        "tester@team.example.com",
        "tester.x@example.com",
        "x+tester@example.com",
        "+tester@example.com",
        "tester@example.com.evil.example.com",
    ],
)
def test_other_addresses_are_not(value: str) -> None:
    assert not is_allowed(value, ALLOWLIST)


def test_an_empty_list_allows_everyone() -> None:
    assert is_allowed("anyone@example.com", ())
