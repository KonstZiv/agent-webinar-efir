"""Ports of the slice «лічильники й експорт»; the shared ones are in ``app.core.ports``.

The reports read the shared tables in ways the foundation's stores do not cover (counts, the
failed invitations, the whole list), so the slice has its own read-only port.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Counts:
    """The two numbers of the page: every participant, and those with a linked Telegram."""

    registered: int
    telegram_linked: int


@dataclass(frozen=True, slots=True)
class Stats:
    """The operator's numbers: v1's three keys, then the two of v2."""

    total: int
    last_24h: int
    failed_emails: int
    telegram_linked: int
    channel_members: int


@dataclass(frozen=True, slots=True)
class ExportRow:
    """A participant as the export shows them: no unsubscribe id, no click or analytics ids."""

    email: str
    registered_at: datetime
    origin: str | None
    telegram_linked: bool
    channel_member: bool | None  # ``None``: never checked
    level: str | None
    utm_source: str | None
    utm_medium: str | None
    utm_campaign: str | None
    utm_content: str | None


class CountSource(Protocol):
    """Where the counters of the page come from."""

    def counts(self) -> Counts: ...


class ReportStore(CountSource, Protocol):
    """Read-only reports on ``participants`` and ``emails`` (v1 writes them too).

    Each report is one statement, so its numbers agree while people register. Failures raise
    as in ``ParticipantStore``: ``StorageUnavailable`` or ``StorageError``.
    """

    def stats(self, registered_since: datetime, stale_after: timedelta) -> Stats:
        """The numbers now; ``last_24h`` counts registrations from ``registered_since`` on.

        ``failed_emails`` keeps v1's name but counts the invitations (``lesson_invitation``)
        only: those the operator's retry sends. A failed email is ``failed``, or ``pending``
        longer than ``stale_after`` since its ``updated_at`` by the database clock, unless its
        ``scheduled_at`` is still ahead.
        """
        ...

    def export_rows(self) -> list[ExportRow]:
        """Every participant, the earliest registration first."""
        ...
