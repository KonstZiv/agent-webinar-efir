"""The channel check: ``getChatMember`` to ``TELEGRAM_CHANNEL`` (docs/requirements.md, section 7).

Subscribed: ``member``, ``administrator``, ``creator``, and ``restricted`` with ``is_member``.
The result goes to ``channel_member``. If Telegram fails, the bot says it could not check and
offers the button. The button «Перевірити ще раз» checks again and never links anyone.
"""

import pytest

from app.core.bot.dialog import is_subscribed
from app.core.bot.ports import MessengerRateLimited
from app.core.bot.replies import RECHECK
from app.core.entities import ChatMember
from app.core.ports import MessengerUnavailable
from tests.bot.conftest import BotSiteFactory
from tests.bot.helpers import (
    CHANNEL,
    CHANNEL_URL,
    CHECK_FAILED,
    COPY,
    LEFT,
    MATERIALS,
    MATERIALS_URL,
    MEMBER,
    NOT_SUBSCRIBED,
    STILL_NOT_SUBSCRIBED,
    TRANSFERRED,
    USER,
    WELCOME,
    BotSite,
    Telegram,
    buttons,
    expected,
)
from tests.conftest import ParticipantFactory

STATUSES = [
    (ChatMember("member"), True),
    (ChatMember("administrator"), True),
    (ChatMember("creator"), True),
    (ChatMember("restricted", True), True),
    (ChatMember("restricted", False), False),
    (ChatMember("restricted"), False),
    (ChatMember("left"), False),
    (ChatMember("kicked"), False),
]


def ids(item: object) -> str:
    if isinstance(item, ChatMember):
        return item.status + ("" if item.is_member is None else f"-{item.is_member}")
    return str(item)


@pytest.mark.parametrize(("member", "subscribed"), STATUSES, ids=ids)
def test_who_counts_as_subscribed(member: ChatMember, subscribed: bool) -> None:
    assert is_subscribed(member) is subscribed


@pytest.mark.parametrize(("member", "subscribed"), STATUSES, ids=ids)
def test_the_check_answers_and_stores_its_result(
    bot_site: BotSite,
    participant_factory: ParticipantFactory,
    member: ChatMember,
    subscribed: bool,
) -> None:
    bot_site.messenger.members = {USER.user_id: member}
    created = participant_factory(telegram=USER)

    bot_site.start(USER)

    assert bot_site.said() == expected(MATERIALS if subscribed else NOT_SUBSCRIBED)
    assert bot_site.participant(created.id).channel_member is subscribed


def test_the_check_asks_about_the_channel_of_the_settings(
    bot_site_factory: BotSiteFactory, participant_factory: ParticipantFactory
) -> None:
    telegram = Telegram()
    site = bot_site_factory(messenger=telegram)
    participant_factory(telegram=USER)

    site.start(USER)

    assert telegram.channels == [CHANNEL]


