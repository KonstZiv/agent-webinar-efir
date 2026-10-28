"""The student: the code, the rating, the question (docs/requirements.md, section 7;
texts: docs/copy.md, 14.3). Every update goes through ``POST /telegram/webhook``."""

import logging
from datetime import timedelta

import pytest

from app.adapters.db.models import Checkin
from app.core.entities import TelegramAccount
from tests.bot.attendance import (
    ALREADY_MARKED,
    CODE_INVALID,
    GROUP,
    NOT_INSTALLED,
    NOT_LINKED,
    NOT_WRITTEN,
    NOW,
    QUESTION_ACCEPTED,
    QUESTION_TOO_LONG,
    TEACHER_ENV,
    TOO_LATE,
    add_checkin,
    add_mark,
    broken_marks,
    marked_reply,
    marks,
    rated,
)
from tests.bot.conftest import BotSiteFactory
from tests.bot.helpers import (
    CHANNEL,
    OTHER,
    USER,
    BotSite,
    Telegram,
    app_log,
    buttons,
    callback_update,
    message_update,
)
from tests.conftest import ParticipantFactory


@pytest.fixture
def site(bot_site_factory: BotSiteFactory) -> BotSite:
    return bot_site_factory(messenger=Telegram(), **TEACHER_ENV)


def press(site: BotSite, checkin: Checkin, account: TelegramAccount = USER) -> None:
    """The student sends the code of the check-in to the bot in a private chat."""
    assert site.post(message_update(account, checkin.code)).status_code == 200


def rate(site: BotSite, checkin_id: int, rating: int, account: TelegramAccount = USER) -> None:
    assert site.post(callback_update(account, f"rate:{checkin_id}:{rating}")).status_code == 200


def write(site: BotSite, text: str, account: TelegramAccount = USER) -> None:
    assert site.post(message_update(account, text)).status_code == 200


def answers(site: BotSite) -> list[str | None]:
    return [text for _, text in site.messenger.answered]


# --- the code ---------------------------------------------------------------------------------


