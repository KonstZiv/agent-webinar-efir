"""Email addresses: normalisation, format, the allowlist of the staging site (requirements, 5).

Only ASCII addresses are accepted, as in v1: then lower case in Python matches ``lower()`` in the
database check on ``participants.email``. No DNS lookups.
"""

import re
from collections.abc import Collection

MAX_LENGTH = 254
MAX_LOCAL_LENGTH = 64
MAX_LABEL_LENGTH = 63

_ATOM = r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+"
_LOCAL = re.compile(rf"{_ATOM}(?:\.{_ATOM})*", re.IGNORECASE | re.ASCII)
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", re.IGNORECASE | re.ASCII)


def normalize_email(value: str) -> str:
    """Strip surrounding whitespace and lower the case.

    >>> normalize_email("  Name@Example.COM ")
    'name@example.com'
    """
    return value.strip().lower()


def is_valid_email(value: str) -> bool:
    """Whether ``value`` looks like a deliverable ASCII address (dot-atom local part, DNS name).

    >>> is_valid_email("name.surname+tag@example.com")
    True
    >>> is_valid_email("name@example")
    False
    >>> is_valid_email("ім'я@example.com")
    False
    """
    if not value.isascii() or len(value) > MAX_LENGTH:
        return False
    local, at, domain = value.rpartition("@")
    if not at or len(local) > MAX_LOCAL_LENGTH or not _LOCAL.fullmatch(local):
        return False
    labels = domain.split(".")
    return (
        len(labels) >= 2
        and all(len(label) <= MAX_LABEL_LENGTH and _LABEL.fullmatch(label) for label in labels)
        and not labels[-1].isdigit()
    )


def is_allowed(email: str, allowlist: Collection[str]) -> bool:
    """Whether the address may register and get email: ``REGISTRATION_ALLOWLIST``.

    An empty list allows everyone (production). An entry ``name@domain`` allows itself and every
    ``name+anything@domain``; entries are normalised and have no ``+`` (``Settings``).

    >>> allowlist = ("tester@example.com",)
    >>> [is_allowed(a, allowlist) for a in ("Tester@example.com", "tester+1@example.com")]
    [True, True]
    >>> [is_allowed(a, allowlist) for a in ("other@example.com", "tester@example.org")]
    [False, False]
    >>> is_allowed("anyone@example.com", ())
    True
    """
    if not allowlist:
        return True
    local, _, domain = normalize_email(email).rpartition("@")
    return f"{local.split('+', 1)[0]}@{domain}" in allowlist
