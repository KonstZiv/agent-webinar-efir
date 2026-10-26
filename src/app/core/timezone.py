"""Kyiv time: event times are local ``Europe/Kyiv`` wall times, never a fixed UTC offset.

Daylight saving time ends on 25.10.2026, so the webinar (21.10) and the first lesson (28.10)
have different offsets; the zone, not a constant, gives the right one.

>>> from datetime import datetime
>>> kyiv_offset(datetime(2026, 10, 21, 19, 0)), kyiv_offset(datetime(2026, 10, 28, 19, 0))
('+03:00', '+02:00')
"""

from datetime import datetime
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")


def in_kyiv(local: datetime) -> datetime:
    """A naive Kyiv wall time as an aware datetime in ``Europe/Kyiv``."""
    return local.replace(tzinfo=KYIV)


def kyiv_offset(local: datetime) -> str:
    """UTC offset of a Kyiv wall time, as ``+HH:MM``."""
    return in_kyiv(local).isoformat(timespec="minutes")[-6:]
