"""Port of the slice «жива статистика»: the participants grouped, never listed.

The source returns counts of groups, so no address, name or identifier ever leaves the
database: the core and the page cannot show what they never get.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Group:
    """``count`` participants with the same level, the same Telegram state and registration hour.

    ``hour`` is the start of the UTC hour of the registration (the hours of Kyiv begin at the
    same moments), or ``None`` for a registration before the window the source was asked for.
    """

    level: str | None
    telegram_linked: bool
    hour: datetime | None
    count: int


class GroupSource(Protocol):
    """Where the numbers of the page come from.

    Failures raise as in ``ParticipantStore``: ``StorageUnavailable`` or ``StorageError``.
    """

    def groups(self, since: datetime) -> list[Group]:
        """Every participant, grouped; ``hour`` is set only for registrations from ``since`` on.

        One statement, so the groups agree with each other while people register.
        """
        ...
