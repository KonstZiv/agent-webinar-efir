"""Text oracle of the attendance in Telegram: docs/copy.md, section 14.3, word for word.

The oracle reads the tables itself (``tests.bot.attendance``). Each row is made to happen
through the webhook; the bot must say exactly its text, with the values put in as the section
describes them, and with buttons labelled as the column «Кнопки» says.
"""

from collections.abc import Callable
from datetime import timedelta

import pytest

from app.core.bot.attendance import AttendanceDialog
from app.core.bot.commands import Press, TeacherCommand
from app.core.entities import TelegramAccount
from app.core.ports import MessengerUnavailable
from tests.bot.attendance import (
    FORBIDDEN,
    GROUP,
    NOT_INSTALLED,
    OTHER_GROUP,
    POST_BUTTONS,
    ROWS,
    TEACHER,
    TEACHER_ENV,
    add_checkin,
    after_mark,
    already_open,
    broken_marks,
    checkin_command,
    checkins,
    closed,
    opened,
    post,
    rated,
)
from tests.bot.conftest import BotSiteFactory
from tests.bot.helpers import (
    CHANNEL,
    OTHER,
    USER,
    BotSite,
    Telegram,
    callback_update,
    labels,
    message_update,
)
from tests.conftest import ParticipantFactory
from tests.fakes import FakeMessenger, FixedClock

type Scene = Callable[[BotSite, ParticipantFactory], None]

SITE_URL = "https://site.example.com"


def press(site: BotSite, checkin_id: int, account: TelegramAccount = USER) -> None:
    site.post(callback_update(account, f"checkin:{checkin_id}", chat_type="channel"))


def linked_and_open(site: BotSite, factory: ParticipantFactory) -> int:
    factory("one@example.com", telegram=USER)
    return add_checkin(site).id


def marked(site: BotSite, factory: ParticipantFactory) -> int:
    """A marked participant; what the bot has said so far is forgotten."""
    checkin_id = linked_and_open(site, factory)
    press(site, checkin_id)
    site.forget()
    site.messenger.answered.clear()
    return checkin_id


# --- the scenes: how each row of the tables comes about ---------------------------------------
# A scene leaves the answer of its row as the last thing the bot said.


def scene_marked(site: BotSite, factory: ParticipantFactory) -> None:
    press(site, linked_and_open(site, factory))


def scene_already(site: BotSite, factory: ParticipantFactory) -> None:
    press(site, marked(site, factory))


def scene_not_linked(site: BotSite, factory: ParticipantFactory) -> None:
    factory("one@example.com", telegram=OTHER)
    press(site, add_checkin(site).id)


def scene_closed(site: BotSite, factory: ParticipantFactory) -> None:
    checkin_id = linked_and_open(site, factory)
    site.clock.advance(timedelta(minutes=30))
    press(site, checkin_id)


def scene_not_written(site: BotSite, factory: ParticipantFactory) -> None:
    checkin_id = linked_and_open(site, factory)
    with broken_marks(site):
        press(site, checkin_id)


def scene_rated(site: BotSite, factory: ParticipantFactory) -> None:
    checkin_id = marked(site, factory)
    site.post(callback_update(USER, f"rate:{checkin_id}:4"))


def scene_question(site: BotSite, factory: ParticipantFactory) -> None:
    marked(site, factory)
    site.post(message_update(USER, "A question"))


def scene_question_too_long(site: BotSite, factory: ParticipantFactory) -> None:
    marked(site, factory)
    site.post(message_update(USER, "q" * 501))


def scene_too_late(site: BotSite, factory: ParticipantFactory) -> None:
    checkin_id = marked(site, factory)
    site.clock.advance(timedelta(hours=25))
    site.post(callback_update(USER, f"rate:{checkin_id}:4"))


def scene_forbidden(site: BotSite, factory: ParticipantFactory) -> None:
    checkin_command(site, f"/checkin {GROUP}", OTHER)


def scene_choose(site: BotSite, factory: ParticipantFactory) -> None:
    add_checkin(site, "AB23", GROUP, opened_at=site.clock.now() - timedelta(days=1))
    checkin_command(site, "/checkin")


def scene_usage(site: BotSite, factory: ParticipantFactory) -> None:
    checkin_command(site, "/checkin")


def scene_opened(site: BotSite, factory: ParticipantFactory) -> None:
    checkin_command(site, f"/checkin {GROUP}")


def scene_opened_not_posted(site: BotSite, factory: ParticipantFactory) -> None:
    assert isinstance(site.messenger, Telegram)
    site.messenger.failures["send_message"] = [MessengerUnavailable()]  # the post is the first
    checkin_command(site, f"/checkin {GROUP}")


def scene_open_exists(site: BotSite, factory: ParticipantFactory) -> None:
    checkin_command(site, f"/checkin {GROUP}")
    checkin_command(site, f"/checkin {GROUP}")


def scene_close(site: BotSite, factory: ParticipantFactory) -> None:
    add_checkin(site, "AB23", GROUP)
    checkin_command(site, "/checkin_close")


def scene_close_none(site: BotSite, factory: ParticipantFactory) -> None:
    checkin_command(site, "/checkin_close")


def scene_report(site: BotSite, factory: ParticipantFactory) -> None:
    add_checkin(site, "AB23", GROUP)
    checkin_command(site, "/checkin_report")


def scene_report_none(site: BotSite, factory: ParticipantFactory) -> None:
    checkin_command(site, "/checkin_report")


