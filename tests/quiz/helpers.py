"""Helpers of the quiz tests: docs/quiz.md read by the test's own parser, a fake level store.

The oracle reads the document independently of the application. Addresses are ``…@example.com``
only.
"""

import re
from dataclasses import dataclass, field

from app.core.ports import StorageUnavailable
from tests.conftest import REPO_ROOT

QUIZ_FILE = REPO_ROOT / "docs" / "quiz.md"
EMAIL = "visitor@example.com"
HTMX = {"HX-Request": "true"}


@dataclass(frozen=True)
class OracleQuestion:
    text: str
    options: list[tuple[str, int]]


@dataclass(frozen=True)
class OracleResult:
    low: int
    high: int
    level: str
    name: str
    advice: str


def oracle() -> tuple[list[OracleQuestion], list[OracleResult]]:
    text = QUIZ_FILE.read_text(encoding="utf-8")
    body, results_text = text.split("## Запитання", 1)[1].split("## Результати", 1)
    questions: list[OracleQuestion] = []
    for line in body.splitlines():
        if heading := re.match(r"^### \d+\. (.+)$", line):
            questions.append(OracleQuestion(heading.group(1), []))
        elif option := re.match(r"^- (.+) — ([012])$", line):
            questions[-1].options.append((option.group(1), int(option.group(2))))
    results = [
        OracleResult(int(m[1]), int(m[2]), m[3], m[4].strip(), m[5].strip())
        for m in (
            re.match(r"^\| (\d+)–(\d+) \| `(\w+)` \| ([^|]+) \| ([^|]+) \|$", line)
            for line in results_text.splitlines()
        )
        if m
    ]
    return questions, results


def answers_for(points: list[int]) -> dict[str, str]:
    """Form fields choosing, per question, the first option worth the given points."""
    questions, _ = oracle()
    fields = {}
    for number, (question, wanted) in enumerate(zip(questions, points, strict=True), start=1):
        index = next(i for i, (_, points) in enumerate(question.options) if points == wanted)
        fields[f"q{number}"] = str(index)
    return fields


@dataclass
class FakeLevelStore:
    """``LevelStore`` in memory; ``known`` are the addresses of participants."""

    known: set[str] = field(default_factory=lambda: {EMAIL})
    levels: dict[str, str] = field(default_factory=dict)
    writes: list[tuple[str, str]] = field(default_factory=list)
    broken: bool = False

    def set_level(self, email: str, level: str) -> bool:
        if self.broken:
            raise StorageUnavailable("set level")
        if email not in self.known:
            return False
        self.levels[email] = level
        self.writes.append((email, level))
        return True
