"""The store of the attendance; every method raises ``StorageError`` (``app.core.ports``)."""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol

from app.core.checkin.model import Checkin, Listed, Report


class CheckinStore(Protocol):
    """Check-ins, marks and groups in the database; data operations only."""

    def add(
        self,
        code: str,
        lesson_date: date,
        group: str | None,
        opened_at: datetime,
        closes_at: datetime,
    ) -> Checkin | None:
        """Store a check-in unless an open one (``closes_at > opened_at``) already has ``code``.

        Return ``None`` for a taken code. The check and the write are one transaction.
        """
        ...

    def get(self, checkin_id: int) -> Checkin | None: ...

    def close(self, checkin_id: int, at: datetime) -> Checkin | None:
        """Set ``closes_at`` to ``at`` unless it is already past; ``None`` for an unknown id."""
        ...

    def find_open(self, code: str, at: datetime) -> Checkin | None:
        """The check-in with ``code`` that is open at ``at``."""
        ...

    def listed(self) -> list[Listed]:
        """Every check-in with the number of marks, the latest first."""
        ...

    def report(self, checkin_id: int) -> Report | None:
        """The check-in with its marks, the earliest first; ``None`` for an unknown id."""
        ...

    def mark(
        self,
        checkin_id: int,
        participant_id: int,
        source: str,
        rating: int | None,
        question: str | None,
        at: datetime,
    ) -> None:
        """Record the mark; a repeat adds no row and changes only what is passed."""
        ...

    def assign(self, group: str, emails: Sequence[str], at: datetime) -> tuple[int, list[str]]:
        """Put the registered ``emails`` into ``group``.

        Return how many were added now and the addresses nobody is registered with.
        """
        ...

    def group_sizes(self) -> dict[str, int]:
        """The members of every group, by code."""
        ...