# Rows told by ``answer_callback``; the others by a message.
ANSWERED: dict[str, Scene] = {
    "Відмічено": scene_marked,
    "Уже відмічені": scene_already,
    "Telegram не прив'язано": scene_not_linked,
    "Вікно закрите": scene_closed,
    "Не вдалося записати": scene_not_written,
}
SAID: dict[str, Scene] = {
    "Після відмітки": scene_marked,
    "Оцінку прийнято": scene_rated,
    "Запитання прийнято": scene_question,
    "Запитання довше за 500 знаків": scene_question_too_long,
    "Час минув (понад добу після заняття)": scene_too_late,
    "Не адмін або змінну не задано": scene_forbidden,
    "/checkin без аргументів, є відомі групи": scene_choose,
    "/checkin з помилкою або без відомих груп": scene_usage,
    "Чек-ін відкрито, пост опубліковано": scene_opened,
    "Чек-ін відкрито, пост не опубліковано": scene_opened_not_posted,
    "Є відкритий чек-ін": scene_open_exists,
    "/checkin_close": scene_close,
    "/checkin_close без відкритого": scene_close_none,
    "/checkin_report": scene_report,
    "/checkin_report без чек-інів": scene_report_none,
}
# The slice is installed in every test application: this row is checked with the dialog alone.
NO_SLICE = "Зріз відмітки не підключено"


def test_every_row_of_the_tables_has_a_scene() -> None:
    """A new situation in copy.md needs a test (and code) before this is green again."""
    assert sorted([*ANSWERED, *SAID, NO_SLICE]) == sorted(ROWS)


@pytest.mark.parametrize("situation", sorted(ANSWERED))
def test_the_bot_answers_the_button_with_the_text_of_the_situation(
    bot_site_factory: BotSiteFactory, participant_factory: ParticipantFactory, situation: str
) -> None:
    site = bot_site_factory(messenger=Telegram(), **TEACHER_ENV)

    ANSWERED[situation](site, participant_factory)

    assert site.messenger.answered[-1][1] == ROWS[situation][0]


def with_values(situation: str, text: str, site: BotSite) -> str:
    """The text of a row with the values the scene makes: one check-in, 21.10.2026, 19:00."""
    row = checkins(site)[-1] if checkins(site) else None
    match situation:
        case "Після відмітки":
            return after_mark("21 жовтня")
        case "Оцінку прийнято":
            return rated(4)
        case "Чек-ін відкрито, пост опубліковано":
            assert row is not None
            return opened(row)
        case "Чек-ін відкрито, пост не опубліковано":
            assert row is not None
            return opened(row, posted=False)
        case "Є відкритий чек-ін":
            assert row is not None
            return already_open(row)
        case "/checkin_close":
            assert row is not None
            return closed(row, "19:00", 0)
        case "/checkin_report":
            assert row is not None
            values = {
                "id": row.id,
                "lesson_date": "21.10.2026",
                "group": GROUP,
                "attended": 0,
                "site": 0,
                "telegram": 0,
                "average": "—",
                "questions_count": 0,
                "questions": "немає",
                "r5": 0,
                "r4": 0,
                "r3": 0,
                "r2": 0,
                "r1": 0,
            }
            for name, value in values.items():
                text = text.replace("{" + name + "}", str(value))
    return text


def expected_labels(situation: str) -> tuple[str, ...]:
    """The column «Кнопки»; «Оберіть групу» has the codes of the groups instead."""
    if situation == "/checkin без аргументів, є відомі групи":
        return (GROUP,)
    cells = ROWS[situation]
    if len(cells) < 2 or cells[1] == "—":
        return ()
    return tuple(label.strip() for label in cells[1].split("·"))


@pytest.mark.parametrize("situation", sorted(SAID))
def test_the_bot_says_the_text_of_the_situation(
    bot_site_factory: BotSiteFactory, participant_factory: ParticipantFactory, situation: str
) -> None:
    site = bot_site_factory(messenger=Telegram(), **TEACHER_ENV)

    SAID[situation](site, participant_factory)

    message = site.sent[-1]
    assert message.text == with_values(situation, ROWS[situation][0], site)
    assert "{" not in message.text
    assert labels(message) == expected_labels(situation)


def test_the_post_of_the_channel_is_the_text_of_the_section(
    bot_site_factory: BotSiteFactory,
) -> None:
    site = bot_site_factory(messenger=Telegram(), **TEACHER_ENV)

    checkin_command(site, f"/checkin {OTHER_GROUP} 45")

    [channel_post, _] = site.sent
    assert channel_post.chat_id == CHANNEL
    assert channel_post.text == post(OTHER_GROUP, 45)
    assert labels(channel_post) == POST_BUTTONS == ("Я на занятті", "Відмітитись на сайті")


def dialog_without_the_slice(messenger: FakeMessenger) -> AttendanceDialog:
    return AttendanceDialog(
        messenger=messenger,
        clock=FixedClock(),
        attendance=lambda: None,
        admin_user_id=TEACHER.user_id,
        channel=CHANNEL,
        site_url=SITE_URL,
    )


def test_without_the_slice_of_the_attendance_the_button_says_so() -> None:
    messenger = FakeMessenger()

    dialog_without_the_slice(messenger).handle(Press(USER.user_id, "callback-1", 5))

    assert messenger.answered == [("callback-1", ROWS[NO_SLICE][0])] == [
        ("callback-1", NOT_INSTALLED)
    ]


def test_without_the_slice_of_the_attendance_the_commands_are_unavailable() -> None:
    messenger = FakeMessenger()
    dialog = dialog_without_the_slice(messenger)

    for name in ("checkin", "checkin_close", "checkin_report"):
        dialog.handle(TeacherCommand(TEACHER.user_id, TEACHER.user_id, name, ""))

    assert [message.text for message in messenger.sent] == [FORBIDDEN] * 3
