"""Concurrent ``/start``: one token or one Telegram never makes two links.

The deterministic tests hold the competing write in a transaction of their own, start the
request in a thread, wait until it waits for the lock (``wait_until_blocked``) and only then
commit: the order of events is fixed. A ``StorageConflict`` of a race is an answer to the
person, not an error. The last tests start real requests at once and check the invariant only.
"""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from sqlalchemy import Engine, text

from app.adapters.db.participants import SqlParticipantStore
from app.core.entities import LinkSource
from app.core.ports import StorageConflict
from app.services import PARTICIPANTS, override
from tests.bot.conftest import BotSiteFactory
from tests.bot.helpers import (
    COPY,
    LINK_USED,
    NOT_SUBSCRIBED,
    OTHER,
    REGISTRATION_TAKEN,
    TELEGRAM_TAKEN,
    TRANSFERRED,
    USER,
    BotSite,
    expected,
    said,
)
from tests.conftest import ParticipantFactory
from tests.database import wait_until_blocked


def while_held(
    engine: Engine, statement: str, params: dict[str, int], request: Callable[[], httpx.Response]
) -> httpx.Response:
    """Run ``request`` while another transaction holds ``statement``; commit once it waits."""
    with engine.connect() as competitor, ThreadPoolExecutor(1) as pool:
        competitor.execute(text(statement), params)
        pending = pool.submit(request)
        wait_until_blocked(engine)
        competitor.commit()
        return pending.result(timeout=10)


LINK = "UPDATE participants SET tg_user_id = :tg, tg_linked_at = now() WHERE id = :id"


@pytest.mark.parametrize("source", ["screen", "email"])
def test_one_telegram_for_two_registrations_at_once(
    bot_site: BotSite,
    participant_factory: ParticipantFactory,
    migrated_engine: Engine,
    source: LinkSource,
) -> None:
    """The other registration takes USER first; this link fails on the unique index."""
    winner = participant_factory()
    created = participant_factory(link_tokens=(source,))

    response = while_held(
        migrated_engine,
        LINK,
        {"tg": USER.user_id, "id": winner.id},
        lambda: bot_site.start(USER, created.link_tokens[0]),
    )

    assert response.status_code == 200
    if source == "screen":
        assert bot_site.said() == expected(TELEGRAM_TAKEN)
        assert bot_site.linked() == {USER.user_id: winner.id}
    else:  # the email link moves USER here
        assert bot_site.said() == expected(TRANSFERRED, NOT_SUBSCRIBED)
        assert bot_site.linked() == {USER.user_id: created.id}


def test_two_telegrams_with_one_screen_token_at_once(
    bot_site: BotSite, participant_factory: ParticipantFactory, migrated_engine: Engine
) -> None:
    """OTHER links the registration first; USER's link then finds it taken."""
    created = participant_factory(link_tokens=("screen",))

    response = while_held(
        migrated_engine,
        LINK,
        {"tg": OTHER.user_id, "id": created.id},
        lambda: bot_site.start(USER, created.link_tokens[0]),
    )

    assert response.status_code == 200
    assert bot_site.said() == expected(REGISTRATION_TAKEN)
    assert bot_site.linked() == {OTHER.user_id: created.id}
    assert bot_site.link_token(created.link_tokens[0]).used_at is None


@pytest.mark.parametrize("source", ["screen", "email"])
def test_a_double_click_links_once_and_checks_twice(
    bot_site: BotSite,
    participant_factory: ParticipantFactory,
    migrated_engine: Engine,
    source: LinkSource,
) -> None:
    """The first click links USER; the second one waits for it and then finds rule 3."""
    created = participant_factory(link_tokens=(source,))

    response = while_held(
        migrated_engine,
        LINK,
        {"tg": USER.user_id, "id": created.id},
        lambda: bot_site.start(USER, created.link_tokens[0]),
    )

    assert response.status_code == 200
    assert bot_site.said() == expected(NOT_SUBSCRIBED)
    assert bot_site.linked() == {USER.user_id: created.id}
    assert bot_site.link_token(created.link_tokens[0]).used_by_tg_user_id == USER.user_id


def test_a_move_that_loses_a_race_is_an_answer(
    bot_site_factory: BotSiteFactory,
    participant_factory: ParticipantFactory,
    migrated_engine: Engine,
) -> None:
    """Two email links move one Telegram at once: the loser hears where the account went."""

    class Racing(SqlParticipantStore):
        def transfer_telegram(self, *args: object) -> bool:
            raise StorageConflict("transfer telegram")

    site = bot_site_factory(overrides=[override(PARTICIPANTS, Racing(migrated_engine))])
    participant_factory(telegram=USER)
    created = participant_factory(link_tokens=("email",))

    response = site.start(USER, created.link_tokens[0])

    assert response.status_code == 200
    assert site.said() == expected(TELEGRAM_TAKEN)
    assert site.link_token(created.link_tokens[0]).used_at is None


# --- real concurrency: the invariant holds whatever the order ------------------------------


def at_once(*requests: Callable[[], httpx.Response]) -> list[httpx.Response]:
    barrier = threading.Barrier(len(requests))

    def run(request: Callable[[], httpx.Response]) -> httpx.Response:
        barrier.wait(timeout=5)
        return request()

    with ThreadPoolExecutor(len(requests)) as pool:
        return [future.result(timeout=20) for future in [pool.submit(run, r) for r in requests]]


@pytest.mark.parametrize("attempt", range(3))
def test_two_telegrams_with_one_screen_token_really_at_once(
    bot_site: BotSite, participant_factory: ParticipantFactory, attempt: int
) -> None:
    created = participant_factory(link_tokens=("screen",))
    token = created.link_tokens[0]

    responses = at_once(lambda: bot_site.start(USER, token), lambda: bot_site.start(OTHER, token))

    assert [response.status_code for response in responses] == [200, 200]
    linked = bot_site.linked()
    assert list(linked.values()) == [created.id]
    winner = next(iter(linked))
    loser = OTHER.user_id if winner == USER.user_id else USER.user_id
    by_chat = {message.chat_id: message.text for message in bot_site.sent}
    assert by_chat[winner] == COPY[NOT_SUBSCRIBED].text
    assert by_chat[loser] in expected(REGISTRATION_TAKEN, LINK_USED)


@pytest.mark.parametrize("source", ["screen", "email"])
def test_one_telegram_for_two_registrations_really_at_once(
    bot_site: BotSite, participant_factory: ParticipantFactory, source: LinkSource
) -> None:
    first = participant_factory(link_tokens=(source,))
    second = participant_factory(link_tokens=(source,))

    responses = at_once(
        lambda: bot_site.start(USER, first.link_tokens[0]),
        lambda: bot_site.start(USER, second.link_tokens[0]),
    )

    assert [response.status_code for response in responses] == [200, 200]
    linked = bot_site.linked()
    assert list(linked) == [USER.user_id]
    assert linked[USER.user_id] in (first.id, second.id)
    allowed = expected(NOT_SUBSCRIBED, TELEGRAM_TAKEN, TRANSFERRED)
    assert [text for text in said(bot_site.sent) if text not in allowed] == []