def test_a_linked_participant_is_marked_and_gets_the_rating_buttons(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    person = participant_factory("one@example.com", telegram=USER)
    checkin = add_checkin(site)

    site.post(message_update(USER, " ab23 "))  # trimmed and upper-cased

    [mark] = marks(site)
    assert (mark.checkin_id, mark.participant_id) == (checkin.id, person.id)
    assert mark.source == "telegram"
    assert (mark.rating, mark.question) == (None, None)
    assert answers(site) == []
    [private] = site.sent
    assert private.chat_id == USER.user_id
    assert private.text == marked_reply(GROUP, "21 жовтня")
    assert len(private.buttons) == 1  # one row
    assert [button.text for button in buttons(private)] == ["1", "2", "3", "4", "5"]
    assert [button.callback_data for button in buttons(private)] == [
        f"rate:{checkin.id}:{number}" for number in range(1, 6)
    ]


def test_a_second_code_changes_nothing(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    checkin = add_checkin(site)
    press(site, checkin)
    [first] = marks(site)
    site.forget()

    press(site, checkin)

    [again] = marks(site)
    assert (again.id, again.created_at) == (first.id, first.created_at)
    assert [message.text for message in site.sent] == [ALREADY_MARKED]


def test_a_person_marked_on_the_site_is_already_marked(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    person = participant_factory("one@example.com", telegram=USER)
    checkin = add_checkin(site)
    add_mark(site, checkin.id, person.id, source="site")

    press(site, checkin)

    [mark] = marks(site)
    assert mark.source == "site"
    assert [message.text for message in site.sent] == [ALREADY_MARKED]


def test_a_check_in_without_a_group_is_named_with_a_dash(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    checkin = add_checkin(site, group=None)

    press(site, checkin)

    assert [message.text for message in site.sent] == [marked_reply(None)]


def test_a_participant_without_a_linked_telegram_is_told_how_to_link(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=OTHER)
    checkin = add_checkin(site)

    press(site, checkin)

    assert marks(site) == []
    assert [message.text for message in site.sent] == [NOT_LINKED]


def test_a_stranger_gets_the_same_answer_for_a_wrong_code(site: BotSite) -> None:
    add_checkin(site)

    site.post(message_update(USER, "ZZZZ"))

    assert marks(site) == []
    assert [message.text for message in site.sent] == [NOT_LINKED]  # nothing about the codes


def test_a_code_after_the_window_is_refused(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    checkin = add_checkin(site)
    site.clock.advance(timedelta(minutes=20))  # closes_at: the window is half-open

    press(site, checkin)

    assert marks(site) == []
    assert [message.text for message in site.sent] == [CODE_INVALID]


def test_an_unknown_code_does_not_fit(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    add_checkin(site)

    site.post(message_update(USER, "ZZZZ"))

    assert marks(site) == []
    assert [message.text for message in site.sent] == [CODE_INVALID]


def test_the_code_of_another_open_check_in_marks_that_one(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    add_checkin(site, "AB23", GROUP)
    other = add_checkin(site, "CD34", "open-2026-10")

    site.post(message_update(USER, "cd34"))

    assert [mark.checkin_id for mark in marks(site)] == [other.id]
    assert [message.text for message in site.sent] == [marked_reply("open-2026-10")]


@pytest.mark.parametrize("text", ["ABCDE", "AB2", "AB 23", "AB2-", "ЯBCD", "ßAB3", "0OI1"])
def test_other_texts_are_not_a_code(
    site: BotSite, participant_factory: ParticipantFactory, text: str
) -> None:
    participant_factory("one@example.com", telegram=USER)
    add_checkin(site, "AB23")

    site.post(message_update(USER, text))

    assert marks(site) == []
    assert site.sent == []  # not a mark yet, so not a question either


def test_a_press_of_the_old_button_is_not_handled_any_more(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    checkin = add_checkin(site)

    response = site.post(callback_update(USER, f"checkin:{checkin.id}"))

    assert response.status_code == 200
    assert marks(site) == []
    assert site.sent == [] and site.messenger.answered == []


def test_a_personal_message_telegram_refuses_does_not_undo_the_mark(
    bot_site_factory: BotSiteFactory, participant_factory: ParticipantFactory
) -> None:
    from app.core.ports import MessengerUnavailable

    telegram = Telegram(failures={"send_message": [MessengerUnavailable()]})
    site = bot_site_factory(messenger=telegram, **TEACHER_ENV)
    participant_factory("one@example.com", telegram=USER)
    checkin = add_checkin(site)

    press(site, checkin)

    assert len(marks(site)) == 1
    assert site.sent == []


def test_a_storage_failure_is_a_retry_later(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    checkin = add_checkin(site)
    with broken_marks(site):
        press(site, checkin)

    assert [message.text for message in site.sent] == [NOT_WRITTEN]


# --- the rating -------------------------------------------------------------------------------


def test_a_rating_is_stored_and_a_new_one_replaces_it(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    checkin = add_checkin(site)
    press(site, checkin)
    site.forget()

    rate(site, checkin.id, 4)
    assert [mark.rating for mark in marks(site)] == [4]
    assert [message.text for message in site.sent] == [rated(4)]

    rate(site, checkin.id, 2)
    assert [mark.rating for mark in marks(site)] == [2]
    assert [message.text for message in site.sent] == [rated(4), rated(2)]


def test_a_rating_is_taken_until_a_day_after_the_window_closed(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    checkin = add_checkin(site)
    press(site, checkin)
    site.clock.advance(timedelta(hours=24, minutes=19))  # a minute before closes_at + 24 h
    rate(site, checkin.id, 5)
    assert [mark.rating for mark in marks(site)] == [5]
    site.forget()

    site.clock.advance(timedelta(minutes=1))
    rate(site, checkin.id, 1)

    assert [mark.rating for mark in marks(site)] == [5]  # unchanged
    assert [message.text for message in site.sent] == [TOO_LATE]


def test_a_rating_of_someone_who_did_not_mark_is_ignored(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    checkin = add_checkin(site)

    rate(site, checkin.id, 3)
    rate(site, checkin.id, 3, OTHER)

    assert marks(site) == []
    assert site.sent == []
    assert len(site.messenger.answered) == 2  # the buttons stop spinning


# --- the question -----------------------------------------------------------------------------


def marked(site: BotSite, participant_factory: ParticipantFactory) -> int:
    participant_factory("one@example.com", telegram=USER)
    checkin = add_checkin(site)
    press(site, checkin)
    site.forget()
    return checkin.id


def test_a_text_from_a_marked_participant_is_the_question(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    marked(site, participant_factory)

    write(site, "How do I test a webhook?")

    assert [mark.question for mark in marks(site)] == ["How do I test a webhook?"]
    [reply] = site.sent
    assert (reply.chat_id, reply.text, reply.buttons) == (USER.user_id, QUESTION_ACCEPTED, ())


def test_the_next_text_is_added_on_a_new_line(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    marked(site, participant_factory)

    write(site, "First")
    write(site, "Second")

    assert [mark.question for mark in marks(site)] == ["First\nSecond"]
    assert [message.text for message in site.sent] == [QUESTION_ACCEPTED] * 2


def test_a_text_over_the_limit_adds_nothing(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    marked(site, participant_factory)
    write(site, "a" * 300)

    write(site, "b" * 200)  # 300 + 1 + 200 = 501

    assert [mark.question for mark in marks(site)] == ["a" * 300]
    assert [message.text for message in site.sent] == [QUESTION_ACCEPTED, QUESTION_TOO_LONG]


def test_exactly_the_limit_is_accepted(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    marked(site, participant_factory)
    write(site, "a" * 300)

    write(site, "b" * 199)  # 300 + 1 + 199 = 500

    assert [len(mark.question or "") for mark in marks(site)] == [500]


def test_one_text_over_the_limit_is_too_long_at_once(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    marked(site, participant_factory)

    write(site, "a" * 501)

    assert [mark.question for mark in marks(site)] == [None]
    assert [message.text for message in site.sent] == [QUESTION_TOO_LONG]


def test_a_text_from_a_participant_without_a_linked_telegram_is_ignored(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    person = participant_factory("one@example.com", telegram=OTHER)
    checkin = add_checkin(site)
    add_mark(site, checkin.id, person.id)

    write(site, "Who am I?")

    assert [mark.question for mark in marks(site)] == [None]
    assert site.sent == []


def test_a_text_from_a_participant_without_a_mark_is_ignored(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    participant_factory("one@example.com", telegram=USER)
    add_checkin(site)

    write(site, "I was not there")

    assert marks(site) == []
    assert site.sent == []


def test_a_text_from_a_stranger_is_ignored(site: BotSite) -> None:
    add_checkin(site)

    write(site, "Hello")

    assert marks(site) == [] and site.sent == []


def test_a_question_is_taken_until_a_day_after_the_window_closed(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    marked(site, participant_factory)
    site.clock.advance(timedelta(hours=24, minutes=19))
    write(site, "In time")
    site.forget()

    site.clock.advance(timedelta(minutes=1))
    write(site, "Too late")

    assert [mark.question for mark in marks(site)] == ["In time"]
    assert site.sent == []


def test_the_question_goes_to_the_latest_check_in_that_takes_feedback(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    person = participant_factory("one@example.com", telegram=USER)
    old = add_checkin(site, "AB23", GROUP, opened_at=NOW - timedelta(days=3))
    new = add_checkin(site, "CD34", GROUP, opened_at=NOW - timedelta(hours=1))
    add_mark(site, old.id, person.id)
    add_mark(site, new.id, person.id)

    write(site, "For the latest")

    by_checkin = {mark.checkin_id: mark.question for mark in marks(site)}
    assert by_checkin == {old.id: None, new.id: "For the latest"}


def test_a_command_is_not_a_question(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    marked(site, participant_factory)

    write(site, "/help")

    assert [mark.question for mark in marks(site)] == [None]
    assert site.sent == []


def test_a_text_in_a_group_chat_is_not_a_question(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    marked(site, participant_factory)

    site.post(message_update(USER, "Hello all", chat_type="supergroup", chat_id=-100555))

    assert [mark.question for mark in marks(site)] == [None]
    assert site.sent == []


# --- logs -------------------------------------------------------------------------------------


def test_the_log_has_no_codes_addresses_or_questions(
    site: BotSite, participant_factory: ParticipantFactory, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    participant_factory("secret.person@example.com", telegram=USER)
    from tests.bot.attendance import TEACHER, checkin_command, checkins

    checkin_command(site, f"/checkin {GROUP}", TEACHER)
    [checkin] = checkins(site)
    press(site, checkin)
    rate(site, checkin.id, 5)
    write(site, "a-very-private-question")
    checkin_command(site, "/checkin_report")
    checkin_command(site, "/checkin_close")

    log = app_log(caplog)
    for secret in (
        "secret.person",
        "a-very-private-question",
        checkin.code,
        GROUP,
        str(USER.user_id),
        str(TEACHER.user_id),
        CHANNEL,
    ):
        assert secret not in log


def test_without_the_attendance_slice_a_code_says_unavailable() -> None:
    from datetime import UTC, datetime

    from app.core.bot.announce import CheckinPost
    from app.core.bot.attendance import AttendanceDialog
    from app.core.bot.commands import Code
    from tests.fakes import FakeMessenger, FixedClock

    messenger = FakeMessenger()
    dialog = AttendanceDialog(
        messenger=messenger,
        clock=FixedClock(datetime(2026, 10, 21, 16, 0, tzinfo=UTC)),
        attendance=lambda: None,
        admin_user_id=1,
        announcer=CheckinPost(messenger, CHANNEL, "sentinel_webinar_bot"),
        site_url="https://site.example.com",
    )

    dialog.handle(Code(USER.user_id, USER.user_id, "AB23"))

    assert [message.text for message in messenger.sent] == [NOT_INSTALLED]
