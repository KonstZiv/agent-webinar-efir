"""Text oracle of the bot: every message and button of docs/copy.md, section 8, word for word.

The oracle reads the table itself (``helpers.bot_copy``). Each situation of the table is made to
happen through the webhook, and the bot must send exactly its text, with ``{site_url}`` and
``{materials_url}`` filled in, and buttons with exactly the labels of the column «Кнопки».
"""

from collections.abc import Callable

import pytest

from app.core.ports import MessengerUnavailable
from tests.bot.conftest import BotSiteFactory
from tests.bot.helpers import (
    CHECK_FAILED,
    COPY,
    EXPIRED,
    LINK_USED,
    MATERIALS,
    MATERIALS_URL,
    MEMBER,
    NOT_SUBSCRIBED,
    OTHER,
    REGISTRATION_TAKEN,
    SITE_URL,
    STILL_NOT_SUBSCRIBED,
    TELEGRAM_TAKEN,
    TRANSFERRED,
    USER,
    WELCOME,
    BotSite,
    Telegram,
    labels,
)
from tests.conftest import ParticipantFactory

type Scene = Callable[[BotSite, ParticipantFactory], None]


def subscribed(site: BotSite, factory: ParticipantFactory) -> None:
    site.messenger.members = {USER.user_id: MEMBER}
    factory(telegram=USER)
    site.start(USER)


def not_subscribed(site: BotSite, factory: ParticipantFactory) -> None:
    created = factory(link_tokens=("screen",))
    site.start(USER, created.link_tokens[0])


def still_not_subscribed(site: BotSite, factory: ParticipantFactory) -> None:
    factory(telegram=USER)
    site.recheck(USER)


def check_failed(site: BotSite, factory: ParticipantFactory) -> None:
    assert isinstance(site.messenger, Telegram)
    site.messenger.failures["channel_member"] = [MessengerUnavailable()]
    factory(telegram=USER)
    site.start(USER)


def expired(site: BotSite, factory: ParticipantFactory) -> None:
    site.start(USER, "unknown-token")


def link_used(site: BotSite, factory: ParticipantFactory) -> None:
    created = factory(link_tokens=("screen",))
    site.start(OTHER, created.link_tokens[0])
    site.forget()
    site.start(USER, created.link_tokens[0])


def registration_taken(site: BotSite, factory: ParticipantFactory) -> None:
    created = factory(telegram=OTHER, link_tokens=("screen",))
    site.start(USER, created.link_tokens[0])


def telegram_taken(site: BotSite, factory: ParticipantFactory) -> None:
    factory(telegram=USER)
    created = factory(link_tokens=("screen",))
    site.start(USER, created.link_tokens[0])


def transferred(site: BotSite, factory: ParticipantFactory) -> None:
    created = factory(telegram=OTHER, link_tokens=("email",))
    site.start(USER, created.link_tokens[0])
    del site.sent[1:]  # the check that follows has its own row


def welcome(site: BotSite, factory: ParticipantFactory) -> None:
    site.start(USER)


SCENES: dict[str, Scene] = {
    MATERIALS: subscribed,
    NOT_SUBSCRIBED: not_subscribed,
    STILL_NOT_SUBSCRIBED: still_not_subscribed,
    CHECK_FAILED: check_failed,
    EXPIRED: expired,
    LINK_USED: link_used,
    REGISTRATION_TAKEN: registration_taken,
    TELEGRAM_TAKEN: telegram_taken,
    TRANSFERRED: transferred,
    WELCOME: welcome,
}


def test_every_row_of_the_table_has_a_scene() -> None:
    """A new situation in copy.md needs a test (and code) before this is green again."""
    assert sorted(COPY) == sorted(SCENES)


@pytest.mark.parametrize("situation", sorted(SCENES))
def test_the_bot_says_the_text_of_the_situation(
    bot_site_factory: BotSiteFactory, participant_factory: ParticipantFactory, situation: str
) -> None:
    site = bot_site_factory(messenger=Telegram())

    SCENES[situation](site, participant_factory)

    [message] = site.sent
    assert message.text == COPY[situation].text
    assert labels(message) == COPY[situation].buttons


def test_the_values_are_filled_in() -> None:
    assert MATERIALS_URL in COPY[MATERIALS].text
    assert SITE_URL in COPY[WELCOME].text
    assert all("{" not in expected.text for expected in COPY.values())
