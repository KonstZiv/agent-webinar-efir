"""Entities and rules of the attendance: the check-in, its code, the entries of the report."""

import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I
CODE_LENGTH = 4
DEFAULT_WINDOW_MINUTES = 20
MIN_WINDOW_MINUTES = 1
MAX_WINDOW_MINUTES = 180
MAX_QUESTION_LENGTH = 500
FEEDBACK_PERIOD = timedelta(hours=24)  # a rating and a question are taken this long after closing
RATINGS = (1, 2, 3, 4, 5)
GROUP_CODE_PATTERN = r"[a-z0-9-]{2,32}"
SOURCE_SITE = "site"
SOURCE_TELEGRAM = "telegram"

_GROUP_CODE = re.compile(GROUP_CODE_PATTERN)


def new_code() -> str:
    """A random code for the slide: ``CODE_LENGTH`` characters of ``CODE_ALPHABET``."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(value: str) -> str:
    """What a person typed, as a code: no surrounding whitespace, upper case.

    >>> normalize_code(" 7f3k ")
    '7F3K'
    """
    return value.strip().upper()


def is_group_code(value: str) -> bool:
    """Lower-case Latin letters, digits and hyphens, 2–32 characters.

    >>> is_group_code("cbs-2026-10"), is_group_code("CBS"), is_group_code("x")
    (True, False, False)
    """
    return _GROUP_CODE.fullmatch(value) is not None


def parse_rating(value: str) -> int | None:
    """A rating from a form field: ``1``–``5``, or ``None`` for an empty field.

    >>> parse_rating(""), parse_rating(" 4 ")
    (None, 4)
    >>> parse_rating("6")
    Traceback (most recent call last):
    ...
    ValueError: rating 6 is out of 1-5
    """
    text = value.strip()
    if not text:
        return None
    if not (text.isascii() and text.isdigit()) or int(text) not in RATINGS:
        raise ValueError(f"rating {text} is out of 1-5")
    return int(text)


@dataclass(frozen=True, slots=True)
class Checkin:
    """A check-in of a lesson: open while ``opened_at <= now < closes_at``."""

    id: int
    code: str
    lesson_date: date
    group: str | None
    opened_at: datetime
    closes_at: datetime

    def is_open(self, now: datetime) -> bool:
        return self.opened_at <= now < self.closes_at

    def takes_feedback(self, now: datetime) -> bool:
        """Whether a rating or a question is still taken: ``FEEDBACK_PERIOD`` after closing."""
        return now < self.closes_at + FEEDBACK_PERIOD


@dataclass(frozen=True, slots=True)
class OpenInGroup:
    """The result of opening a check-in for a group that already has an open one."""

    checkin: Checkin


@dataclass(frozen=True, slots=True)
class Mark:
    """A participant's mark with its check-in and the question written so far."""

    checkin: Checkin
    question: str | None


@dataclass(frozen=True, slots=True)
class Entry:
    """A participant's mark as the teacher sees it."""

    email: str
    source: str
    rating: int | None
    question: str | None
    at: datetime


@dataclass(frozen=True, slots=True)
class Report:
    """A check-in with its marks: the count, the ratings and their average."""

    checkin: Checkin
    ratings: dict[int, int]
    entries: tuple[Entry, ...]

    @property
    def attended(self) -> int:
        return len(self.entries)

    @property
    def average(self) -> float | None:
        rated = sum(self.ratings.values())
        if not rated:
            return None
        return round(sum(rating * count for rating, count in self.ratings.items()) / rated, 2)


@dataclass(frozen=True, slots=True)
class Listed:
    """A line of the list of check-ins: the check-in and how many marked themselves."""

    checkin: Checkin
    attended: int


@dataclass(frozen=True, slots=True)
class Members:
    """The result of assigning addresses to a group."""

    added: int
    unknown: tuple[str, ...]
