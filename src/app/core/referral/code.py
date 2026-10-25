"""The code of a personal link: eight characters of a URL-safe alphabet, never guessable in order.

>>> is_valid_code(new_code())
True
>>> is_valid_code("a b")
False
"""

import re
import secrets
import string

CODE_LENGTH = 8
ALPHABET = string.ascii_letters + string.digits + "-_"
# ``participants.ref_code`` is ``varchar(16)``.
_CODE = re.compile(r"[A-Za-z0-9_-]{1,16}", re.ASCII)


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def is_valid_code(value: str | None) -> bool:
    """Whether ``value`` has the form of a code; it says nothing about who owns it."""
    return value is not None and _CODE.fullmatch(value) is not None
