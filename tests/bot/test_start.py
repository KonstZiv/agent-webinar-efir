"""``/start`` with and without a token: the rules of docs/requirements.md, section 7, in order.

1. unknown or expired token; 2. a used ``screen`` token; 3. the same link; 4. a new link;
5. a conflict — an ``email`` token moves the link, a ``screen`` token is refused. After a link
or a move the bot checks the subscription at once (docs/copy.md, section 8). A token counts as
used when it made or confirmed a link: a refusal leaves it as it was.
"""

from datetime import timedelta

import pytest
from sqlalchemy import Engine

from app.adapters.db.participants import SqlParticipantStore
from app.core.entities import LinkSource, Participant, TelegramAccount
from app.services import PARTICIPANTS, override
from tests.bot.conftest import BotSiteFactory
from tests.bot.helpers import (
    EXPIRED,
    LINK_USED,
    MATERIALS,
    MEMBER,
    NOT_SUBSCRIBED,
    OTHER,
    REGISTRATION_TAKEN,
    TELEGRAM_TAKEN,
    TRANSFERRED,
    USER,
    WELCOME,
    BotSite,
    expected,
)
from tests.conftest import ParticipantFactory
from tests.factories import REGISTERED_AT

SOURCES: list[LinkSource] = ["screen", "email"]


def token_of(created: object) -> str:
    tokens: tuple[str, ...] = created.link_tokens  # type: ignore[attr-defined]
    return tokens[0]


# --- 1. unknown or expired -----------------------------------------------------------------


@pytest.mark.parametrize("payload", ["unknown-token", "x" * 64, "bad token!", "x" * 65, "тoken"])
def test_1_an_unknown_token(bot_site: BotSite, payload: str) -> None:
    bot_site.start(USER, payload)

    assert bot_site.said() == expected(EXPIRED)
    assert bot_site.sent[0].buttons == ()
    assert bot_site.linked() == {}


@pytest.mark.parametrize("source", SOURCES)
def test_1_an_expired_token(
    bot_site: BotSite, participant_factory: ParticipantFactory, source: LinkSource
) -> None:
    created = participant_factory(link_tokens=(source,))
    token = token_of(created)
    expires_at = bot_site.link_token(token).expires_at
    bot_site.clock.advance(expires_at - bot_site.clock.now())  # the very moment it expires

    bot_site.start(USER, token)

    assert bot_site.said() == expected(EXPIRED)
    assert bot_site.linked() == {}
    assert bot_site.link_token(token).used_at is None


def test_1_a_token_whose_participant_left_in_between(
    bot_site_factory: BotSiteFactory,
    participant_factory: ParticipantFactory,
    migrated_engine: Engine,
) -> None:
    """The token was found, then the participant unsubscribed before the bot read them."""

    class Unsubscribed(SqlParticipantStore):
        def by_id(self, participant_id: int) -> Participant | None:
            return None

    site = bot_site_factory(overrides=[override(PARTICIPANTS, Unsubscribed(migrated_engine))])
    created = participant_factory(link_tokens=("email",))

    site.start(USER, token_of(created))

    assert site.said() == expected(EXPIRED)
    assert site.linked() == {}


# --- 2. a used screen token ----------------------------------------------------------------


