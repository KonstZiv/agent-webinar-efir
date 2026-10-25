"""The permission to answer the quiz: a signed, expiring ticket for one address.

``<payload>.<sig>``: ``payload`` is unpadded base64url of ``<expires>:<address>`` (Unix seconds),
``sig`` the unpadded base64url HMAC-SHA256 over ``quiz:<payload>``. It is handed out only on the
success screen, in the form of the quiz, so only the browser that sees the screen holds it.
It is never logged.
"""

import base64
import hashlib
import hmac
from datetime import datetime, timedelta

TERM = timedelta(hours=2)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _signature(payload: str, secret: str) -> str:
    message = f"quiz:{payload}".encode("ascii")
    return _b64(hmac.new(secret.encode(), message, hashlib.sha256).digest())


def make_ticket(email: str, now: datetime, secret: str) -> str:
    """The ticket of ``email``, valid for ``TERM`` from ``now``.

    >>> from datetime import UTC
    >>> now = datetime(2026, 10, 25, tzinfo=UTC)
    >>> read_ticket(make_ticket("u@example.com", now, "k" * 32), now, "k" * 32)
    'u@example.com'
    """
    expires = int((now + TERM).timestamp())
    payload = _b64(f"{expires}:{email}".encode())
    return f"{payload}.{_signature(payload, secret)}"


def read_ticket(ticket: str, now: datetime, secret: str) -> str | None:
    """The address of a genuine, unexpired ticket; ``None`` for anything else.

    >>> from datetime import UTC
    >>> now = datetime(2026, 10, 25, tzinfo=UTC)
    >>> read_ticket("forged.forged", now, "k" * 32) is None
    True
    >>> old = make_ticket("u@example.com", now, "k" * 32)
    >>> read_ticket(old, now + TERM + timedelta(seconds=1), "k" * 32) is None
    True
    """
    payload, dot, signature = ticket.partition(".")
    if not dot or not payload.isascii() or not signature.isascii() or not hmac.compare_digest(
        signature, _signature(payload, secret)
    ):
        return None
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
        expires, _, email = raw.partition(":")
        if now.timestamp() > int(expires):
            return None
    except ValueError:
        return None
    return email or None
