"""The quiz scenario: check the ticket, grade the answer, store only the level."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.core.ports import Clock, StorageError
from app.core.quiz.model import Quiz, Result
from app.core.quiz.ports import LevelStore
from app.core.quiz.ticket import make_ticket, read_ticket

logger = logging.getLogger(__name__)


class Problem(StrEnum):
    INCOMPLETE = "incomplete"  # a missing or spoiled answer
    EXPIRED = "expired"  # no genuine ticket, or it ran out
    NOT_SAVED = "not_saved"  # the storage failed


@dataclass(frozen=True, slots=True)
class Answered:
    result: Result


@dataclass(frozen=True, slots=True)
class Refused:
    problem: Problem


class LevelQuiz:
    def __init__(self, quiz: Quiz, store: LevelStore, clock: Clock, secret: str) -> None:
        self._quiz = quiz
        self._store = store
        self._clock = clock
        self._secret = secret

    def ticket(self, email: str) -> str:
        """The permission to answer for the participant with this normalised address."""
        return make_ticket(email, self._clock.now(), self._secret)

    def answer(self, ticket: str, choices: Sequence[int | None]) -> Answered | Refused:
        """Grade ``choices`` and store the level for the owner of ``ticket``.

        The ticket is checked first, so a foreign request learns nothing and writes nothing.
        The sum is not kept; the log names the class of a failure only.
        """
        email = read_ticket(ticket, self._clock.now(), self._secret)
        if email is None:
            return Refused(Problem.EXPIRED)
        result = self._quiz.grade(choices)
        if result is None:
            return Refused(Problem.INCOMPLETE)
        try:
            found = self._store.set_level(email, result.level)
        except StorageError as error:
            logger.warning("Quiz: level not stored: %s", type(error).__name__)
            return Refused(Problem.NOT_SAVED)
        return Answered(result) if found else Refused(Problem.EXPIRED)
