"""Idempotency keys of the invitation that carry the moment they appeared (RFC 9562, UUIDv7).

Resend keeps a key for 24 hours from its first request and answers 409 to the same key with
another body. The letter's bot token must therefore follow the key, not the calendar: the token
issued since the key appeared is the one of its first attempt. The time comes from the
application's clock, so it compares with the tokens' ``created_at``; the schema needs no column.

>>> from datetime import UTC, datetime
>>> moment = datetime(2026, 10, 20, 16, 0, 0, 123456, tzinfo=UTC)
>>> key = new_key(moment)
>>> key.version, key.variant == uuid.RFC_4122
(7, True)
>>> key_time(key)
datetime.datetime(2026, 10, 20, 16, 0, 0, 123000, tzinfo=datetime.timezone.utc)
>>> new_key(moment) != key
True
>>> key_time(uuid.UUID("11111111-2222-4333-8444-555555555555")) is None  # uuid4: no time
True
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MILLISECOND = timedelta(milliseconds=1)
_RANDOM_BITS = 74  # 12 bits of rand_a and 62 bits of rand_b


def new_key(at: datetime) -> uuid.UUID:
    """A random UUIDv7 whose timestamp is ``at``, to the millisecond."""
    milliseconds = (at - _EPOCH) // _MILLISECOND
    random = secrets.randbits(_RANDOM_BITS)
    value = (
        (milliseconds & (2**48 - 1)) << 80
        | 0x7 << 76  # version
        | (random >> 62) << 64  # rand_a
        | 0b10 << 62  # variant
        | random & (2**62 - 1)  # rand_b
    )
    return uuid.UUID(int=value)


def key_time(key: uuid.UUID) -> datetime | None:
    """When the key appeared; ``None`` for a key without a time (written before UUIDv7)."""
    if key.version != 7:
        return None
    return _EPOCH + (key.int >> 80) * _MILLISECOND
