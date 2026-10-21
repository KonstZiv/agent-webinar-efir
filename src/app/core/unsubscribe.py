"""Unsubscribe token shared with v1 (docs/contract.md, section 4).

``<id>.<sig>``: ``id`` is the participant's ``unsubscribe_id`` as 32 lower-case hex digits,
``sig`` is unpadded base64url of HMAC-SHA256 keyed with ``UNSUBSCRIBE_SECRET`` over
``unsubscribe:<id>``. The logic is v1's (``webinar.core.unsubscribe``), so a link from an old
email of v1 finds the same participant. The token carries no address, but it is a permission to
delete a participant: it is never logged. This module belongs to the slice «реєстрація і лист».
"""

import base64
import hashlib
import hmac
import re
import uuid

_TOKEN = re.compile(r"([0-9a-f]{32})\.([A-Za-z0-9_-]{43})", re.ASCII)
TOKEN_LENGTH = 76


def _signature(hex_id: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode(), f"unsubscribe:{hex_id}".encode("ascii"), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def make_token(unsubscribe_id: uuid.UUID, secret: str) -> str:
    """The unsubscribe token of a participant.

    >>> token = make_token(uuid.UUID(int=1), "secret-0123456789abcdef0123456789")
    >>> token.split(".")[0]
    '00000000000000000000000000000001'
    >>> len(token)
    76
    """
    hex_id = unsubscribe_id.hex
    return f"{hex_id}.{_signature(hex_id, secret)}"


def read_token(token: str, secret: str) -> uuid.UUID | None:
    """The ``unsubscribe_id`` of a genuine token; ``None`` for anything else.

    >>> secret = "secret-0123456789abcdef0123456789"
    >>> read_token(make_token(uuid.UUID(int=1), secret), secret)
    UUID('00000000-0000-0000-0000-000000000001')
    >>> read_token("00000000000000000000000000000001.forged", secret) is None
    True
    """
    if len(token) != TOKEN_LENGTH or not token.isascii():
        return None
    match = _TOKEN.fullmatch(token)
    if match is None:
        return None
    hex_id, signature = match.groups()
    if not hmac.compare_digest(signature, _signature(hex_id, secret)):
        return None
    return uuid.UUID(hex=hex_id)
