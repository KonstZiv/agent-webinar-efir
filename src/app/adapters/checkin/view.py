"""What ``_checkin.html`` needs: the template global ``checkin`` and the state of one answer.

Where the slice is not installed, the global is absent and the partial renders nothing.
"""

from dataclasses import dataclass

from app.adapters.checkin.texts import CheckinTexts
from app.core.checkin.model import MAX_QUESTION_LENGTH, RATINGS

CHECKIN_PATH = "/checkin"


@dataclass(frozen=True, slots=True)
class CheckinPartial:
    """The texts and the address of the form for the partial."""

    texts: CheckinTexts
    url: str = CHECKIN_PATH
    ratings: tuple[int, ...] = RATINGS
    max_question: int = MAX_QUESTION_LENGTH


@dataclass(frozen=True, slots=True)
class CheckinState:
    """The answer of ``POST /checkin``: the form again with a problem, or the success.

    ``success`` is the line about the lesson and the address; ``feedback`` — a rating or a
    question came with the mark.
    """

    code: str = ""
    email: str = ""
    rating: str = ""
    question: str = ""
    problem: str | None = None
    success: str | None = None
    feedback: bool = False
