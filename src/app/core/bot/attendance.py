"""The bot's part in the attendance: the teacher's commands, the buttons, the question.

Texts: docs/copy.md, section 14.3 (``app.core.bot.attendance_replies``). The scenarios belong to
the slice «відмітка присутності»; the bot finds them by a key at the moment of use
(``attendance``) and, without them, answers «Недоступно» to a code and «Команда недоступна» to
a command. Only ``TELEGRAM_ADMIN_USER_ID`` gives commands; any other person, and everyone when
the variable is not set, gets the same refusal without details.

Nothing here raises for Telegram or for the storage: a message Telegram does not take is logged
by the class of the failure and nothing else (no ids, codes or questions), because a retried
update must never add a question twice. Storage failures come as the statuses ``failed`` of the
port and are answered with «Не вдалося записати».
"""

import logging
import re
from collections.abc import Callable

from app.core.bot import attendance_replies as texts
from app.core.bot.announce import CheckinPost
from app.core.bot.commands import (
    AttendanceCommand,
    Code,
    PickGroup,
    Question,
    Rate,
    TeacherCommand,
)
from app.core.bot.ports import AttendanceViaTelegram
from app.core.entities import Button
from app.core.ports import Clock, Messenger, MessengerUnavailable
from app.core.timezone import KYIV

logger = logging.getLogger(__name__)

GROUP_PATTERN = r"[a-z0-9-]{2,32}"  # a group code, as the attendance stores it
GROUP = re.compile(GROUP_PATTERN)
_MINUTES = re.compile(r"[0-9]{1,3}")
DEFAULT_MINUTES = 10  # the length of a break
MIN_MINUTES, MAX_MINUTES = 1, 180
KNOWN_GROUPS = 8  # the buttons of «Оберіть групу»

CHECKIN, CLOSE, REPORT = "checkin", "checkin_close", "checkin_report"


