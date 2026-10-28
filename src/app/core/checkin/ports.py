"""The store of the attendance; every method raises ``StorageError`` (``app.core.ports``)."""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol

from app.core.checkin.model import Checkin, Listed, Mark, OpenInGroup, Report


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

    def add_in_group(
        self,
        code: str,
        lesson_date: date,
        group: str,
        opened_at: datetime,
        closes_at: datetime,
    ) -> Checkin | OpenInGroup | None:
        """Like ``add``, but a group with an open check-in (``closes_at > opened_at``) gets none.

        Return that open check-in as ``OpenInGroup``, ``None`` for a taken code. The checks and
        the write are one transaction, under the same lock as ``add``.
        """
        ...

    def get(self, checkin_id: int) -> Checkin | None: ...

    def latest(self, group: str | None) -> Checkin | None:
        """The latest check-in of ``group``, or of any group if ``None``."""
        ...

    def latest_open(self, group: str | None, at: datetime) -> Checkin | None:
        """The latest check-in of ``group`` (any group if ``None``) that is open at ``at``."""
        ...

    def known_groups(self, limit: int) -> list[str]:
        """Group codes from the members and from the check-ins, the freshest first."""
        ...

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
    ) -> bool:
        """Record the mark; a repeat adds no row and changes only what is passed.

        Return whether the row was added now.
        """
        ...

    def set_rating(self, checkin_id: int, participant_id: int, rating: int, at: datetime) -> bool:
        """Replace the rating of an existing mark; ``False`` if the person has no mark there."""
        ...

    def latest_mark(self, participant_id: int, closes_after: datetime) -> Mark | None:
        """The latest mark of the person on a check-in that closes after ``closes_after``."""
        ...

    def set_question(
        self, checkin_id: int, participant_id: int, old: str | None, new: str, at: datetime
    ) -> bool:
        """Write ``new`` as the question if it is still ``old``; ``False`` if it changed."""
        ...

    def assign(self, group: str, emails: Sequence[str], at: datetime) -> tuple[int, list[str]]:
        """Put the registered ``emails`` into ``group``.

        Return how many were added now and the addresses nobody is registered with.
        """
        ...

    def group_sizes(self) -> dict[str, int]:
        """The members of every group, by code."""
        ...
