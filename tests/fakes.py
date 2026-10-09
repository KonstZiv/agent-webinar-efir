"""Fake port implementations for tests."""

from datetime import datetime, timedelta


class FakeDatabaseProbe:
    """Database probe with a fixed answer."""

    def __init__(self, available: bool = True) -> None:
        self.available = available

    def is_available(self) -> bool:
        return self.available


class FixedClock:
    """Clock that stands still until a test moves it forward."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta
