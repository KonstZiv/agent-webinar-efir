"""Ports of the quiz."""

from typing import Protocol


class LevelStore(Protocol):
    """Writes the level of a participant; failures raise the ``StorageError`` family."""

    def set_level(self, email: str, level: str) -> bool:
        """Store ``level`` for the participant with this normalised address, replacing any.

        Return whether the participant exists.
        """
        ...