def test_the_materials_come_as_a_link_and_a_button(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    bot_site.messenger.members = {USER.user_id: MEMBER}
    participant_factory(telegram=USER)

    bot_site.start(USER)

    [message] = bot_site.sent
    assert MATERIALS_URL in message.text
    [button] = buttons(message)
    assert (button.text, button.url, button.callback_data) == (
        COPY[MATERIALS].buttons[0],
        MATERIALS_URL,
        None,
    )


def test_the_unsubscribed_get_the_channel_and_the_button(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    participant_factory(telegram=USER)

    bot_site.start(USER)

    [message] = bot_site.sent
    channel, again = buttons(message)
    assert (channel.url, channel.callback_data) == (CHANNEL_URL, None)
    assert (again.url, again.callback_data) == (None, RECHECK)


def test_checking_again_while_still_unsubscribed(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(telegram=USER)

    response = bot_site.recheck(USER)

    assert response.status_code == 200
    assert bot_site.said() == expected(STILL_NOT_SUBSCRIBED)
    assert len(bot_site.messenger.answered) == 1
    assert bot_site.participant(created.id).channel_member is False


def test_checking_again_after_subscribing(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(telegram=USER, channel_member=False)
    bot_site.messenger.members = {USER.user_id: MEMBER}

    bot_site.recheck(USER)

    assert bot_site.said() == expected(MATERIALS)
    assert bot_site.participant(created.id).channel_member is True


def test_checking_again_after_leaving_the_channel(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(telegram=USER, channel_member=True)
    bot_site.messenger.members = {USER.user_id: LEFT}

    bot_site.recheck(USER)

    assert bot_site.participant(created.id).channel_member is False


def test_the_button_never_links(bot_site: BotSite, participant_factory: ParticipantFactory) -> None:
    """Even with a fresh link of the screen waiting: only /start with it links."""
    participant_factory(link_tokens=("screen", "email"))

    bot_site.recheck(USER)

    assert bot_site.said() == expected(WELCOME)
    assert bot_site.linked() == {}


@pytest.mark.parametrize(
    "error", [MessengerUnavailable(), MessengerRateLimited()], ids=["failure", "429"]
)
def test_a_failed_check_says_so_and_stores_nothing(
    bot_site_factory: BotSiteFactory, participant_factory: ParticipantFactory, error: Exception
) -> None:
    site = bot_site_factory(messenger=Telegram(failures={"channel_member": [error]}))
    created = participant_factory(telegram=USER, channel_member=True)

    response = site.start(USER)

    assert response.status_code == 200
    assert site.said() == expected(CHECK_FAILED)
    [again] = buttons(site.sent[0])
    assert (again.url, again.callback_data) == (None, RECHECK)
    assert site.participant(created.id).channel_member is True


def test_a_failed_answer_to_the_button_still_checks(
    bot_site_factory: BotSiteFactory, participant_factory: ParticipantFactory
) -> None:
    site = bot_site_factory(
        messenger=Telegram(failures={"answer_callback": [MessengerRateLimited()]})
    )
    participant_factory(telegram=USER)

    assert site.recheck(USER).status_code == 200
    assert site.said() == expected(STILL_NOT_SUBSCRIBED)


def test_without_the_materials_page_the_subscribed_are_asked_to_check_later(
    bot_site_factory: BotSiteFactory, participant_factory: ParticipantFactory
) -> None:
    """Operator's decision: no ``MATERIALS_SLUG``, no link to a 404; the button works later."""
    site = bot_site_factory(MATERIALS_SLUG=None)
    site.messenger.members = {USER.user_id: MEMBER}
    created = participant_factory(telegram=USER)

    site.start(USER)

    assert site.said() == expected(CHECK_FAILED)
    assert "/m/" not in site.sent[0].text
    assert site.participant(created.id).channel_member is True


# --- 429 on a message: Telegram delivers the update again ----------------------------------


def test_429_on_the_second_message_of_a_move_is_503_and_the_retry_only_checks(
    bot_site_factory: BotSiteFactory, participant_factory: ParticipantFactory
) -> None:
    telegram = Telegram(failures={"send_message": [None, MessengerRateLimited()]})
    site = bot_site_factory(messenger=telegram)
    participant_factory(telegram=USER)
    created = participant_factory(link_tokens=("email",))
    update_payload = created.link_tokens[0]

    assert site.start(USER, update_payload).status_code == 503
    assert site.said() == expected(TRANSFERRED)
    assert site.linked() == {USER.user_id: created.id}
    site.forget()

    assert site.start(USER, update_payload).status_code == 200  # Telegram's retry
    assert site.said() == expected(NOT_SUBSCRIBED)


def test_429_on_the_only_message_is_503_and_the_retry_answers(
    bot_site_factory: BotSiteFactory, participant_factory: ParticipantFactory
) -> None:
    telegram = Telegram(failures={"send_message": [MessengerRateLimited()]})
    site = bot_site_factory(messenger=telegram)
    created = participant_factory(link_tokens=("screen",))

    assert site.start(USER, created.link_tokens[0]).status_code == 503
    assert site.start(USER, created.link_tokens[0]).status_code == 200

    assert site.said() == expected(NOT_SUBSCRIBED)
    assert site.linked() == {USER.user_id: created.id}
