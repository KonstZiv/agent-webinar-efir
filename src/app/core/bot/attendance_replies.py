"""Messages and buttons of the attendance in Telegram: docs/copy.md, section 14.3, word for word.

Texts are not written or shortened here: the oracle (tests/bot/test_attendance_oracle.py) reads
section 14.3 on its own and compares every message the bot sends with it. The values are put in
as that section describes: ``{closes_at}`` and ``{closed_at}`` as «HH:MM» in Kyiv, ``{lesson_date}``
as «DD.MM.YYYY», ``{lesson_day_month}`` as «28 жовтня».
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime

from app.core.bot.ports import ReportSummary
from app.core.entities import Button
from app.core.event_values import MONTHS
from app.core.timezone import KYIV

# ``callback_data`` of the buttons: the rating, a group to open.
RATE_PREFIX = "rate"
OPEN_PREFIX = "open"

POST = (
    "Відмітка присутності на занятті студентів групи {group}. Якщо це не ваша група — "
    "проігноруйте. Щоб відмітитись, натисніть кнопку і надішліть боту код з екрана тренера. "
    "Вікно відкрите {window} хв."
)
POST_BUTTON = "Відмітитись"
CHECKIN_START = "checkin"  # the ``start`` parameter of the post's button; link tokens are longer

# The answers to a code sent to the bot in a private chat.
MARKED = (
    "Ви відмічені на занятті групи {group}, {lesson_day_month}. Як вам заняття? Якщо є запитання "
    "тренеру — просто напишіть його сюди одним повідомленням."
)
ALREADY_MARKED = "Ви вже відмічені ✔"
CODE_INVALID = "Код не підходить, або вікно відмітки вже закрите. Звірте код на екрані тренера."
NOT_LINKED = (
    "Ваш Telegram ще не підключено до реєстрації. Якщо ви зареєстровані — натисніть «Отримати в "
    "Telegram» у листі-запрошенні; якщо ні — зареєструйтеся на {site_host}/course. Потім "
    "надішліть код ще раз."
)
CODE_HINT = "Надішліть сюди код з екрана тренера — 4 символи."
NOT_WRITTEN = "Не вдалося записати. Спробуйте ще раз за хвилину."
NOT_INSTALLED = "Недоступно."

RATED = "Дякуємо! Ваша оцінка: {rating}."
QUESTION_ACCEPTED = "Дякуємо — тренер побачить запитання."
QUESTION_TOO_LONG = "Скоротіть запитання до 500 знаків і надішліть ще раз."
TOO_LATE = "Час для оцінки і запитань минув."

FORBIDDEN = "Команда недоступна."
CHOOSE_GROUP = "Оберіть групу для відмітки:"
USAGE = (
    "Використання: /checkin <група> [хвилин, 1–180] — або /checkin без аргументів і оберіть групу "
    "кнопкою. Типово: 10 хв, дата заняття — сьогодні."
)
OPENED = (
    "Чек-ін #{id} відкрито: заняття {lesson_date}, група {group}, код {code}, вікно до "
    "{closes_at} за Києвом. Пост у каналі опубліковано. Посилання для чату заняття: "
    "{checkin_link}"
)
OPENED_NOT_POSTED = (
    "Чек-ін #{id} відкрито: заняття {lesson_date}, група {group}, код {code}, вікно до "
    "{closes_at} за Києвом. Пост у канал не вдалося опублікувати — перевірте права бота в "
    "каналі; код діє, сайт працює. Посилання для чату заняття: {checkin_link}"
)
ALREADY_OPEN = (
    "Уже є відкритий чек-ін #{id} групи {group} (код {code}, до {closes_at}). Закрийте його: "
    "/checkin_close {group}"
)
CLOSED = "Чек-ін #{id} групи {group} закрито о {closed_at} за Києвом. Відмітились: {attended}."
NO_OPEN = "Відкритих чек-інів немає."
REPORT = (
    "Чек-ін #{id}, заняття {lesson_date}, група {group}: відмітились {attended} (сайт {site}, "
    "Telegram {telegram}). Оцінки: 5 — {r5}, 4 — {r4}, 3 — {r3}, 2 — {r2}, 1 — {r1}; середня "
    "{average}. Запитання ({questions_count}): {questions}"
)
NO_CHECKINS = "Чек-інів ще немає."

NO_GROUP = "—"  # a check-in without a group (opened through the admin API)
NO_AVERAGE = "—"
NO_QUESTIONS = "немає"
MESSAGE_LIMIT = 4096  # the longest text Telegram takes in one message


def clock_time(moment: datetime) -> str:
    """«HH:MM» in Kyiv.

    >>> from datetime import UTC
    >>> clock_time(datetime(2026, 11, 2, 17, 20, tzinfo=UTC))
    '19:20'
    """
    return f"{moment.astimezone(KYIV):%H:%M}"


def full_date(day: date) -> str:
    """«DD.MM.YYYY».

    >>> full_date(date(2026, 11, 2))
    '02.11.2026'
    """
    return f"{day.day:02d}.{day.month:02d}.{day.year}"


def day_month(day: date) -> str:
    """«28 жовтня».

    >>> day_month(date(2026, 10, 28))
    '28 жовтня'
    """
    return f"{day.day} {MONTHS[day.month - 1]}"


def checkin_link(site_url: str, code: str) -> str:
    return f"{site_url}/checkin?code={code}"


def post_buttons(bot_username: str) -> tuple[tuple[Button, ...], ...]:
    """The one button of the post: it opens the chat with the bot and starts ``checkin``."""
    return ((Button(POST_BUTTON, url=f"https://t.me/{bot_username}?start={CHECKIN_START}"),),)




def rating_buttons(checkin_id: int) -> tuple[tuple[Button, ...], ...]:
    return (
        tuple(
            Button(str(number), callback_data=f"{RATE_PREFIX}:{checkin_id}:{number}")
            for number in (1, 2, 3, 4, 5)
        ),
    )


def group_buttons(groups: Sequence[str]) -> tuple[tuple[Button, ...], ...]:
    """The groups to pick from, two in a row."""
    buttons = [Button(group, callback_data=f"{OPEN_PREFIX}:{group}") for group in groups]
    return tuple(tuple(buttons[start : start + 2]) for start in range(0, len(buttons), 2))


def report_text(report: ReportSummary) -> str:
    """The teacher's report: counts, ratings and questions, no addresses."""
    ratings: Mapping[int, int] = report.ratings
    average = f"{report.average:.1f}" if report.average is not None else NO_AVERAGE
    questions = [" ".join(question.split()) for question in report.questions]
    listed = "".join(f"\n{number}. {text}" for number, text in enumerate(questions, start=1))
    return REPORT.format(
        id=report.id,
        lesson_date=full_date(report.lesson_date),
        group=report.group or NO_GROUP,
        attended=report.attended,
        site=report.site,
        telegram=report.telegram,
        r5=ratings.get(5, 0),
        r4=ratings.get(4, 0),
        r3=ratings.get(3, 0),
        r2=ratings.get(2, 0),
        r1=ratings.get(1, 0),
        average=average,
        questions_count=len(questions),
        questions=listed or NO_QUESTIONS,
    )


def _units(text: str) -> int:
    """The length Telegram counts: UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def split_message(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """``text`` in parts of at most ``limit`` characters, cut at line ends where it can.

    Nothing is dropped: the parts joined with a new line give ``text`` back, except where a
    single line is longer than ``limit`` and is cut in the middle.

    >>> split_message("a\\nbb\\nccc", 4)
    ['a\\nbb', 'ccc']
    >>> split_message("x" * 5, 2)
    ['xx', 'xx', 'x']
    """
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        while _units(line) > limit:
            if current:
                parts.append(current)
                current = ""
            cut = len(line)
            while _units(line[:cut]) > limit:
                cut -= 1
            parts.append(line[:cut])
            line = line[cut:]
        joined = f"{current}\n{line}" if current else line
        if current and _units(joined) > limit:
            parts.append(current)
            current = line
        else:
            current = joined
    parts.append(current)
    return [part for part in parts if part] or [""]