class AttendanceDialog:
    """Handles one command, button or text of the attendance; ``handle`` returns a log label."""

    def __init__(
        self,
        *,
        messenger: Messenger,
        clock: Clock,
        attendance: Callable[[], AttendanceViaTelegram | None],
        admin_user_id: int | None,
        announcer: CheckinPost,
        site_url: str,
    ) -> None:
        self._messenger = messenger
        self._clock = clock
        self._attendance = attendance
        self._admin_user_id = admin_user_id
        self._announcer = announcer
        self._site_url = site_url
        self._site_host = site_url.partition("://")[2] or site_url

    def handle(self, command: AttendanceCommand) -> str:
        match command:
            case TeacherCommand():
                return self._teacher(command)
            case PickGroup():
                return self._pick(command)
            case Code():
                return self._code(command)
            case Rate():
                return self._rate(command)
            case Question():
                return self._question(command)

    # --- the teacher ------------------------------------------------------------------------

    def _service_for_teacher(self, user_id: int) -> AttendanceViaTelegram | None:
        """The scenarios, for the teacher only; ``None`` for anyone else or without them."""
        if self._admin_user_id is None or user_id != self._admin_user_id:
            return None
        return self._attendance()

    def _teacher(self, command: TeacherCommand) -> str:
        service = self._service_for_teacher(command.user_id)
        if service is None:
            self._say(command.chat_id, texts.FORBIDDEN)
            return "forbidden"
        tokens = command.arguments.split()
        if command.name == CHECKIN:
            return self._checkin(service, command.chat_id, tokens)
        group = tokens[0] if tokens else None
        if command.name == CLOSE:
            return self._close(service, command.chat_id, group)
        return self._report(service, command.chat_id, group)

    def _checkin(self, service: AttendanceViaTelegram, chat_id: int, tokens: list[str]) -> str:
        if not tokens:
            return self._choose_group(service, chat_id)
        minutes = self._minutes(tokens)
        if minutes is None or not GROUP.fullmatch(tokens[0]):
            self._say(chat_id, texts.USAGE)
            return "usage"
        return self._open(service, chat_id, tokens[0], minutes)

    @staticmethod
    def _minutes(tokens: list[str]) -> int | None:
        """The window of ``/checkin <group> [minutes]``; ``None`` for a wrong argument list."""
        if len(tokens) == 1:
            return DEFAULT_MINUTES
        if len(tokens) > 2 or not _MINUTES.fullmatch(tokens[1]):
            return None
        minutes = int(tokens[1])
        return minutes if MIN_MINUTES <= minutes <= MAX_MINUTES else None

    def _choose_group(self, service: AttendanceViaTelegram, chat_id: int) -> str:
        groups = service.known_groups(KNOWN_GROUPS)
        if groups is None:
            self._say(chat_id, texts.NOT_WRITTEN)
            return "failed"
        if not groups:
            self._say(chat_id, texts.USAGE)
            return "usage"
        self._say(chat_id, texts.CHOOSE_GROUP, texts.group_buttons(groups))
        return "choose_group"

    def _pick(self, command: PickGroup) -> str:
        service = self._service_for_teacher(command.user_id)
        if service is None:
            self._answer(command.callback_id, texts.FORBIDDEN)
            return "forbidden"
        self._answer(command.callback_id)
        return self._open(service, command.chat_id, command.group, DEFAULT_MINUTES)

    def _open(
        self, service: AttendanceViaTelegram, chat_id: int, group: str, minutes: int
    ) -> str:
        today = self._clock.now().astimezone(KYIV).date()
        opened = service.open(today, group, minutes)
        if opened.status == "failed":
            self._say(chat_id, texts.NOT_WRITTEN)
            return "failed"
        closes_at = texts.clock_time(opened.closes_at)
        if opened.status == "open_exists":
            self._say(
                chat_id,
                texts.ALREADY_OPEN.format(
                    id=opened.id, group=opened.group, code=opened.code, closes_at=closes_at
                ),
            )
            return "open_exists"
        posted = self._announcer.announce(opened.id, opened.code, group, today, minutes)
        link = texts.checkin_link(self._site_url, opened.code)
        reply = texts.OPENED if posted else texts.OPENED_NOT_POSTED
        self._say(
            chat_id,
            reply.format(
                id=opened.id,
                lesson_date=texts.full_date(today),
                group=group,
                code=opened.code,
                closes_at=closes_at,
                checkin_link=link,
            ),
        )
        return "opened" if posted else "opened_not_posted"

    def _close(self, service: AttendanceViaTelegram, chat_id: int, group: str | None) -> str:
        if group is not None and not GROUP.fullmatch(group):
            self._say(chat_id, texts.NO_OPEN)
            return "none"
        closed = service.close(group)
        if closed.status == "failed":
            self._say(chat_id, texts.NOT_WRITTEN)
            return "failed"
        if closed.status == "none":
            self._say(chat_id, texts.NO_OPEN)
            return "none"
        self._say(
            chat_id,
            texts.CLOSED.format(
                id=closed.id,
                group=closed.group or texts.NO_GROUP,
                closed_at=texts.clock_time(closed.closed_at),
                attended=closed.attended,
            ),
        )
        return "closed"

    def _report(self, service: AttendanceViaTelegram, chat_id: int, group: str | None) -> str:
        if group is not None and not GROUP.fullmatch(group):
            self._say(chat_id, texts.NO_CHECKINS)
            return "none"
        report = service.report(group)
        if report.status == "failed":
            self._say(chat_id, texts.NOT_WRITTEN)
            return "failed"
        if report.status == "none":
            self._say(chat_id, texts.NO_CHECKINS)
            return "none"
        self._say(chat_id, texts.report_table(report), html=True)
        for part in texts.report_questions(report):
            self._say(chat_id, part)
        return "report"

    # --- the student ------------------------------------------------------------------------

    def _code(self, command: Code) -> str:
        """A code from the teacher's screen: the person is marked, if it fits an open check-in."""
        service = self._attendance()
        if service is None:
            self._say(command.chat_id, texts.NOT_INSTALLED)
            return "unavailable"
        marked = service.mark_code(command.code, command.user_id)
        match marked.status:
            case "marked":
                self._say(
                    command.chat_id,
                    texts.MARKED.format(
                        group=marked.group or texts.NO_GROUP,
                        lesson_day_month=texts.day_month(marked.lesson_date),
                    ),
                    texts.rating_buttons(marked.checkin_id),
                )
            case "already":
                self._say(command.chat_id, texts.ALREADY_MARKED)
            case "not_linked":
                self._say(command.chat_id, texts.NOT_LINKED.format(site_host=self._site_host))
            case "closed":
                self._say(command.chat_id, texts.CODE_INVALID)
            case _:
                self._say(command.chat_id, texts.NOT_WRITTEN)
        return marked.status

    def code_hint(self, chat_id: int, linked: bool) -> str:
        """The answer to ``/start checkin``: ask a linked person for the code, others to link."""
        if self._attendance() is None:
            self._say(chat_id, texts.NOT_INSTALLED)
            return "unavailable"
        if linked:
            self._say(chat_id, texts.CODE_HINT)
            return "code_hint"
        self._say(chat_id, texts.NOT_LINKED.format(site_host=self._site_host))
        return "not_linked"

    def _rate(self, command: Rate) -> str:
        service = self._attendance()
        if service is None:
            self._answer(command.callback_id, texts.NOT_INSTALLED)
            return "unavailable"
        rated = service.rate(command.checkin_id, command.user_id, command.rating)
        match rated.status:
            case "rated":
                self._answer(command.callback_id)
                self._say(command.chat_id, texts.RATED.format(rating=command.rating))
            case "too_late":
                self._answer(command.callback_id)
                self._say(command.chat_id, texts.TOO_LATE)
            case "failed":
                self._answer(command.callback_id, texts.NOT_WRITTEN)
            case _:
                self._answer(command.callback_id)
        return rated.status

    def _question(self, command: Question) -> str:
        service = self._attendance()
        if service is None:
            return "ignored"
        asked = service.ask(command.user_id, command.text)
        match asked.status:
            case "saved":
                self._say(command.chat_id, texts.QUESTION_ACCEPTED)
            case "too_long":
                self._say(command.chat_id, texts.QUESTION_TOO_LONG)
            case "failed":
                self._say(command.chat_id, texts.NOT_WRITTEN)
            case _:
                return "ignored"
        return asked.status

    # --- Telegram ---------------------------------------------------------------------------

    def _say(
        self,
        chat_id: int,
        text: str,
        buttons: tuple[tuple[Button, ...], ...] = (),
        *,
        html: bool = False,
    ) -> None:
        try:
            self._messenger.send_message(chat_id, text, buttons, html=html, preview=False)
        except MessengerUnavailable as error:
            logger.warning("Telegram message not sent: %s", type(error).__name__)

    def _answer(
        self, callback_id: str, text: str | None = None, *, show_alert: bool = False
    ) -> None:
        try:
            self._messenger.answer_callback(callback_id, text, show_alert=show_alert)
        except MessengerUnavailable as error:
            logger.warning("Telegram button not answered: %s", type(error).__name__)
