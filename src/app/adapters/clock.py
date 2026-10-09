"""System clock adapter for the ``Clock`` port."""

from datetime import UTC, datetime


class SystemClock:
    """Current time in UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)
