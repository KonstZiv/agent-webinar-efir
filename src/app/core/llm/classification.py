"""The classification of a lead: what the model says about the person's level and intent."""

from dataclasses import dataclass
from enum import StrEnum


class Level(StrEnum):
    BEGINNER = "beginner"
    EXPERIENCED = "experienced"
    UNKNOWN = "unknown"


class Intent(StrEnum):
    READY_TO_ENROLL = "ready_to_enroll"
    CONSIDERING = "considering"
    BROWSING = "browsing"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Classification:
    level: Level
    intent: Intent

    def as_json(self) -> dict[str, str]:
        """The value stored in ``participants.extra["llm"]``."""
        return {"level": self.level.value, "intent": self.intent.value}


def read_classification(level: object, intent: object) -> Classification:
    """A classification from what the model wrote; a value outside the lists is ``unknown``.

    >>> read_classification("beginner", "browsing")
    Classification(level=<Level.BEGINNER: 'beginner'>, intent=<Intent.BROWSING: 'browsing'>)
    >>> read_classification("guru", None).level, read_classification("guru", None).intent
    (<Level.UNKNOWN: 'unknown'>, <Intent.UNKNOWN: 'unknown'>)
    """
    return Classification(
        _member(Level, level, Level.UNKNOWN), _member(Intent, intent, Intent.UNKNOWN)
    )


def _member[E: StrEnum](kind: type[E], value: object, default: E) -> E:
    if isinstance(value, str):
        try:
            return kind(value)
        except ValueError:
            pass
    return default
