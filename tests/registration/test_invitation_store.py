"""The invitation's rows of ``emails`` on a real PostgreSQL (requirements, sections 6 and 10).

One ``lesson_invitation`` per participant: claiming inserts it or takes back a failed one, or a
``pending`` one older than 15 minutes by the database clock, unless its ``scheduled_at`` is still
ahead. The participant is read ``FOR KEY SHARE``, so an unsubscribe in flight finishes first;
retries lock ``FOR NO KEY UPDATE … SKIP LOCKED`` at most (the foundation's rule: v1 holds
``FOR KEY SHARE`` on a participant while it sends). Ported from v1's tests/db/test_emails.py.
"""

import dataclasses
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, delete, text, update

from app.adapters.db.engine import make_engine
from app.adapters.db.link_tokens import SqlLinkTokenStore
from app.adapters.db.models import EmailRecord, Participant
from app.adapters.registration.emails import KIND, SqlInvitationStore
from app.core.entities import Delivered, LinkToken, NotDelivered
from app.core.ports import StorageUnavailable
from app.core.registration.ports import ClaimedEmail
from tests.conftest import ParticipantFactory
from tests.registration.helpers import age_emails, captured_sql, rows

NOW = datetime(2026, 10, 20, 16, 0, tzinfo=UTC)
EMAIL = "visitor@example.com"
STALE = timedelta(minutes=15)


def invitations(engine: Engine) -> list[EmailRecord]:
    return [row for row in rows(engine, EmailRecord) if row.kind == KIND]


def email_of(claimed: ClaimedEmail | None) -> tuple[object, ...] | None:
    """The claimed email without the moment of the claim: a later claim of it has another."""
    if claimed is None:
        return None
    return (
        claimed.id,
        claimed.participant_id,
        claimed.recipient,
        claimed.unsubscribe_id,
        claimed.idempotency_key,
    )


@pytest.fixture
def store(migrated_engine: Engine) -> SqlInvitationStore:
    return SqlInvitationStore(migrated_engine)


def test_the_kind_is_the_lesson_invitation() -> None:
    assert KIND == "lesson_invitation"


