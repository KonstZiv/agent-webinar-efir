"""Text oracle of the attendance in Telegram: docs/copy.md, section 14.3, word for word.

The oracle reads the tables itself (``tests.bot.attendance``). Each row is made to happen
through the webhook; the bot must say exactly its text, with the values put in as the section
describes them, and with buttons labelled as the column «Кнопки» says.
"""

from collections.abc import Callable
from datetime import timedelta

import pytest

from app.core.bot.announce import CheckinPost
from app.core.bot.attendance import AttendanceDialog
from app.core.bot.commands import Code, TeacherCommand
from app.core.entities import TelegramAccount
from app.core.ports import MessengerUnavailable
from tests.bot.attendance import (
    BOT_USERNAME,
    FORBIDDEN,
    GROUP,
    NOT_INSTALLED,
    OTHER_GROUP,
    POST_BUTTONS,
    ROWS,
    TEACHER,
    TEACHER_ENV,
    add_checkin,
    already_open,
    broken_marks,
    checkin_command,
    checkins,
    closed,
    marked_reply,
    opened,
    post,
    rated,
    report_table,
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


def press(site: BotSite, code: str, account: TelegramAccount = USER) -> None:
    """The student sends the code to the bot."""
    site.post(message_update(account, code))


def linked_and_open(site: BotSite, factory: ParticipantFactory) -> int:
    factory("one@example.com", telegram=USER)
    return add_checkin(site).id


def marked(site: BotSite, factory: ParticipantFactory) -> int:
    """A marked participant; what the bot has said so far is forgotten."""
    checkin_id = linked_and_open(site, factory)
    press(site, "AB23")
    site.forget()
    return checkin_id


# --- the scenes: how each row of the tables comes about ---------------------------------------
# A scene leaves the answer of its row as the last thing the bot said.


def scene_marked(site: BotSite, factory: ParticipantFactory) -> None:
    linked_and_open(site, factory)
    press(site, "AB23")


def scene_already(site: BotSite, factory: ParticipantFactory) -> None:
    marked(site, factory)
    press(site, "AB23")


def scene_not_linked(site: BotSite, factory: ParticipantFactory) -> None:
    factory("one@example.com", telegram=OTHER)
    add_checkin(site)
    press(site, "AB23")


def scene_code_invalid(site: BotSite, factory: ParticipantFactory) -> None:
    linked_and_open(site, factory)
    site.clock.advance(timedelta(minutes=30))
    press(site, "AB23")


def scene_not_written(site: BotSite, factory: ParticipantFactory) -> None:
    linked_and_open(site, factory)
    with broken_marks(site):
        press(site, "AB23")


def scene_code_hint(site: BotSite, factory: ParticipantFactory) -> None:
    factory("one@example.com", telegram=USER)
    site.start(USER, "checkin")


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


SAID: dict[str, Scene] = {
    "Відмічено": scene_marked,
    "Уже відмічені": scene_already,
    "Код не підходить": scene_code_invalid,
    "Telegram не прив'язано": scene_not_linked,
    "Не вдалося записати": scene_not_written,
    "Підказка коду (після кнопки «Відмітитись» під постом)": scene_code_hint,
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
    assert sorted([*SAID, NO_SLICE]) == sorted(ROWS)


def with_values(situation: str, text: str, site: BotSite) -> str:
    """The text of a row with the values the scene makes: one check-in, 21.10.2026, 19:00."""
    row = checkins(site)[-1] if checkins(site) else None
    match situation:
        case "Відмічено":
            return marked_reply(GROUP, "21 жовтня")
        case "Telegram не прив'язано":
            return text.replace("{site_host}", "public-sentinel.example.com")
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
            return report_table(row)  # the labels of the row; no marks, so no questions
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


@pytest.mark.parametrize("situation", sorted(SAID))
def test_no_message_about_the_attendance_has_a_link_preview(
    bot_site_factory: BotSiteFactory, participant_factory: ParticipantFactory, situation: str
) -> None:
    site = bot_site_factory(messenger=Telegram(), **TEACHER_ENV)

    SAID[situation](site, participant_factory)

    assert site.sent
    assert all(not message.preview for message in site.sent)


def test_the_post_of_the_channel_is_the_text_of_the_section(
    bot_site_factory: BotSiteFactory,
) -> None:
    site = bot_site_factory(messenger=Telegram(), **TEACHER_ENV)

    checkin_command(site, f"/checkin {OTHER_GROUP} 45")

    [channel_post, _] = site.sent
    assert channel_post.chat_id == CHANNEL
    assert channel_post.text == post(OTHER_GROUP, 45)
    assert labels(channel_post) == POST_BUTTONS == ("Відмітитись",)
    [[button]] = channel_post.buttons
    assert button.url == f"https://t.me/{BOT_USERNAME}?start=checkin"
    assert button.callback_data is None


def dialog_without_the_slice(messenger: FakeMessenger) -> AttendanceDialog:
    return AttendanceDialog(
        messenger=messenger,
        clock=FixedClock(),
        attendance=lambda: None,
        admin_user_id=TEACHER.user_id,
        announcer=CheckinPost(messenger, CHANNEL, BOT_USERNAME),
        site_url=SITE_URL,
    )


def test_without_the_slice_of_the_attendance_a_code_says_so() -> None:
    messenger = FakeMessenger()

    dialog_without_the_slice(messenger).handle(Code(USER.user_id, USER.user_id, "AB23"))

    assert [message.text for message in messenger.sent] == [ROWS[NO_SLICE][0]] == [NOT_INSTALLED]


@pytest.mark.parametrize("linked", [True, False])
def test_without_the_slice_of_the_attendance_the_hint_says_so(linked: bool) -> None:
    messenger = FakeMessenger()

    dialog_without_the_slice(messenger).code_hint(USER.user_id, linked)

    assert [message.text for message in messenger.sent] == [NOT_INSTALLED]


def test_without_the_slice_of_the_attendance_the_commands_are_unavailable() -> None:
    messenger = FakeMessenger()
    dialog = dialog_without_the_slice(messenger)

    for name in ("checkin", "checkin_close", "checkin_report"):
        dialog.handle(TeacherCommand(TEACHER.user_id, TEACHER.user_id, name, ""))

    assert [message.text for message in messenger.sent] == [FORBIDDEN] * 3
