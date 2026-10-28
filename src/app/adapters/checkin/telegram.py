"""The attendance for the bot of Telegram: the scenarios of ``app.core.checkin`` in the shape the
bot asks for.

The bot declares what it needs (``AttendanceViaTelegram`` of ``app.core.bot.ports``) and finds
this class by the key ``checkin.telegram``; this slice does not import the bot, so the answers are
dataclasses of its own that have the fields the bot's protocols name. An expected case is a
status, a storage failure is the status ``failed``. The log carries the operation and the class
of a failure, never a code, an address or a question.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal

from app.core.checkin.model import SOURCE_SITE, SOURCE_TELEGRAM, OpenInGroup
from app.core.checkin.service import Attendance, Telegram, Verdict
from app.core.ports import StorageError

logger = logging.getLogger(__name__)

NO_DATE = date.min  # the field of an answer that has no check-in to name
NO_MOMENT = datetime.min.replace(tzinfo=UTC)

type PressStatus = Literal[
    "marked",
    "already",
    "not_linked",
    "closed",
    "rated",
    "too_late",
    "not_marked",
    "saved",
    "too_long",
    "failed",
]
_STATUS: dict[Verdict, PressStatus] = {
    Verdict.MARKED: "marked",
    Verdict.ALREADY: "already",
    Verdict.NOT_LINKED: "not_linked",
    Verdict.CLOSED: "closed",
    Verdict.RATED: "rated",
    Verdict.TOO_LATE: "too_late",
    Verdict.NOT_MARKED: "not_marked",
    Verdict.SAVED: "saved",
    Verdict.TOO_LONG: "too_long",
}


@dataclass(frozen=True, slots=True)
class OpenedAnswer:
    status: Literal["opened", "open_exists", "failed"]
    id: int = 0
    code: str = ""
    group: str = ""
    closes_at: datetime = NO_MOMENT


@dataclass(frozen=True, slots=True)
class ClosedAnswer:
    status: Literal["closed", "none", "failed"]
    id: int = 0
    group: str | None = None
    closed_at: datetime = NO_MOMENT
    attended: int = 0


@dataclass(frozen=True, slots=True)
class ReportAnswer:
    status: Literal["found", "none", "failed"]
    id: int = 0
    lesson_date: date = NO_DATE
    group: str | None = None
    attended: int = 0
    site: int = 0
    telegram: int = 0
    ratings: dict[int, int] = field(default_factory=dict)
    average: float | None = None
    questions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PressedAnswer:
    status: PressStatus
    lesson_date: date = NO_DATE
    checkin_id: int = 0
    group: str | None = None


def _pressed(result: Telegram) -> PressedAnswer:
    checkin = result.checkin
    if checkin is None:
        return PressedAnswer(_STATUS[result.verdict])
    return PressedAnswer(_STATUS[result.verdict], checkin.lesson_date, checkin.id, checkin.group)


def _failed(operation: str, error: StorageError) -> None:
    logger.warning("Telegram attendance %s failed: %s", operation, type(error).__name__)


class TelegramAttendance:
    """``AttendanceViaTelegram`` on the scenarios of ``Attendance``."""

    def __init__(self, attendance: Attendance) -> None:
        self._attendance = attendance

    def known_groups(self, limit: int) -> list[str] | None:
        try:
            return self._attendance.known_groups(limit)
        except StorageError as error:
            _failed("groups", error)
            return None

    def open(self, lesson_date: date, group: str, window_minutes: int) -> OpenedAnswer:
        try:
            found = self._attendance.open_in_group(lesson_date, group, window_minutes)
        except StorageError as error:
            _failed("open", error)
            return OpenedAnswer("failed")
        if isinstance(found, OpenInGroup):
            checkin = found.checkin
            return OpenedAnswer(
                "open_exists", checkin.id, checkin.code, group, checkin.closes_at
            )
        return OpenedAnswer("opened", found.id, found.code, group, found.closes_at)

    def close(self, group: str | None) -> ClosedAnswer:
        try:
            closed = self._attendance.close_latest_open(group)
            if closed is None:
                return ClosedAnswer("none")
            report = self._attendance.report(closed.id)
        except StorageError as error:
            _failed("close", error)
            return ClosedAnswer("failed")
        attended = report.attended if report is not None else 0
        return ClosedAnswer("closed", closed.id, closed.group, closed.closes_at, attended)

    def report(self, group: str | None) -> ReportAnswer:
        try:
            report = self._attendance.latest_report(group)
        except StorageError as error:
            _failed("report", error)
            return ReportAnswer("failed")
        if report is None:
            return ReportAnswer("none")
        checkin = report.checkin
        return ReportAnswer(
            "found",
            id=checkin.id,
            lesson_date=checkin.lesson_date,
            group=checkin.group,
            attended=report.attended,
            site=sum(1 for entry in report.entries if entry.source == SOURCE_SITE),
            telegram=sum(1 for entry in report.entries if entry.source == SOURCE_TELEGRAM),
            ratings=dict(report.ratings),
            average=report.average,
            questions=tuple(entry.question for entry in report.entries if entry.question),
        )

    def mark_code(self, code: str, tg_user_id: int) -> PressedAnswer:
        try:
            return _pressed(self._attendance.mark_telegram_code(code, tg_user_id))
        except StorageError as error:
            _failed("mark", error)
            return PressedAnswer("failed")

    def rate(self, checkin_id: int, tg_user_id: int, rating: int) -> PressedAnswer:
        try:
            return _pressed(self._attendance.rate_telegram(checkin_id, tg_user_id, rating))
        except StorageError as error:
            _failed("rate", error)
            return PressedAnswer("failed")

    def ask(self, tg_user_id: int, text: str) -> PressedAnswer:
        try:
            return _pressed(self._attendance.ask_telegram(tg_user_id, text))
        except StorageError as error:
            _failed("ask", error)
            return PressedAnswer("failed")
