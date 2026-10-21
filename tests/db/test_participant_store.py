"""``SqlParticipantStore``: data operations on the shared table of participants.

The rules (who may register, when a Telegram link moves) belong to the slices; the store keeps
the data consistent: one row per address, one participant per Telegram account.
"""

import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.exc import OperationalError

from app.adapters.db.engine import make_engine
from app.adapters.db.participants import SqlParticipantStore
from app.core.entities import NewParticipant, TelegramAccount, TrafficSource
from app.core.ports import StorageConflict, StorageUnavailable
from tests.conftest import ParticipantFactory
from tests.database import wait_until_blocked

NOW = datetime(2026, 10, 20, 17, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 21, 9, 30, tzinfo=UTC)


@pytest.fixture
def store(migrated_engine: Engine) -> SqlParticipantStore:
    return SqlParticipantStore(migrated_engine)


def new(email: str = "visitor@example.com", **fields: object) -> NewParticipant:
    values: dict[str, object] = {
        "email": email,
        "unsubscribe_id": uuid.uuid4(),
        "registered_at": NOW,
        "consent_version": "consent-v1",
        "consent_at": NOW,
        **fields,
    }
    return NewParticipant(**values)  # type: ignore[arg-type]


def count(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


@contextmanager
def v1_holds_key_share(engine: Engine, participant_id: int) -> Iterator[None]:
    """What v1 holds on a participant while it claims their email (``SELECT … FOR KEY SHARE``)."""
    with engine.connect() as v1:
        v1.execute(
            text("SELECT id FROM participants WHERE id = :id FOR KEY SHARE"), {"id": participant_id}
        )
        yield
        v1.rollback()


# --- registering ---------------------------------------------------------------------------


def test_a_new_participant_is_stored_with_origin_v2(store: SqlParticipantStore) -> None:
    source = TrafficSource(utm_source="telegram", gclid="abc", landing_url="https://x.example.com/")

    participant, created = store.add_if_absent(new(source=source, ga_client_id="123.456"))

    assert created is True
    assert participant.email == "visitor@example.com"
    assert participant.origin == "v2"
    assert participant.registered_at == NOW
    assert participant.telegram is None
    assert store.by_email("visitor@example.com") == participant


def test_a_repeat_returns_the_first_row_unchanged(
    store: SqlParticipantStore, migrated_engine: Engine
) -> None:
    first, _ = store.add_if_absent(new(source=TrafficSource(utm_source="first")))

    again, created = store.add_if_absent(
        new(source=TrafficSource(utm_source="second"), registered_at=LATER)
    )

    assert (again, created) == (first, False)
    with migrated_engine.connect() as connection:
        utm = connection.execute(text("SELECT utm_source FROM participants")).scalar_one()
    assert utm == "first"


def test_a_v1_row_stays_a_v1_row(
    store: SqlParticipantStore, participant_factory: ParticipantFactory
) -> None:
    participant_factory("from-v1@example.com", origin=None)

    participant, created = store.add_if_absent(new("from-v1@example.com"))

    assert created is False
    assert participant.origin is None


def test_a_repeat_survives_an_unsubscribe_between_statements(
    store: SqlParticipantStore, participant_factory: ParticipantFactory, migrated_engine: Engine
) -> None:
    """The address is taken when the insert runs; an unsubscribe right after it must wait."""
    existing = participant_factory("visitor@example.com")
    unsubscribe: list[str] = []

    def unsubscribe_meanwhile(*args: object) -> None:
        statement = str(args[2])
        if unsubscribe or not statement.startswith("INSERT INTO participants"):
            return
        with migrated_engine.connect() as v1:
            v1.execute(text("SET lock_timeout = '200ms'"))
            try:
                v1.execute(text("DELETE FROM participants WHERE id = :id"), {"id": existing.id})
                v1.commit()
                unsubscribe.append("deleted the row")
            except OperationalError:
                unsubscribe.append("waited for the registration")

    event.listen(migrated_engine, "after_cursor_execute", unsubscribe_meanwhile)
    try:
        participant, created = store.add_if_absent(new("visitor@example.com"))
    finally:
        event.remove(migrated_engine, "after_cursor_execute", unsubscribe_meanwhile)

    assert (participant.id, created) == (existing.id, False)
    assert unsubscribe == ["waited for the registration"]


def test_v1_claiming_an_email_does_not_hold_up_a_repeat(
    store: SqlParticipantStore, participant_factory: ParticipantFactory, migrated_engine: Engine
) -> None:
    existing = participant_factory("visitor@example.com")

    with v1_holds_key_share(migrated_engine, existing.id):
        participant, created = store.add_if_absent(new("visitor@example.com"))

    assert (participant.id, created) == (existing.id, False)


def test_source_values_are_stored_cleaned(
    store: SqlParticipantStore, migrated_engine: Engine
) -> None:
    """A visitor's ``?utm_source=%00`` or a 600-character value never fails the registration."""
    source = TrafficSource(utm_source="tele\x00gram", referrer="https://x.example.com/" + "a" * 600)

    _, created = store.add_if_absent(new(source=source))

    assert created is True
    with migrated_engine.connect() as connection:
        utm, referrer = connection.execute(
            text("SELECT utm_source, referrer FROM participants")
        ).one()
    assert (utm, len(referrer)) == ("telegram", 500)


# --- finding -------------------------------------------------------------------------------


def test_finding_by_each_key(
    store: SqlParticipantStore, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(
        "found@example.com", telegram=TelegramAccount(42, "found_user"), level="middle"
    )

    by_id = store.by_id(created.id)
    assert by_id is not None
    assert by_id.telegram == TelegramAccount(42, "found_user")
    assert by_id.level == "middle"
    assert store.by_email("found@example.com") == by_id
    assert store.by_unsubscribe_id(created.unsubscribe_id) == by_id
    assert store.by_telegram(42) == by_id


def test_unknown_keys_find_nothing(store: SqlParticipantStore) -> None:
    assert store.by_id(1) is None
    assert store.by_email("nobody@example.com") is None
    assert store.by_unsubscribe_id(uuid.uuid4()) is None
    assert store.by_telegram(42) is None


# --- unsubscribing -------------------------------------------------------------------------


def test_removing_deletes_every_row_of_the_participant(
    store: SqlParticipantStore,
    participant_factory: ParticipantFactory,
    migrated_engine: Engine,
) -> None:
    leaving = participant_factory(
        emails={"lesson_invitation": "sent"}, link_tokens=["email"], clicks=["lesson"]
    )
    staying = participant_factory(emails={"confirmation": "sent"})

    assert store.remove_by_unsubscribe_id(leaving.unsubscribe_id) is True
    assert store.remove_by_unsubscribe_id(leaving.unsubscribe_id) is False

    assert store.by_id(leaving.id) is None
    assert store.by_id(staying.id) is not None
    assert [count(migrated_engine, t) for t in ("emails", "link_tokens", "clicks")] == [1, 0, 0]


# --- Telegram ------------------------------------------------------------------------------
#
# Linking a free account and moving a link are separate operations with their conditions in the
# statements: the bot's rules hold even when two updates arrive at once.


def test_linking_a_free_account_to_a_free_registration(
    store: SqlParticipantStore, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory()

    assert store.link_telegram_if_free(created.id, TelegramAccount(7, "seven"), NOW) is True

    participant = store.by_id(created.id)
    assert participant is not None
    assert (participant.telegram, participant.telegram_linked_at, participant.channel_member) == (
        TelegramAccount(7, "seven"),
        NOW,
        None,
    )


def test_an_account_of_another_registration_is_not_linked(
    store: SqlParticipantStore, participant_factory: ParticipantFactory
) -> None:
    owner = participant_factory(telegram=TelegramAccount(7, "seven"), channel_member=True)
    other = participant_factory()

    assert store.link_telegram_if_free(other.id, TelegramAccount(7, "seven"), LATER) is False

    assert store.by_telegram(7) == store.by_id(owner.id)
    assert store.by_id(other.id).telegram is None  # type: ignore[union-attr]


def test_a_linked_registration_is_not_linked_again(
    store: SqlParticipantStore, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(telegram=TelegramAccount(7, "seven"))

    assert store.link_telegram_if_free(created.id, TelegramAccount(8), LATER) is False
    assert store.link_telegram_if_free(created.id, TelegramAccount(7, "renamed"), LATER) is False

    assert store.by_id(created.id).telegram == TelegramAccount(7, "seven")  # type: ignore[union-attr]
    assert store.by_telegram(8) is None


def test_linking_to_an_unknown_participant_changes_nothing(store: SqlParticipantStore) -> None:
    assert store.link_telegram_if_free(404, TelegramAccount(7), NOW) is False
    assert store.by_telegram(7) is None


def test_two_registrations_racing_for_one_account(
    store: SqlParticipantStore, participant_factory: ParticipantFactory, migrated_engine: Engine
) -> None:
    """Both saw the account free; the later one gets a conflict, not «database unavailable»."""
    first, second = participant_factory(), participant_factory()

    with migrated_engine.connect() as winner, ThreadPoolExecutor(1) as pool:
        winner.execute(
            text("UPDATE participants SET tg_user_id = 7 WHERE id = :id"), {"id": first.id}
        )
        loser = pool.submit(store.link_telegram_if_free, second.id, TelegramAccount(7), NOW)
        wait_until_blocked(migrated_engine)
        winner.commit()

        with pytest.raises(StorageConflict):
            loser.result(timeout=5)

    assert store.by_telegram(7) == store.by_id(first.id)


def test_a_transfer_moves_the_account_from_another_participant(
    store: SqlParticipantStore, participant_factory: ParticipantFactory
) -> None:
    """One Telegram account — one registration: the old link is cleared in the same step."""
    old = participant_factory(telegram=TelegramAccount(7, "seven"), channel_member=True)
    new_owner = participant_factory()

    assert store.transfer_telegram(new_owner.id, TelegramAccount(7, "seven"), LATER) is True

    previous = store.by_id(old.id)
    assert previous is not None
    assert (previous.telegram, previous.telegram_linked_at, previous.channel_member) == (
        None,
        None,
        None,
    )
    assert store.by_telegram(7) == store.by_id(new_owner.id)


def test_a_transfer_replaces_another_account_and_its_check(
    store: SqlParticipantStore, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(telegram=TelegramAccount(7, "seven"), channel_member=True)

    store.transfer_telegram(created.id, TelegramAccount(8, "eight"), LATER)

    participant = store.by_id(created.id)
    assert participant is not None
    assert participant.telegram == TelegramAccount(8, "eight")
    assert (participant.telegram_linked_at, participant.channel_member) == (LATER, None)
    assert store.by_telegram(7) is None


def test_a_transfer_of_the_same_account_keeps_the_link(
    store: SqlParticipantStore, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(telegram=TelegramAccount(7, "seven"), channel_member=True)
    linked_at = store.by_id(created.id).telegram_linked_at  # type: ignore[union-attr]

    store.transfer_telegram(created.id, TelegramAccount(7, "renamed"), LATER)

    participant = store.by_id(created.id)
    assert participant is not None
    assert participant.telegram == TelegramAccount(7, "renamed")
    assert (participant.telegram_linked_at, participant.channel_member) == (linked_at, True)


def test_a_transfer_to_an_unknown_participant_changes_nothing(
    store: SqlParticipantStore, participant_factory: ParticipantFactory
) -> None:
    owner = participant_factory(telegram=TelegramAccount(7))

    assert store.transfer_telegram(404, TelegramAccount(7), NOW) is False
    assert store.by_telegram(7) == store.by_id(owner.id)


def test_v1_claiming_an_email_does_not_hold_up_a_transfer(
    store: SqlParticipantStore, participant_factory: ParticipantFactory, migrated_engine: Engine
) -> None:
    """The transfer locks the participant FOR NO KEY UPDATE, which v1's FOR KEY SHARE allows."""
    created = participant_factory()

    with v1_holds_key_share(migrated_engine, created.id):
        assert store.transfer_telegram(created.id, TelegramAccount(7), NOW) is True


def test_channel_membership_is_stored_for_the_linked_account(
    store: SqlParticipantStore, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(telegram=TelegramAccount(7))

    assert store.set_channel_member(created.id, 7, True) is True
    first = store.by_id(created.id)
    assert store.set_channel_member(created.id, 7, False) is True
    second = store.by_id(created.id)

    assert (first.channel_member, second.channel_member) == (True, False)  # type: ignore[union-attr]


def test_membership_of_a_moved_account_stays_off_the_old_registration(
    store: SqlParticipantStore, participant_factory: ParticipantFactory
) -> None:
    """The check began before the transfer: its answer is about the account, not about P."""
    old = participant_factory(telegram=TelegramAccount(7))
    new_owner = participant_factory()
    store.transfer_telegram(new_owner.id, TelegramAccount(7), LATER)

    assert store.set_channel_member(old.id, 7, True) is False

    assert store.by_id(old.id).channel_member is None  # type: ignore[union-attr]


# --- failures ------------------------------------------------------------------------------


def test_an_unreachable_database_is_storage_unavailable() -> None:
    engine = make_engine("postgresql+psycopg://app@127.0.0.1:1/unreachable")
    try:
        with pytest.raises(StorageUnavailable):
            SqlParticipantStore(engine).by_email("visitor@example.com")
    finally:
        engine.dispose()
