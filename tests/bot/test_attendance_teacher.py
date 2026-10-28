"""The teacher's commands: ``/checkin``, the choice of a group, ``/checkin_close``,
``/checkin_report`` (docs/requirements.md, sections 7 and 9а; texts: docs/copy.md, 14.3)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.ports import MessengerUnavailable
from tests.bot.attendance import (
    BOT_USERNAME,
    CHOOSE,
    FORBIDDEN,
    GROUP,
    NO_CHECKINS,
    NO_OPEN,
    NOW,
    OTHER_GROUP,
    POST_BUTTONS,
    TEACHER,
    TEACHER_ENV,
    USAGE,
    add_checkin,
    add_mark,
    add_member,
    already_open,
    checkin_command,
    checkins,
    closed,
    link,
    opened,
    post,
)
from tests.bot.conftest import BotSiteFactory
from tests.bot.helpers import (
    CHANNEL,
    OTHER,
    BotSite,
    Telegram,
    buttons,
    callback_update,
    labels,
)
from tests.conftest import ParticipantFactory
from tests.fakes import FixedClock


@pytest.fixture
def site(bot_site_factory: BotSiteFactory) -> BotSite:
    return bot_site_factory(messenger=Telegram(), **TEACHER_ENV)


def test_checkin_opens_a_check_in_of_the_group_for_today_and_posts_it(site: BotSite) -> None:
    checkin_command(site, f"/checkin {GROUP}")

    [row] = checkins(site)
    assert (row.group_code, str(row.lesson_date)) == (GROUP, "2026-10-21")  # today in Kyiv
    assert (row.opened_at, row.closes_at) == (NOW, NOW + timedelta(minutes=10))  # a break
    [channel_post, reply] = site.sent
    assert channel_post.chat_id == CHANNEL
    assert channel_post.text == post(GROUP, 10)
    assert labels(channel_post) == POST_BUTTONS
    assert len(channel_post.buttons) == 1  # one row, one button
    [open_bot] = buttons(channel_post)
    assert open_bot.url == f"https://t.me/{BOT_USERNAME}?start=checkin"
    assert open_bot.callback_data is None
    assert row.code not in channel_post.text  # the code is on the teacher's screen only
    assert reply.chat_id == TEACHER.user_id
    assert reply.text == opened(row)
    assert link(row.code) in reply.text


def test_checkin_takes_the_window_in_minutes(site: BotSite) -> None:
    checkin_command(site, f"/checkin {GROUP} 15")

    [row] = checkins(site)
    assert row.closes_at - row.opened_at == timedelta(minutes=15)
    assert site.sent[0].text == post(GROUP, 15)
    assert site.sent[1].text == opened(row, closes_at="19:15")


def test_checkin_accepts_the_name_of_the_bot_after_the_command(site: BotSite) -> None:
    checkin_command(site, f"/checkin@sentinel_webinar_bot {GROUP} 30")

    [row] = checkins(site)
    assert row.closes_at - row.opened_at == timedelta(minutes=30)


def test_the_date_of_the_lesson_is_today_in_kyiv_not_in_utc(
    bot_site_factory: BotSiteFactory,
) -> None:
    # 22:30 UTC on 21.10 is 01:30 on 22.10 in Kyiv.
    clock = FixedClock(datetime(2026, 10, 21, 22, 30, tzinfo=UTC))
    site = bot_site_factory(messenger=Telegram(), clock=clock, **TEACHER_ENV)

    checkin_command(site, f"/checkin {GROUP}")

    [row] = checkins(site)
    assert str(row.lesson_date) == "2026-10-22"
    assert site.sent[0].text == post(GROUP, 10)


@pytest.mark.parametrize("window", ["1", "180"])
def test_the_limits_of_the_window_are_allowed(site: BotSite, window: str) -> None:
    checkin_command(site, f"/checkin {GROUP} {window}")

    [row] = checkins(site)
    assert row.closes_at - row.opened_at == timedelta(minutes=int(window))


@pytest.mark.parametrize(
    "text",
    [
        "/checkin X",
        "/checkin a",
        f"/checkin {'a' * 33}",
        f"/checkin {GROUP} 0",
        f"/checkin {GROUP} 181",
        f"/checkin {GROUP} -5",
        f"/checkin {GROUP} abc",
        f"/checkin {GROUP} 5 6",
        "/checkin cbs_2026",
    ],
)
def test_wrong_arguments_get_the_usage_and_open_nothing(site: BotSite, text: str) -> None:
    checkin_command(site, text)

    assert [message.text for message in site.sent] == [USAGE]
    assert checkins(site) == []


def test_another_person_cannot_open_a_check_in(site: BotSite) -> None:
    checkin_command(site, f"/checkin {GROUP}", OTHER)

    assert [message.text for message in site.sent] == [FORBIDDEN]
    assert site.sent[0].chat_id == OTHER.user_id
    assert checkins(site) == []


@pytest.mark.parametrize(
    "text", [f"/checkin {GROUP}", "/checkin", "/checkin_close", "/checkin_report"]
)
def test_without_the_teachers_id_no_command_works(
    bot_site_factory: BotSiteFactory, text: str
) -> None:
    site = bot_site_factory(messenger=Telegram())
    add_checkin(site)

    checkin_command(site, text)

    assert [message.text for message in site.sent] == [FORBIDDEN]
    [row] = checkins(site)
    assert row.closes_at == NOW + timedelta(minutes=20)  # nothing was closed or opened


@pytest.mark.parametrize("text", ["/checkin_close", "/checkin_report"])
def test_another_person_cannot_close_or_read(site: BotSite, text: str) -> None:
    add_checkin(site)

    checkin_command(site, text, OTHER)

    assert [message.text for message in site.sent] == [FORBIDDEN]


def test_a_second_check_in_of_the_group_is_not_opened(site: BotSite) -> None:
    checkin_command(site, f"/checkin {GROUP}")
    [first] = checkins(site)
    site.forget()

    checkin_command(site, f"/checkin {GROUP} 30")

    assert [message.text for message in site.sent] == [already_open(first)]
    assert len(checkins(site)) == 1


def test_check_ins_of_different_groups_are_open_together(site: BotSite) -> None:
    checkin_command(site, f"/checkin {GROUP}")
    checkin_command(site, f"/checkin {OTHER_GROUP}")

    first, second = checkins(site)
    assert (first.group_code, second.group_code) == (GROUP, OTHER_GROUP)
    assert first.code != second.code
    assert site.sent[-1].text == opened(second)


def test_a_closed_check_in_does_not_stand_in_the_way(site: BotSite) -> None:
    add_checkin(site, "AB23", GROUP, opened_at=NOW - timedelta(hours=2))

    checkin_command(site, f"/checkin {GROUP}")

    assert len(checkins(site)) == 2


def test_a_failed_post_does_not_cancel_the_check_in(
    bot_site_factory: BotSiteFactory,
) -> None:
    telegram = Telegram(failures={"send_message": [MessengerUnavailable()]})
    site = bot_site_factory(messenger=telegram, **TEACHER_ENV)

    checkin_command(site, f"/checkin {GROUP}")

    [row] = checkins(site)
    [reply] = site.sent  # the post failed, so only the answer is recorded
    assert reply.chat_id == TEACHER.user_id
    assert reply.text == opened(row, posted=False)
    assert row.code in reply.text and link(row.code) in reply.text


# --- the choice of a group --------------------------------------------------------------------


def test_checkin_alone_offers_the_known_groups_two_in_a_row(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    member = participant_factory("one@example.com")
    add_checkin(site, "AB23", "old-group", opened_at=NOW - timedelta(days=30))
    add_member(site, member.id, "member-group", NOW - timedelta(days=10))
    add_checkin(site, "CD34", GROUP, opened_at=NOW - timedelta(days=1))
    add_checkin(site, "EF45", None, opened_at=NOW - timedelta(minutes=5))  # no group, no button

    checkin_command(site, "/checkin")

    [message] = site.sent
    assert message.chat_id == TEACHER.user_id and message.text == CHOOSE
    rows = [[button.text for button in row] for row in message.buttons]
    assert rows == [[GROUP, "member-group"], ["old-group"]]
    assert [button.callback_data for button in buttons(message)] == [
        f"open:{GROUP}",
        "open:member-group",
        "open:old-group",
    ]


def test_at_most_eight_groups_are_offered(site: BotSite) -> None:
    for number in range(12):
        opened_at = NOW - timedelta(days=number)
        add_checkin(site, f"A{number:03d}"[:4], f"group-{number:02d}", opened_at=opened_at)

    checkin_command(site, "/checkin")

    [message] = site.sent
    assert [button.text for button in buttons(message)] == [f"group-{n:02d}" for n in range(8)]


def test_without_known_groups_the_usage_is_given(site: BotSite) -> None:
    checkin_command(site, "/checkin")

    assert [message.text for message in site.sent] == [USAGE]


def test_the_button_of_a_group_opens_its_check_in_like_the_command(site: BotSite) -> None:
    add_checkin(site, "AB23", GROUP, opened_at=NOW - timedelta(days=7))

    response = site.post(callback_update(TEACHER, f"open:{GROUP}"))

    assert response.status_code == 200
    first, second = checkins(site)
    assert second.group_code == GROUP
    assert second.closes_at - second.opened_at == timedelta(minutes=10)
    assert [message.text for message in site.sent] == [post(GROUP, 10), opened(second)]
    assert len(site.messenger.answered) == 1  # the spinner of the button stops


def test_the_button_of_a_group_is_for_the_teacher_only(site: BotSite) -> None:
    response = site.post(callback_update(OTHER, f"open:{GROUP}"))

    assert response.status_code == 200
    assert checkins(site) == []
    assert site.sent == []
    assert site.messenger.answered[0][1] == FORBIDDEN


def test_the_button_of_a_group_does_nothing_without_the_teachers_id(
    bot_site_factory: BotSiteFactory,
) -> None:
    site = bot_site_factory(messenger=Telegram())

    site.post(callback_update(TEACHER, f"open:{GROUP}"))

    assert checkins(site) == []
    assert site.messenger.answered[0][1] == FORBIDDEN


# --- closing and the report -------------------------------------------------------------------


def test_close_ends_the_window_of_the_group_now(
    site: BotSite, participant_factory: ParticipantFactory
) -> None:
    other = add_checkin(site, "CD34", OTHER_GROUP, opened_at=NOW - timedelta(minutes=1))
    row = add_checkin(site, "AB23", GROUP)
    add_mark(site, row.id, participant_factory("one@example.com").id)
    add_mark(site, row.id, participant_factory("two@example.com").id, source="telegram")
    site.clock.advance(timedelta(minutes=5))

    checkin_command(site, f"/checkin_close {GROUP}")

    by_id = {item.id: item for item in checkins(site)}
    assert by_id[row.id].closes_at == NOW + timedelta(minutes=5)
    assert by_id[other.id].closes_at == other.closes_at  # another group stays open
    assert [message.text for message in site.sent] == [closed(row, "19:05", 2)]


def test_close_without_a_group_closes_the_latest_open_one(site: BotSite) -> None:
    older = add_checkin(site, "AB23", GROUP, opened_at=NOW - timedelta(minutes=2))
    latest = add_checkin(site, "CD34", OTHER_GROUP, opened_at=NOW - timedelta(minutes=1))

    checkin_command(site, "/checkin_close")

    by_id = {item.id: item for item in checkins(site)}
    assert by_id[latest.id].closes_at == NOW
    assert by_id[older.id].closes_at == older.closes_at
    assert [message.text for message in site.sent] == [closed(latest, "19:00", 0)]


def test_close_says_when_nothing_is_open(site: BotSite) -> None:
    add_checkin(site, "AB23", GROUP, opened_at=NOW - timedelta(hours=1))

    checkin_command(site, "/checkin_close")
    checkin_command(site, f"/checkin_close {GROUP}")
    checkin_command(site, "/checkin_close ГРУПА")

    assert [message.text for message in site.sent] == [NO_OPEN] * 3


def test_report_says_when_there_is_nothing(site: BotSite) -> None:
    checkin_command(site, "/checkin_report")
    checkin_command(site, f"/checkin_report {GROUP}")

    assert [message.text for message in site.sent] == [NO_CHECKINS] * 2


def test_an_unknown_group_has_no_report(site: BotSite) -> None:
    add_checkin(site, "AB23", GROUP)

    checkin_command(site, f"/checkin_report {OTHER_GROUP}")

    assert [message.text for message in site.sent] == [NO_CHECKINS]

