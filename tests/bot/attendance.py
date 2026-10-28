"""Helpers of the attendance in the bot's tests: the teacher, the rows, the texts of 14.3.

The expected texts are read from docs/copy.md, section 14.3, by this module on its own
(``texts``), never from the application. The rows go straight into the test database through
the foundation's models; the bot's tests do not use the other slice's code.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.adapters.db.models import Attendance, Checkin, ParticipantGroup
from app.core.entities import TelegramAccount
from tests import copy_oracle as copy
from tests.bot.helpers import SITE_URL, BotSite, message_update
from tests.fakes import WEBINAR_START

TEACHER = TelegramAccount(777000111, "teacher_name")
TEACHER_ENV = {"TELEGRAM_ADMIN_USER_ID": str(TEACHER.user_id)}
GROUP = "cbs-2026-10"
OTHER_GROUP = "open-2026-10"
# The fake clock stands at 19:00 in Kyiv on 21.10.2026 (tests/fakes.py).
TODAY = date(2026, 10, 21)
NOW = WEBINAR_START


def texts() -> dict[str, list[str]]:
    """Every row of the tables of section 14.3: the situation → the other cells."""
    section = copy.section("14.3", copy.raw_copy_text())
    found: dict[str, list[str]] = {}
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [copy.plain(cell) for cell in line.strip().strip("|").split("|")]
        if cells[0] == "Ситуація" or set(cells[0]) <= set(":- "):
            continue
        found[cells[0]] = cells[1:]
    assert found, "no rows in section 14.3"
    return found


ROWS = texts()
POST_SECTION = copy.section("14.3", copy.raw_copy_text())
POST_TEXT = copy.one(POST_SECTION, "Текст")
POST_BUTTONS = tuple(label.strip() for label in copy.one(POST_SECTION, "Кнопки").split("·"))


def say(situation: str) -> str:
    """The text of a row of 14.3 as it stands, with no values to put in."""
    return ROWS[situation][0]


FORBIDDEN = say("Не адмін або змінну не задано")
CHOOSE = say("/checkin без аргументів, є відомі групи")
USAGE = say("/checkin з помилкою або без відомих груп")
MARKED = say("Відмічено")
ALREADY_MARKED = say("Уже відмічені")
NOT_LINKED = say("Telegram не прив'язано")
WINDOW_CLOSED = say("Вікно закрите")
NOT_WRITTEN = say("Не вдалося записати")
NOT_INSTALLED = say("Зріз відмітки не підключено")
QUESTION_ACCEPTED = say("Запитання прийнято")
QUESTION_TOO_LONG = say("Запитання довше за 500 знаків")
TOO_LATE = say("Час минув (понад добу після заняття)")
NO_OPEN = say("/checkin_close без відкритого")
NO_CHECKINS = say("/checkin_report без чек-інів")


def after_mark(lesson_day_month: str) -> str:
    return say("Після відмітки").replace("{lesson_day_month}", lesson_day_month)


def rated(rating: int) -> str:
    return say("Оцінку прийнято").replace("{rating}", str(rating))


def post(group: str, window: int, lesson_day_month: str = "21 жовтня") -> str:
    return (
        POST_TEXT.replace("{group}", group)
        .replace("{lesson_day_month}", lesson_day_month)
        .replace("{window}", str(window))
    )


def link(code: str) -> str:
    return f"{SITE_URL}/checkin?code={code}"


def opened(
    checkin: Checkin,
    *,
    posted: bool = True,
    closes_at: str = "19:20",
    lesson_date: str = "21.10.2026",
) -> str:
    published = "Чек-ін відкрито, пост опубліковано"
    row = published if posted else "Чек-ін відкрито, пост не опубліковано"
    return (
        say(row)
        .replace("{id}", str(checkin.id))
        .replace("{lesson_date}", lesson_date)
        .replace("{group}", str(checkin.group_code))
        .replace("{code}", checkin.code)
        .replace("{closes_at}", closes_at)
        .replace("{checkin_link}", link(checkin.code))
    )


def already_open(checkin: Checkin, closes_at: str = "19:20") -> str:
    return (
        say("Є відкритий чек-ін")
        .replace("{id}", str(checkin.id))
        .replace("{group}", str(checkin.group_code))
        .replace("{code}", checkin.code)
        .replace("{closes_at}", closes_at)
    )


def closed(checkin: Checkin, closed_at: str, attended: int) -> str:
    return (
        say("/checkin_close")
        .replace("{id}", str(checkin.id))
        .replace("{group}", str(checkin.group_code))
        .replace("{closed_at}", closed_at)
        .replace("{attended}", str(attended))
    )


# --- the teacher's words ------------------------------------------------------------------------


def command(account: TelegramAccount, text: str) -> dict[str, object]:
    return message_update(account, text)


def checkin_command(site: BotSite, text: str, account: TelegramAccount = TEACHER) -> None:
    assert site.post(command(account, text)).status_code == 200


# --- rows ------------------------------------------------------------------------------------


def add_checkin(
    site: BotSite,
    code: str = "AB23",
    group: str | None = GROUP,
    *,
    opened_at: datetime = NOW,
    window: timedelta = timedelta(minutes=20),
    lesson_date: date = TODAY,
) -> Checkin:
    with Session(site.engine) as session:
        row = Checkin(
            code=code,
            lesson_date=lesson_date,
            group_code=group,
            opened_at=opened_at,
            closes_at=opened_at + window,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def add_member(site: BotSite, participant_id: int, group: str, at: datetime = NOW) -> None:
    with Session(site.engine) as session:
        session.add(
            ParticipantGroup(participant_id=participant_id, group_code=group, assigned_at=at)
        )
        session.commit()


def add_mark(
    site: BotSite,
    checkin_id: int,
    participant_id: int,
    *,
    source: str = "site",
    rating: int | None = None,
    question: str | None = None,
) -> None:
    with Session(site.engine) as session:
        session.add(
            Attendance(
                checkin_id=checkin_id,
                participant_id=participant_id,
                source=source,
                rating=rating,
                question=question,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


@contextmanager
def broken_marks(site: BotSite) -> Iterator[None]:
    """The table of the marks is gone for a while: every write to it fails."""
    with site.engine.begin() as connection:
        connection.execute(text("ALTER TABLE attendance RENAME TO attendance_gone"))
    try:
        yield
    finally:
        with site.engine.begin() as connection:
            connection.execute(text("ALTER TABLE attendance_gone RENAME TO attendance"))


def marks(site: BotSite) -> list[Attendance]:
    with Session(site.engine) as session:
        return list(session.scalars(select(Attendance).order_by(Attendance.id)))


def checkins(site: BotSite) -> list[Checkin]:
    with Session(site.engine) as session:
        return list(session.scalars(select(Checkin).order_by(Checkin.id)))

