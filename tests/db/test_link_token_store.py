"""``SqlLinkTokenStore``: personal links to the bot; the slices decide what a use means."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text

from app.adapters.db.engine import make_engine
from app.adapters.db.link_tokens import SqlLinkTokenStore
from app.core.entities import LinkToken
from app.core.ports import StorageConflict, StorageUnavailable
from tests.conftest import ParticipantFactory
from tests.database import wait_until_blocked

ISSUED = datetime(2026, 10, 20, 17, 0, tzinfo=UTC)
TOKEN = "Abc_def-0123456789abcdefghijklmnopqrstuv"
USED = ISSUED + timedelta(minutes=1)


@pytest.fixture
def store(migrated_engine: Engine) -> SqlLinkTokenStore:
    return SqlLinkTokenStore(migrated_engine)


def issued(participant_id: int, source: str = "screen") -> LinkToken:
    return LinkToken(
        token=TOKEN,
        participant_id=participant_id,
        source=source,  # type: ignore[arg-type]
        created_at=ISSUED,
        expires_at=ISSUED + timedelta(days=7),
    )


def test_a_token_is_stored_and_found(
    store: SqlLinkTokenStore, participant_factory: ParticipantFactory
) -> None:
    token = issued(participant_factory().id, "email")

    store.add(token)

    assert store.find(TOKEN) == token
    assert store.find("unknown-token") is None


def test_the_first_use_is_kept_and_the_latest_user_recorded(
    store: SqlLinkTokenStore, participant_factory: ParticipantFactory
) -> None:
    store.add(issued(participant_factory().id))
    first, second = ISSUED + timedelta(minutes=1), ISSUED + timedelta(hours=1)

    assert store.record_use(TOKEN, 7, first) is True
    assert store.record_use(TOKEN, 8, second) is True

    token = store.find(TOKEN)
    assert token is not None
    assert (token.used_at, token.used_by_tg_user_id) == (first, 8)


def test_using_an_unknown_token_changes_nothing(store: SqlLinkTokenStore) -> None:
    assert store.record_use("unknown-token", 7, ISSUED) is False


# --- single use: claim ---------------------------------------------------------------------
#
# A token from the success screen is used once: by its first user, again only by the same one.
# The condition is in the statement, so two /start at once cannot both take it.


def test_a_free_token_is_claimed(
    store: SqlLinkTokenStore, participant_factory: ParticipantFactory
) -> None:
    store.add(issued(participant_factory().id))

    assert store.claim(TOKEN, 7, USED) is True

    token = store.find(TOKEN)
    assert token is not None
    assert (token.used_at, token.used_by_tg_user_id) == (USED, 7)


def test_its_user_claims_it_again_and_the_first_use_stays(
    store: SqlLinkTokenStore, participant_factory: ParticipantFactory
) -> None:
    store.add(issued(participant_factory().id))
    store.claim(TOKEN, 7, USED)

    assert store.claim(TOKEN, 7, USED + timedelta(hours=1)) is True

    token = store.find(TOKEN)
    assert token is not None
    assert (token.used_at, token.used_by_tg_user_id) == (USED, 7)


def test_another_user_cannot_claim_it(
    store: SqlLinkTokenStore, participant_factory: ParticipantFactory
) -> None:
    store.add(issued(participant_factory().id))
    store.claim(TOKEN, 7, USED)

    assert store.claim(TOKEN, 8, USED + timedelta(minutes=1)) is False

    token = store.find(TOKEN)
    assert token is not None
    assert (token.used_at, token.used_by_tg_user_id) == (USED, 7)


def test_an_unknown_token_cannot_be_claimed(store: SqlLinkTokenStore) -> None:
    assert store.claim("unknown-token", 7, USED) is False


def test_two_users_claiming_at_once_get_it_once(
    store: SqlLinkTokenStore, participant_factory: ParticipantFactory, migrated_engine: Engine
) -> None:
    """The second claim waits for the first and then sees the token taken."""
    store.add(issued(participant_factory().id))

    with migrated_engine.connect() as first, ThreadPoolExecutor(1) as pool:
        first.execute(
            text("UPDATE link_tokens SET used_at = :at, used_by_tg_user_id = 7 WHERE token = :t"),
            {"at": USED, "t": TOKEN},
        )
        second = pool.submit(store.claim, TOKEN, 8, USED)
        wait_until_blocked(migrated_engine)
        first.commit()

        assert second.result(timeout=5) is False

    token = store.find(TOKEN)
    assert token is not None
    assert token.used_by_tg_user_id == 7


def test_a_token_of_a_removed_participant_is_a_conflict(store: SqlLinkTokenStore) -> None:
    """The participant unsubscribed meanwhile: bad data, not a database outage."""
    with pytest.raises(StorageConflict):
        store.add(issued(404))


def test_an_unreachable_database_is_storage_unavailable() -> None:
    engine = make_engine("postgresql+psycopg://app@127.0.0.1:1/unreachable")
    try:
        with pytest.raises(StorageUnavailable):
            SqlLinkTokenStore(engine).find(TOKEN)
    finally:
        engine.dispose()
