"""The questions and results of the quiz and the scoring (docs/quiz.md).

The data is read from the document by the adapter; the rules live here. Points are never kept:
``Quiz.grade`` turns the chosen options into a result and forgets the sum.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Option:
    text: str
    points: int


@dataclass(frozen=True, slots=True)
class Question:
    text: str
    options: tuple[Option, ...]


@dataclass(frozen=True, slots=True)
class Result:
    """A level: ``level`` is the value stored in the database; ``low``–``high`` the sums."""

    level: str
    name: str
    advice: str
    low: int
    high: int


@dataclass(frozen=True, slots=True)
class Quiz:
    questions: tuple[Question, ...]
    results: tuple[Result, ...]

    def grade(self, choices: Sequence[int | None]) -> Result | None:
        """The result for the chosen option of every question; ``None`` for a bad answer.

        ``choices[i]`` is the index of the option chosen for question ``i``. A missing
        choice, an index out of range or a wrong number of choices is a bad answer.

        >>> quiz = Quiz(
        ...     (Question("?", (Option("a", 0), Option("b", 2))),),
        ...     (Result("low", "Low", "", 0, 1), Result("high", "High", "", 2, 2)),
        ... )
        >>> quiz.grade([1]).level
        'high'
        >>> quiz.grade([None]) is None and quiz.grade([2]) is None
        True
        """
        if len(choices) != len(self.questions):
            return None
        total = 0
        for question, choice in zip(self.questions, choices, strict=True):
            if choice is None or not 0 <= choice < len(question.options):
                return None
            total += question.options[choice].points
        return next((r for r in self.results if r.low <= total <= r.high), None)