def test_2_its_own_user_gets_the_check_again(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(link_tokens=("screen",))
    token = token_of(created)
    bot_site.start(USER, token)
    bot_site.forget()

    bot_site.start(USER, token)

    assert bot_site.said() == expected(NOT_SUBSCRIBED)
    assert bot_site.linked() == {USER.user_id: created.id}


def test_2_another_user_is_refused(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(link_tokens=("screen",))
    token = token_of(created)
    bot_site.start(USER, token)
    used_at = bot_site.link_token(token).used_at
    bot_site.forget()

    bot_site.start(OTHER, token)

    assert bot_site.said() == expected(LINK_USED)
    assert bot_site.linked() == {USER.user_id: created.id}
    row = bot_site.link_token(token)
    assert (row.used_at, row.used_by_tg_user_id) == (used_at, USER.user_id)


# --- 3. the same link ----------------------------------------------------------------------


@pytest.mark.parametrize("source", SOURCES)
def test_3_a_registration_linked_to_this_telegram_gets_the_check(
    bot_site: BotSite, participant_factory: ParticipantFactory, source: LinkSource
) -> None:
    bot_site.messenger.members = {USER.user_id: MEMBER}
    created = participant_factory(telegram=USER, link_tokens=(source,))

    bot_site.start(USER, token_of(created))

    assert bot_site.said() == expected(MATERIALS)
    row = bot_site.participant(created.id)
    assert (row.tg_user_id, row.tg_linked_at, row.channel_member) == (
        USER.user_id,
        REGISTERED_AT,
        True,
    )
    token = bot_site.link_token(token_of(created))
    assert (token.used_at, token.used_by_tg_user_id) == (bot_site.clock.now(), USER.user_id)


# --- 4. a new link -------------------------------------------------------------------------


@pytest.mark.parametrize("source", SOURCES)
def test_4_a_free_registration_and_a_free_telegram_are_linked(
    bot_site: BotSite, participant_factory: ParticipantFactory, source: LinkSource
) -> None:
    created = participant_factory(link_tokens=(source,))

    response = bot_site.start(USER, token_of(created))

    assert response.status_code == 200
    assert bot_site.said() == expected(NOT_SUBSCRIBED)
    row = bot_site.participant(created.id)
    assert (row.tg_user_id, row.tg_username, row.tg_linked_at, row.channel_member) == (
        USER.user_id,
        USER.username,
        bot_site.clock.now(),
        False,
    )
    token = bot_site.link_token(token_of(created))
    assert (token.used_at, token.used_by_tg_user_id) == (bot_site.clock.now(), USER.user_id)


def test_4_an_account_without_a_username(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(link_tokens=("screen",))

    bot_site.start(TelegramAccount(USER.user_id), token_of(created))

    row = bot_site.participant(created.id)
    assert (row.tg_user_id, row.tg_username) == (USER.user_id, None)


def test_4_a_subscribed_person_gets_the_materials_right_away(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    bot_site.messenger.members = {USER.user_id: MEMBER}
    created = participant_factory(link_tokens=("screen",))

    bot_site.start(USER, token_of(created))

    assert bot_site.said() == expected(MATERIALS)
    assert bot_site.participant(created.id).channel_member is True


# --- 5. a conflict -------------------------------------------------------------------------


def test_5_an_email_token_moves_the_registration_from_another_telegram(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(telegram=OTHER, channel_member=True, link_tokens=("email",))

    bot_site.start(USER, token_of(created))

    assert bot_site.said() == expected(TRANSFERRED, NOT_SUBSCRIBED)
    row = bot_site.participant(created.id)
    assert (row.tg_user_id, row.tg_username, row.tg_linked_at, row.channel_member) == (
        USER.user_id,
        USER.username,
        bot_site.clock.now(),
        False,
    )
    assert bot_site.linked() == {USER.user_id: created.id}


def test_5_an_email_token_moves_this_telegram_from_another_registration(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    bot_site.messenger.members = {USER.user_id: MEMBER}
    before = participant_factory(telegram=USER, channel_member=True)
    created = participant_factory(link_tokens=("email",))

    bot_site.start(USER, token_of(created))

    assert bot_site.said() == expected(TRANSFERRED, MATERIALS)
    old = bot_site.participant(before.id)
    assert (old.tg_user_id, old.tg_username, old.tg_linked_at, old.channel_member) == (
        None,
        None,
        None,
        None,
    )
    assert bot_site.linked() == {USER.user_id: created.id}
    token = bot_site.link_token(token_of(created))
    assert token.used_by_tg_user_id == USER.user_id


def test_5_a_screen_token_of_a_registration_linked_to_another_telegram_is_refused(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(telegram=OTHER, link_tokens=("screen",))

    bot_site.start(USER, token_of(created))

    assert bot_site.said() == expected(REGISTRATION_TAKEN)
    assert bot_site.linked() == {OTHER.user_id: created.id}
    assert bot_site.link_token(token_of(created)).used_at is None


def test_5_a_screen_token_for_a_telegram_linked_to_another_registration_is_refused(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    before = participant_factory(telegram=USER)
    created = participant_factory(link_tokens=("screen",))

    bot_site.start(USER, token_of(created))

    assert bot_site.said() == expected(TELEGRAM_TAKEN)
    assert bot_site.linked() == {USER.user_id: before.id}
    assert bot_site.link_token(token_of(created)).used_at is None


def test_5_with_both_conflicts_a_screen_token_names_the_registration(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    before = participant_factory(telegram=USER)
    created = participant_factory(telegram=OTHER, link_tokens=("screen",))

    bot_site.start(USER, token_of(created))

    assert bot_site.said() == expected(REGISTRATION_TAKEN)
    assert bot_site.linked() == {USER.user_id: before.id, OTHER.user_id: created.id}


def test_a_refused_screen_token_still_links_once_the_conflict_is_gone(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    """A refusal does not use the token up."""
    before = participant_factory(telegram=USER, link_tokens=("email",))
    created = participant_factory(link_tokens=("screen",))
    bot_site.start(USER, token_of(created))  # refused: USER is linked to ``before``
    bot_site.start(OTHER, token_of(before))  # the email link of ``before`` takes it to OTHER
    bot_site.forget()

    bot_site.start(USER, token_of(created))

    assert bot_site.said() == expected(NOT_SUBSCRIBED)
    assert bot_site.linked() == {OTHER.user_id: before.id, USER.user_id: created.id}
    assert bot_site.link_token(token_of(created)).used_by_tg_user_id == USER.user_id


def test_an_email_token_works_for_its_whole_term(
    bot_site: BotSite, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(link_tokens=("email",))
    token = token_of(created)
    bot_site.start(USER, token)
    first_use = bot_site.clock.now()
    bot_site.clock.advance(timedelta(days=1))

    bot_site.start(OTHER, token)
    bot_site.clock.advance(timedelta(days=1))
    bot_site.start(USER, token)

    assert bot_site.linked() == {USER.user_id: created.id}
    row = bot_site.link_token(token)
    assert (row.used_at, row.used_by_tg_user_id) == (first_use, USER.user_id)


# --- /start without a token ----------------------------------------------------------------


def test_start_without_a_token_from_an_unlinked_telegram(bot_site: BotSite) -> None:
    bot_site.start(USER)

    assert bot_site.said() == expected(WELCOME)
    assert bot_site.linked() == {}


@pytest.mark.parametrize(
    ("member", "situation"), [(MEMBER, MATERIALS), (None, NOT_SUBSCRIBED)], ids=["member", "left"]
)
def test_start_without_a_token_from_a_linked_telegram_checks(
    bot_site: BotSite,
    participant_factory: ParticipantFactory,
    member: object,
    situation: str,
) -> None:
    if member is not None:
        bot_site.messenger.members = {USER.user_id: MEMBER}
    participant_factory(telegram=USER)

    bot_site.start(USER)

    assert bot_site.said() == expected(situation)