def test_first_claim_creates_a_pending_invitation(
    store: SqlInvitationStore, migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(EMAIL)
    key = uuid.uuid4()

    claimed = store.claim(created.id, key, STALE)

    [row] = rows(migrated_engine, EmailRecord)
    assert claimed == ClaimedEmail(
        id=row.id,
        participant_id=created.id,
        recipient=EMAIL,
        unsubscribe_id=created.unsubscribe_id,
        idempotency_key=key,
        claimed_at=row.updated_at,
    )
    assert (row.kind, row.status, row.idempotency_key, row.attempts) == (KIND, "pending", key, 0)


def test_unknown_participant_claims_nothing(
    store: SqlInvitationStore, migrated_engine: Engine
) -> None:
    assert store.claim(404, uuid.uuid4(), STALE) is None
    assert rows(migrated_engine, EmailRecord) == []


def test_a_confirmation_of_v1_does_not_stand_for_the_invitation(
    store: SqlInvitationStore, migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    """One email of each kind per participant: v1's ``confirmation`` is another kind."""
    created = participant_factory(EMAIL, origin=None, emails={"confirmation": "sent"})

    assert store.claim(created.id, uuid.uuid4(), STALE) is not None
    assert sorted(row.kind for row in rows(migrated_engine, EmailRecord)) == [
        "confirmation",
        KIND,
    ]


def test_pending_or_sent_invitation_is_not_claimed_again(
    store: SqlInvitationStore, migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(EMAIL)
    claimed = store.claim(created.id, uuid.uuid4(), STALE)
    assert claimed is not None

    assert store.claim(created.id, uuid.uuid4(), STALE) is None  # pending
    store.record_delivery(claimed, Delivered(provider_id="re_1", attempts=2), NOW, None)
    assert store.claim(created.id, uuid.uuid4(), STALE) is None  # sent

    [row] = invitations(migrated_engine)
    assert (row.status, row.resend_id, row.sent_at, row.attempts) == ("sent", "re_1", NOW, 2)


def test_failed_invitation_is_claimed_again_with_its_key(
    store: SqlInvitationStore, migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(EMAIL)
    first = store.claim(created.id, uuid.uuid4(), STALE)
    assert first is not None
    store.record_delivery(first, NotDelivered(error="HTTP 500 x", attempts=3), NOW, None)
    [failed] = invitations(migrated_engine)
    assert (failed.status, failed.last_error, failed.sent_at) == ("failed", "HTTP 500 x", None)

    second = store.claim(created.id, uuid.uuid4(), STALE)

    assert email_of(second) == email_of(first)
    [row] = invitations(migrated_engine)
    assert (row.status, row.attempts) == ("pending", 3)
    assert row.updated_at > failed.updated_at
    assert second is not None and second.claimed_at == row.updated_at
    store.record_delivery(second, Delivered(provider_id="", attempts=1), NOW, None)
    [done] = invitations(migrated_engine)
    assert (done.attempts, done.resend_id) == (4, None)  # an empty provider id is not stored


def test_concurrent_claims_of_a_failed_invitation_give_it_to_one(
    store: SqlInvitationStore, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(EMAIL)
    first = store.claim(created.id, uuid.uuid4(), STALE)
    assert first is not None
    store.record_delivery(first, NotDelivered(error="HTTP 500 x", attempts=1), NOW, None)

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(store.claim, created.id, uuid.uuid4(), STALE) for _ in range(6)]
        results = [future.result(timeout=10) for future in futures]  # re-raises errors

    assert [email_of(result) for result in results if result is not None] == [email_of(first)]


def test_starting_a_claimed_invitation_stamps_it_again(
    store: SqlInvitationStore, migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    """The 15 minutes of a «pending» invitation run from the start of sending, not the queue."""
    claimed = store.claim(participant_factory(EMAIL).id, uuid.uuid4(), STALE)
    assert claimed is not None
    age_emails(migrated_engine, 10)
    [aged] = invitations(migrated_engine)

    started = store.start(dataclasses.replace(claimed, claimed_at=aged.updated_at))

    [row] = invitations(migrated_engine)
    assert started is not None
    assert email_of(started) == email_of(claimed)
    assert started.claimed_at == row.updated_at > aged.updated_at
    assert row.status == "pending"


def test_an_invitation_claimed_again_is_not_started_by_the_first_claim(
    store: SqlInvitationStore, migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    """The first claim waited past 15 minutes and the operator's retry took the row meanwhile."""
    created = participant_factory(EMAIL)
    first = store.claim(created.id, uuid.uuid4(), STALE)
    assert first is not None
    age_emails(migrated_engine, 16)
    [aged] = invitations(migrated_engine)
    late = dataclasses.replace(first, claimed_at=aged.updated_at)
    retried = store.claim_failed(STALE, store.database_now())
    assert email_of(retried) == email_of(first)

    assert store.start(late) is None
    assert retried is not None and store.start(retried) is not None


def test_a_sent_invitation_is_not_started(
    store: SqlInvitationStore, participant_factory: ParticipantFactory
) -> None:
    claimed = store.claim(participant_factory(EMAIL).id, uuid.uuid4(), STALE)
    assert claimed is not None
    store.record_delivery(claimed, Delivered(provider_id="re_1", attempts=1), NOW, None)

    assert store.start(claimed) is None


def test_only_the_current_claim_records_and_sent_stays_sent(
    store: SqlInvitationStore, migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    """Process A hangs past 15 minutes; the retry B takes the email and sends it; A comes back."""
    created = participant_factory(EMAIL)
    claim_a = store.claim(created.id, uuid.uuid4(), STALE)
    assert claim_a is not None
    age_emails(migrated_engine, 16)
    [aged] = invitations(migrated_engine)
    claim_a = dataclasses.replace(claim_a, claimed_at=aged.updated_at)
    claim_b = store.claim_failed(STALE, store.database_now())
    assert claim_b is not None
    refused = NotDelivered(error="HTTP 422 validation_error", attempts=1, rejected=True)

    assert not store.record_delivery(claim_a, refused, NOW, uuid.uuid4())  # B's «pending»
    assert store.record_delivery(claim_b, Delivered(provider_id="re_b", attempts=1), NOW, None)
    assert not store.record_delivery(claim_a, refused, NOW, uuid.uuid4())  # «sent»

    [row] = invitations(migrated_engine)
    assert (row.status, row.resend_id, row.last_error, row.attempts) == ("sent", "re_b", None, 1)
    assert row.idempotency_key == claim_a.idempotency_key


def test_rows_go_with_the_participant(
    store: SqlInvitationStore, migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(EMAIL)
    other = participant_factory("other@example.com")
    claimed = store.claim(created.id, uuid.uuid4(), STALE)
    kept = store.claim(other.id, uuid.uuid4(), STALE)
    assert claimed is not None and kept is not None

    with migrated_engine.begin() as connection:
        connection.execute(delete(Participant).where(Participant.id == created.id))
    # The row went with the participant: recording the late result changes nothing.
    assert not store.record_delivery(claimed, Delivered(provider_id="re_1", attempts=1), NOW, None)

    assert [row.id for row in rows(migrated_engine, EmailRecord)] == [kept.id]


def test_long_error_is_cut_to_the_column(
    store: SqlInvitationStore, migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    claimed = store.claim(participant_factory(EMAIL).id, uuid.uuid4(), STALE)
    assert claimed is not None

    store.record_delivery(claimed, NotDelivered(error="x" * 600, attempts=1), NOW, None)

    assert invitations(migrated_engine)[0].last_error == "x" * 500


def test_unreachable_database_is_storage_unavailable() -> None:
    engine = make_engine("postgresql+psycopg://webinar@127.0.0.1:1/unreachable")
    try:
        store = SqlInvitationStore(engine)
        with pytest.raises(StorageUnavailable):
            store.claim(1, uuid.uuid4(), STALE)
        with pytest.raises(StorageUnavailable):
            store.record_delivery(
                ClaimedEmail(1, 1, EMAIL, uuid.uuid4(), uuid.uuid4(), claimed_at=NOW),
                Delivered(provider_id="", attempts=1),
                NOW,
                None,
            )
        with pytest.raises(StorageUnavailable):
            store.database_now()
    finally:
        engine.dispose()


def test_every_change_stamps_updated_at(
    store: SqlInvitationStore, migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    """No trigger in the database: the application stamps every change of the row."""
    claimed = store.claim(participant_factory(EMAIL).id, uuid.uuid4(), STALE)
    assert claimed is not None
    long_ago = datetime(2026, 1, 1, tzinfo=UTC)
    with migrated_engine.begin() as connection:
        connection.execute(update(EmailRecord).values(updated_at=long_ago))

    still_claimed = dataclasses.replace(claimed, claimed_at=long_ago)
    store.record_delivery(still_claimed, NotDelivered(error="x", attempts=1), NOW, None)

    assert invitations(migrated_engine)[0].updated_at > long_ago


def test_stale_pending_invitation_is_claimed_again_with_its_key(
    store: SqlInvitationStore, migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    """«pending» older than 15 minutes counts as failed: the process died mid-send."""
    created = participant_factory(EMAIL)
    first = store.claim(created.id, uuid.uuid4(), STALE)
    assert first is not None

    age_emails(migrated_engine, 14)
    assert store.claim(created.id, uuid.uuid4(), STALE) is None
    age_emails(migrated_engine, 16)
    again = store.claim(created.id, uuid.uuid4(), STALE)

    assert email_of(again) == email_of(first)
    assert store.claim(created.id, uuid.uuid4(), STALE) is None  # fresh again


@pytest.mark.parametrize(("hours", "claimed"), [(1, False), (-1, True)], ids=["ahead", "past"])
def test_a_scheduled_invitation_waits_for_its_time(
    store: SqlInvitationStore,
    migrated_engine: Engine,
    participant_factory: ParticipantFactory,
    hours: int,
    claimed: bool,
) -> None:
    created = participant_factory(EMAIL)
    first = store.claim(created.id, uuid.uuid4(), STALE)
    assert first is not None
    store.record_delivery(first, NotDelivered(error="x", attempts=1), NOW, None)
    with migrated_engine.begin() as connection:
        connection.execute(
            update(EmailRecord).values(
                scheduled_at=text(f"now() + interval '{hours} hours'"),
                updated_at=text("now() - interval '1 hour'"),
            )
        )

    assert (store.claim(created.id, uuid.uuid4(), STALE) is not None) is claimed
    started = store.database_now()
    store_claim = store.claim_failed(STALE, started)
    assert store_claim is None  # taken above, or still waiting


def test_sent_invitation_forgets_the_previous_error(
    store: SqlInvitationStore, migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(EMAIL)
    claimed = store.claim(created.id, uuid.uuid4(), STALE)
    assert claimed is not None
    store.record_delivery(claimed, NotDelivered(error="HTTP 500 x", attempts=1), NOW, None)
    again = store.claim(created.id, uuid.uuid4(), STALE)
    assert again is not None

    store.record_delivery(again, Delivered(provider_id="re_1", attempts=1), NOW, None)

    [row] = invitations(migrated_engine)
    assert (row.status, row.last_error) == ("sent", None)


def test_rejected_invitation_gets_a_new_key(
    store: SqlInvitationStore, migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(EMAIL)
    first = store.claim(created.id, uuid.uuid4(), STALE)
    assert first is not None
    new_key = uuid.uuid4()

    rejected = NotDelivered(error="HTTP 429 daily_quota_exceeded", attempts=1, rejected=True)
    store.record_delivery(first, rejected, NOW, new_key)
    again = store.claim(created.id, uuid.uuid4(), STALE)

    assert again is not None
    assert (again.id, again.idempotency_key) == (first.id, new_key)
    assert invitations(migrated_engine)[0].idempotency_key == new_key


# --- claiming failed invitations for the operator's retry ----------------------------------


def fail(store: SqlInvitationStore, participant_id: int) -> ClaimedEmail:
    claimed = store.claim(participant_id, uuid.uuid4(), STALE)
    assert claimed is not None
    store.record_delivery(claimed, NotDelivered(error="x", attempts=1), NOW, None)
    return claimed


def test_failed_invitations_changed_before_the_call_are_claimed_oldest_first(
    store: SqlInvitationStore, migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    first = fail(store, participant_factory("first@example.com").id)
    second = fail(store, participant_factory("second@example.com").id)
    sent = store.claim(participant_factory("sent@example.com").id, uuid.uuid4(), STALE)
    assert sent is not None
    store.record_delivery(sent, Delivered(provider_id="re_1", attempts=1), NOW, None)
    with migrated_engine.begin() as connection:
        connection.execute(
            update(EmailRecord)
            .where(EmailRecord.id == second.id)
            .values(updated_at=text("now() - interval '2 hours'"))
        )
    started = store.database_now()

    taken = [store.claim_failed(STALE, started), store.claim_failed(STALE, started)]

    assert [claim.id if claim else None for claim in taken] == [second.id, first.id]
    assert store.claim_failed(STALE, started) is None  # claimed now: changed after the start
    assert {row.status for row in invitations(migrated_engine)} == {"pending", "sent"}


def test_the_retry_leaves_v1_confirmations_alone(
    store: SqlInvitationStore, participant_factory: ParticipantFactory
) -> None:
    participant_factory(EMAIL, origin=None, emails={"confirmation": "failed"})

    assert store.claim_failed(STALE, store.database_now() + timedelta(hours=1)) is None


def wait_for_lock_wait(engine: Engine) -> None:
    """Block until some session of this database waits for a row lock."""
    query = text(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname = current_database() AND wait_event_type = 'Lock'"
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            if connection.execute(query).scalar():
                return
        time.sleep(0.01)
    raise AssertionError("the claim never waited for the unsubscribe")


def test_claim_during_an_unsubscribe_waits_and_finds_nobody(
    store: SqlInvitationStore, migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    """The claim locks the participant: an unsubscribe in flight finishes first, no FK error."""
    created = participant_factory(EMAIL)

    with migrated_engine.connect() as other, ThreadPoolExecutor(max_workers=1) as pool:
        unsubscribe = other.begin()
        other.execute(delete(Participant).where(Participant.id == created.id))
        claim = pool.submit(store.claim, created.id, uuid.uuid4(), STALE)
        wait_for_lock_wait(migrated_engine)
        unsubscribe.commit()
        result = claim.result(timeout=10)  # StorageConflict here would mean an FK race

    assert result is None
    assert rows(migrated_engine, EmailRecord) == []


@pytest.mark.parametrize(
    ("claim", "lock"),
    [
        ("registration", "FOR KEY SHARE"),
        ("retry", "FOR NO KEY UPDATE OF emails, participants SKIP LOCKED"),
    ],
)
def test_claims_lock_no_more_than_the_foundation_allows(
    store: SqlInvitationStore,
    migrated_engine: Engine,
    participant_factory: ParticipantFactory,
    claim: str,
    lock: str,
) -> None:
    created = participant_factory(EMAIL)
    if claim == "retry":
        fail(store, created.id)

    with captured_sql(migrated_engine) as statements:
        if claim == "registration":
            assert store.claim(created.id, uuid.uuid4(), STALE) is not None
        else:
            started = store.database_now()
            assert store.claim_failed(STALE, started) is not None

    [locking] = [sql for sql in statements if " FOR " in sql]
    assert "FROM participants" in locking or "JOIN participants" in locking
    assert locking.rstrip().endswith(lock)


# --- the bot link of the letter ------------------------------------------------------------


def token(participant_id: int, source: str, created_at: datetime, value: str) -> LinkToken:
    return LinkToken(
        token=value,
        participant_id=participant_id,
        source=source,  # type: ignore[arg-type]
        created_at=created_at,
        expires_at=created_at + timedelta(days=7),
    )


def test_the_latest_email_token_issued_at_or_after_a_moment(
    store: SqlInvitationStore, migrated_engine: Engine, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(EMAIL)
    other = participant_factory("other@example.com")
    tokens = SqlLinkTokenStore(migrated_engine)
    since = NOW - timedelta(hours=24)
    tokens.add(
        token(created.id, "email", since - timedelta(minutes=1), "old_email_token_" + "a" * 20)
    )
    tokens.add(token(created.id, "email", NOW - timedelta(hours=2), "email_token_one_" + "b" * 20))
    tokens.add(token(created.id, "email", NOW - timedelta(hours=1), "email_token_two_" + "c" * 20))
    tokens.add(token(created.id, "screen", NOW, "screen_token_" + "d" * 23))
    tokens.add(token(other.id, "email", NOW, "other_email_token_" + "e" * 18))

    found = store.latest_email_token(created.id, since)

    assert found is not None
    assert (found.token, found.source, found.participant_id) == (
        "email_token_two_" + "c" * 20,
        "email",
        created.id,
    )
    assert store.latest_email_token(created.id, NOW) is None
    at_the_moment = store.latest_email_token(created.id, NOW - timedelta(hours=1))
    assert at_the_moment is not None and at_the_moment.token == "email_token_two_" + "c" * 20
