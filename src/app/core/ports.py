"""Ports: interfaces the core needs from the outside world."""

from datetime import datetime
from typing import Protocol

from app.core.entities import HumanCheckResult


class DatabaseProbe(Protocol):
    """Checks that the database accepts queries."""

    def is_available(self) -> bool:
        """Return ``True`` when a trivial query succeeds."""
        ...


class Clock(Protocol):
    """Source of the current time."""

    def now(self) -> datetime:
        """Return the current moment as a timezone-aware datetime."""
        ...


class HumanCheckUnavailable(Exception):
    """The human check service cannot give a verdict (network, outage, misconfiguration)."""


class HumanCheck(Protocol):
    """Server-side check of the widget answer that a person fills in the form."""

    def verify(self, token: str) -> HumanCheckResult:
        """Check the widget token. Raises ``HumanCheckUnavailable`` when there is no verdict."""
        ...


class RateLimiter(Protocol):
    """Counts attempts per key within a time window."""

    def allow(self, key: str) -> bool:
        """Record an attempt for ``key``; ``False`` when the limit is already reached."""
        ...

    def refund(self, key: str) -> None:
        """Forget the latest recorded attempt for ``key``: it did not take effect."""
        ...
