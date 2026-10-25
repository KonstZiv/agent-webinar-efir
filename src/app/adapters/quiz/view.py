"""What ``_quiz.html`` needs: the template global ``quiz`` and the state of one answer.

Where the slice is not installed, the global is absent and the partial renders nothing.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from app.adapters.quiz.texts import QuizTexts
from app.core.quiz.model import Quiz, Result

QUIZ_PATH = "/quiz"
TICKET_FIELD = "ticket"


def question_field(number: int) -> str:
    """The radio group of question ``number`` (from 1); the value is the option's index."""
    return f"q{number}"


@dataclass(frozen=True, slots=True)
class QuizPartial:
    """The content, the texts, the address and the maker of tickets for the partial."""

    quiz: Quiz
    texts: QuizTexts
    ticket_for: Callable[[str], str]
    url: str = QUIZ_PATH
    ticket_field: str = TICKET_FIELD

    def ticket(self, email: str) -> str:
        return self.ticket_for(email)

    def field(self, number: int) -> str:
        return question_field(number)


@dataclass(frozen=True, slots=True)
class QuizState:
    """The answer of ``POST /quiz``: the result, or the form again with a problem.

    ``chosen`` maps a question number (from 1) to the chosen option's index.
    """

    ticket: str = ""
    chosen: dict[int, int] = field(default_factory=dict)
    problem: str | None = None
    result: Result | None = None
