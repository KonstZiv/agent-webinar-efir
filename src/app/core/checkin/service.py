"""The attendance scenarios: open and close a check-in, mark a participant, assign groups.

The log carries counts and the class of a failure only: no address, code or question.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from app.core.checkin.addresses import looks_like_email, normalize_email
from app.core.checkin.model import (
    MAX_QUESTION_LENGTH,
    SOURCE_SITE,
    Checkin,
    Listed,
    Members,
    Report,
    new_code,
    normalize_code,
    parse_rating,
)
from app.core.checkin.ports import CheckinStore
from app.core.ports import Clock, ParticipantStore, RateLimiter, StorageError

logger = logging.getLogger(__name__)

CODE_ATTEMPTS = 20


class Problem(StrEnum):
    """Why a mark was refused; the value names the text to show."""

    CODE_EMPTY = "code_empty"
    CODE_INVALID = "code_invalid"  # unknown, or the check-in is closed
    EMAIL_EMPTY = "email_empty"
    EMAIL_FORMAT = "email_format"
    EMAIL_UNKNOWN = "email_unknown"
    QUESTION_TOO_LONG = "question_too_long"
    TOO_MANY = "too_many"
    RATING_INVALID = "rating_invalid"  # not 1–5: the form offers no such choice
    FAILED = "failed"  # the storage failed


@dataclass(frozen=True, slots=True)
class Marked:
    """The participant is marked (now or before); ``feedback`` — a rating or a question came."""

    checkin: Checkin
    email: str
    feedback: bool


@dataclass(frozen=True, slots=True)
class Refused:
    problem: Problem


class Attendance:
    def __init__(
        self,
        store: CheckinStore,
        participants: ParticipantStore,
        clock: Clock,
        limiter: RateLimiter,
        make_code: Callable[[], str] = new_code,
    ) -> None:
        self._store = store
        self._participants = participants
        self._clock = clock
        self._limiter = limiter
        self._make_code = make_code

    def open(self, lesson_date: date, group: str | None, window_minutes: int) -> Checkin:
        """Open a check-in for ``window_minutes`` from now with a code unique among open ones."""
        now = self._clock.now()
        for _ in range(CODE_ATTEMPTS):
            checkin = self._store.add(
                self._make_code(), lesson_date, group, now, now + timedelta(minutes=window_minutes)
            )
            if checkin is not None:
                logger.info("Check-in opened: window %d min", window_minutes)
                return checkin
        raise StorageError("no free check-in code")

    def close(self, checkin_id: int) -> Checkin | None:
        """Close now; an already closed check-in is returned as it is; ``None`` — unknown id."""
        return self._store.close(checkin_id, self._clock.now())

    def listed(self) -> list[Listed]:
        return self._store.listed()

    def report(self, checkin_id: int) -> Report | None:
        return self._store.report(checkin_id)

    def mark(
        self, client: str, code: str, email: str, rating: str = "", question: str = ""
    ) -> Marked | Refused:
        """Mark the registered participant ``email`` on the open check-in with ``code``.

        The attempt counts first, per ``client``. The code is checked before the address is
        looked up, so only those who see the slide can learn who is registered. A repeat
        changes no row but gives a rating or a question that comes with it.
        """
        if not self._limiter.allow(client):
            return Refused(Problem.TOO_MANY)
        wanted = normalize_code(code)
        address = normalize_email(email)
        text = question.strip()
        if not wanted:
            return Refused(Problem.CODE_EMPTY)
        if not address:
            return Refused(Problem.EMAIL_EMPTY)
        if not looks_like_email(address):
            return Refused(Problem.EMAIL_FORMAT)
        if len(text) > MAX_QUESTION_LENGTH:
            return Refused(Problem.QUESTION_TOO_LONG)
        try:
            stars = parse_rating(rating)
        except ValueError:
            return Refused(Problem.RATING_INVALID)
        now = self._clock.now()
        try:
            checkin = self._store.find_open(wanted, now)
            if checkin is None:
                return Refused(Problem.CODE_INVALID)
            participant = self._participants.by_email(address)
            if participant is None:
                return Refused(Problem.EMAIL_UNKNOWN)
            self._store.mark(checkin.id, participant.id, SOURCE_SITE, stars, text or None, now)
        except StorageError as error:
            logger.warning("Check-in: mark not stored: %s", type(error).__name__)
            return Refused(Problem.FAILED)
        return Marked(checkin, address, feedback=stars is not None or bool(text))

    def assign(self, group: str, emails: Sequence[str]) -> Members:
        """Put the registered addresses into ``group``; the others are returned as unknown."""
        wanted = list(dict.fromkeys(normalize_email(email) for email in emails if email.strip()))
        added, unknown = self._store.assign(group, wanted, self._clock.now())
        logger.info("Group assigned: %d added, %d unknown", added, len(unknown))
        return Members(added, tuple(unknown))

    def group_sizes(self) -> dict[str, int]:
        return self._store.group_sizes()
