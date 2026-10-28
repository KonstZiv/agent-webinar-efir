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
    FEEDBACK_PERIOD,
    MAX_QUESTION_LENGTH,
    RATINGS,
    SOURCE_SITE,
    SOURCE_TELEGRAM,
    Checkin,
    Listed,
    Members,
    OpenInGroup,
    Report,
    new_code,
    normalize_code,
    parse_rating,
)
from app.core.checkin.ports import CheckinStore
from app.core.ports import Clock, ParticipantStore, RateLimiter, StorageError

logger = logging.getLogger(__name__)

CODE_ATTEMPTS = 20
QUESTION_ATTEMPTS = 3


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


class Verdict(StrEnum):
    """What came of a mark, a rating or a question from Telegram; the value is the status."""

    MARKED = "marked"
    ALREADY = "already"  # marked before
    NOT_LINKED = "not_linked"  # no registration has this Telegram
    CLOSED = "closed"  # the window is shut, or there is no such check-in
    RATED = "rated"
    TOO_LATE = "too_late"  # the day for a rating is over
    NOT_MARKED = "not_marked"  # no mark to rate or to ask under
    SAVED = "saved"
    TOO_LONG = "too_long"


@dataclass(frozen=True, slots=True)
class Telegram:
    """The verdict and the check-in it concerns, when there is one."""

    verdict: Verdict
    checkin: Checkin | None = None


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

    def open_in_group(
        self, lesson_date: date, group: str | None, window_minutes: int
    ) -> Checkin | OpenInGroup:
        """Like ``open``, but a group with an open check-in gets no second one (it is returned)."""
        now = self._clock.now()
        for _ in range(CODE_ATTEMPTS):
            found = self._store.add_in_group(
                self._make_code(),
                lesson_date,
                group,
                now,
                now + timedelta(minutes=window_minutes),
            )
            if found is not None:
                if isinstance(found, Checkin):
                    logger.info("Check-in opened: window %d min", window_minutes)
                return found
        raise StorageError("no free check-in code")

    def close(self, checkin_id: int) -> Checkin | None:
        """Close now; an already closed check-in is returned as it is; ``None`` — unknown id."""
        return self._store.close(checkin_id, self._clock.now())

    def close_latest_open(self, group: str | None) -> Checkin | None:
        """Close the latest open check-in of ``group`` (of any group if ``None``)."""
        found = self._store.latest_open(group, self._clock.now())
        return None if found is None else self.close(found.id)

    def latest_report(self, group: str | None) -> Report | None:
        """The report of the latest check-in of ``group`` (of any group if ``None``)."""
        found = self._store.latest(group)
        return None if found is None else self._store.report(found.id)

    def known_groups(self, limit: int) -> list[str]:
        """Group codes the teacher can pick, the freshest first."""
        return self._store.known_groups(limit)

    def mark_telegram_code(self, code: str, tg_user_id: int) -> Telegram:
        """Mark the participant with this Telegram on the open check-in with ``code``.

        The Telegram is looked up first: a person with none learns nothing about the codes.
        """
        now = self._clock.now()
        participant = self._participants.by_telegram(tg_user_id)
        if participant is None:
            return Telegram(Verdict.NOT_LINKED)
        checkin = self._store.find_open(normalize_code(code), now)
        if checkin is None:
            return Telegram(Verdict.CLOSED)
        added = self._store.mark(checkin.id, participant.id, SOURCE_TELEGRAM, None, None, now)
        return Telegram(Verdict.MARKED if added else Verdict.ALREADY, checkin)

    def rate_telegram(self, checkin_id: int, tg_user_id: int, rating: int) -> Telegram:
        """Replace the rating of the participant's mark; taken until a day after closing."""
        if rating not in RATINGS:
            return Telegram(Verdict.NOT_MARKED)
        now = self._clock.now()
        checkin = self._store.get(checkin_id)
        participant = self._participants.by_telegram(tg_user_id)
        if checkin is None or participant is None:
            return Telegram(Verdict.NOT_MARKED)
        if not checkin.takes_feedback(now):
            return Telegram(Verdict.TOO_LATE, checkin)
        if not self._store.set_rating(checkin.id, participant.id, rating, now):
            return Telegram(Verdict.NOT_MARKED, checkin)
        return Telegram(Verdict.RATED, checkin)

    def ask_telegram(self, tg_user_id: int, text: str) -> Telegram:
        """Add the question to the latest mark that still takes feedback, on a new line.

        Without such a mark (or a registration) nothing is stored. The question stays within
        ``MAX_QUESTION_LENGTH`` together with what was written before, or nothing is added.
        """
        now = self._clock.now()
        participant = self._participants.by_telegram(tg_user_id)
        if participant is None:
            return Telegram(Verdict.NOT_MARKED)
        addition = text.strip()
        for _ in range(QUESTION_ATTEMPTS):
            mark = self._store.latest_mark(participant.id, now - FEEDBACK_PERIOD)
            if mark is None or not addition:
                return Telegram(Verdict.NOT_MARKED)
            joined = f"{mark.question}\n{addition}" if mark.question else addition
            if len(joined) > MAX_QUESTION_LENGTH:
                return Telegram(Verdict.TOO_LONG, mark.checkin)
            saved = self._store.set_question(
                mark.checkin.id, participant.id, mark.question, joined, now
            )
            if saved:
                return Telegram(Verdict.SAVED, mark.checkin)
        raise StorageError("the question keeps changing")  # two people with one Telegram at once

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
