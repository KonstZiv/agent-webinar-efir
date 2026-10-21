"""No personal data and nothing that gives access reaches the log (docs/requirements.md, 15).

Telegram ids, usernames, chat ids, link tokens, the bot token and the webhook secret stay out;
the log says the kind of update and its result instead of its body.
"""

import logging

import pytest

from app.core.ports import MessengerUnavailable
from tests.bot.conftest import BotSiteFactory
from tests.bot.helpers import BOT_TOKEN, OTHER, SECRET, USER, Telegram
from tests.conftest import ParticipantFactory


def test_the_log_of_a_whole_conversation_has_no_personal_data(
    bot_site_factory: BotSiteFactory,
    participant_factory: ParticipantFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    telegram = Telegram(
        failures={
            "channel_member": [None, MessengerUnavailable()],
            "send_message": [None, None, None, MessengerUnavailable()],
        }
    )
    site = bot_site_factory(messenger=telegram)
    screen = participant_factory(link_tokens=("screen",))
    email = participant_factory(telegram=OTHER, link_tokens=("email",))
    tokens = [*screen.link_tokens, *email.link_tokens]

    site.start(USER, screen.link_tokens[0])  # linked
    site.start(OTHER, screen.link_tokens[0])  # refused: used
    site.start(USER, email.link_tokens[0])  # moved; the check fails
    site.recheck(USER)
    site.start(OTHER)
    site.start(USER, "unknown-token-0123456789")

    logged = caplog.text
    for secret in (
        str(USER.user_id),
        str(OTHER.user_id),
        str(USER.username),
        str(OTHER.username),
        *tokens,
        "unknown-token-0123456789",
        BOT_TOKEN.split(":", 1)[1],
        SECRET,
    ):
        assert secret not in logged
    assert "Telegram update start_token:" in logged
