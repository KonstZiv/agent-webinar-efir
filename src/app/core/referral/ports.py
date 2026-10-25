"""Port of the feature Ф1: the code and the count of one participant.

Failures raise as in ``app.core.ports.ParticipantStore``: ``StorageUnavailable``,
``StorageConflict`` (a taken code), ``StorageError``.
"""

from typing import Protocol


class ReferralStore(Protocol):
    def ensure_code(self, participant_id: int, candidate: str) -> str | None:
        """Store ``candidate`` as the code unless the participant has one; return the code.

        The condition is checked by the statement that writes, so of two requests at the same
        moment one code wins and both get it. ``None``: there is no such participant.
        """
        ...

    def count_referred(self, participant_id: int) -> int:
        """How many participants have ``participant_id`` as their inviter."""
        ...
