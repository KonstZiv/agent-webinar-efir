"""Addresses typed into the check-in form: normalised as the registration stores them.

Stored addresses are lower case without surrounding whitespace and ASCII only
(docs/requirements.md, section 5). The form needs only to tell an obvious slip from an address;
whether the address is registered the participants' store answers.
"""

import re

MAX_LENGTH = 254

_ADDRESS = re.compile(
    r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]{1,64}@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+",
    re.ASCII,
)


def normalize_email(value: str) -> str:
    """Strip surrounding whitespace and lower the case.

    >>> normalize_email("  Name@Example.COM ")
    'name@example.com'
    """
    return value.strip().lower()


def looks_like_email(value: str) -> bool:
    """Whether a normalised value is shaped like ``name@domain.tld``.

    >>> looks_like_email("name@example.com"), looks_like_email("name@example")
    (True, False)
    >>> looks_like_email("ім'я@example.com"), looks_like_email("a b@example.com")
    (False, False)
    """
    return (
        value.isascii()
        and len(value) <= MAX_LENGTH
        and ".." not in value
        and _ADDRESS.fullmatch(value) is not None
    )
