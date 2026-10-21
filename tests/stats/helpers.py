"""Helpers of the slice «жива статистика» tests: stand-in sources of the groups, quiz levels.

The levels are read from docs/quiz.md here, independently of the application (the test's own
parser). Addresses are ``…@example.com`` only.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.core.ports import StorageError, StorageUnavailable
from app.core.stats.ports import Group
from tests.conftest import REPO_ROOT

QUIZ_FILE = REPO_ROOT / "docs" / "quiz.md"
_RESULT_ROW = re.compile(r"^\|[^|]*\|\s*`(\w+)`\s*\|\s*([^|]+?)\s*\|")

LEVELS_FOR_TESTS = {"level1": "Рівень 1 курсу", "level2": "Рівень 2 курсу"}


def quiz_levels() -> dict[str, str]:
    """Value in the database → the name for people, in the order of the results table."""
    text = QUIZ_FILE.read_text(encoding="utf-8")
    results = text.split("## Результати", 1)[1]
    matches = [_RESULT_ROW.match(line) for line in results.splitlines()]
    return {match.group(1): match.group(2) for match in matches if match}


@dataclass
class RecordingSource:
    """A ``GroupSource`` with fixed answers that records its calls, or fails with ``error``."""

    answer: list[Group] = field(default_factory=list)
    error: StorageError | None = None
    calls: list[datetime] = field(default_factory=list)

    def groups(self, since: datetime) -> list[Group]:
        self.calls.append(since)
        if self.error is not None:
            raise self.error
        return self.answer


def unavailable() -> RecordingSource:
    """The database is down: every call raises ``StorageUnavailable``."""
    return RecordingSource(error=StorageUnavailable("test"))


def failing() -> RecordingSource:
    """Every call raises a bare ``StorageError``: a broken statement, not an outage."""
    return RecordingSource(error=StorageError("test"))
