"""Resending failed invitations: ``POST /admin/emails/retry`` (requirements, sections 6 and 8).

A failed invitation, or a ``pending`` one older than 15 minutes by the database clock (except a
``scheduled_at`` still ahead), is sent again; a sent one is never touched. One call takes each
email once, the least recently changed first, at most 20 within 30 seconds, and stops when the
mail quota is spent. The answer is ``{"attempted", "sent", "failed"}`` as in v1; a database
outage — 503 ``{"status": "unavailable"}``; without the admin token — 401.
"""

import logging
import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, text, update

from app.adapters.db.models import EmailRecord
from app.adapters.registration.emails import SqlInvitationStore
from app.adapters.registration.keys import INVITATION_STORE
from app.core.entities import Delivered, NotDelivered
from app.core.ports import StorageConflict, StorageUnavailable
from app.core.registration.invitation import (
    RETRY_BUDGET,
    RETRY_LIMIT,
    STALE_PENDING_AFTER,
    RetryReport,
)
from app.core.registration.ports import ClaimedEmail
from app.services import override
from tests.conftest import REQUIRED_ENV, ParticipantFactory
from tests.fakes import FAILED, OUT_OF_QUOTA, REJECTED
from tests.registration.conftest import SiteFactory
from tests.registration.delivery import HookedSender, World
from tests.registration.helpers import Unavailable, age_emails, app_log, rows

ADMIN = {"Authorization": f"Bearer {REQUIRED_ENV['ADMIN_TOKEN']}"}
EMAIL = "visitor@example.com"


@pytest.fixture
def world(migrated_engine: Engine) -> World:
    return World(migrated_engine)


def register(
    world: World,
    participant_factory: ParticipantFactory,
    email: str = EMAIL,
    *,
    first_send: Delivered | NotDelivered = FAILED,
) -> int:
    """A participant whose invitation went out once, with the result ``first_send``."""
    created = participant_factory(email)
    world.sender.results.append(first_send)
    world.deliver(created.id)
    return created.id


def record_of(world: World, participant_id: int) -> EmailRecord:
    [row] = [row for row in rows(world.engine, EmailRecord) if row.participant_id == participant_id]
    return row


def test_limits_of_one_call() -> None:
    assert (20, timedelta(seconds=30)) == (RETRY_LIMIT, RETRY_BUDGET)
    assert timedelta(minutes=15) == STALE_PENDING_AFTER


def test_failure_of_unknown_fate_is_resent_with_the_same_key(
    world: World, participant_factory: ParticipantFactory
) -> None:
    participant = register(world, participant_factory)

    report = world.delivery().retry_failed()

    assert report == RetryReport(attempted=1, sent=1, failed=0)
    first, second = world.keys()
    assert first == second == record_of(world, participant).idempotency_key
    assert (record_of(world, participant).status, record_of(world, participant).attempts) == (
        "sent",
        4,
    )


def test_refused_invitation_is_resent_with_the_new_key_from_its_row(
    world: World, participant_factory: ParticipantFactory
) -> None:
    participant = register(world, participant_factory, first_send=REJECTED)
    stored = record_of(world, participant).idempotency_key

    world.delivery().retry_failed()

    first, second = world.keys()
    assert first != second == stored
    assert record_of(world, participant).status == "sent"


def test_sent_invitation_is_left_alone(
    world: World, participant_factory: ParticipantFactory
) -> None:
    participant = register(
        world, participant_factory, first_send=Delivered(provider_id="re_1", attempts=1)
    )
    before = record_of(world, participant)

    report = world.delivery().retry_failed()

    assert report == RetryReport(attempted=0, sent=0, failed=0)
    assert len(world.sender.sent) == 1
    after = record_of(world, participant)
    assert (after.status, after.attempts, after.updated_at) == (
        "sent",
        before.attempts,
        before.updated_at,
    )


def test_stuck_pending_is_resent_and_a_fresh_one_is_not(
    world: World, participant_factory: ParticipantFactory
) -> None:
    created = participant_factory(EMAIL)
    store = SqlInvitationStore(world.engine)
    claimed = store.claim(created.id, uuid.uuid4(), STALE_PENDING_AFTER)  # in flight
    assert claimed is not None
    delivery = world.delivery()

    assert delivery.retry_failed() == RetryReport(attempted=0, sent=0, failed=0)
    age_emails(world.engine, 16)  # the process died mid-send
    assert delivery.retry_failed() == RetryReport(attempted=1, sent=1, failed=0)

    assert world.keys() == [claimed.idempotency_key]


def test_a_scheduled_invitation_is_not_resent_before_its_time(
    world: World, participant_factory: ParticipantFactory
) -> None:
    participant = register(world, participant_factory)
    with world.engine.begin() as connection:
        connection.execute(
            update(EmailRecord).values(scheduled_at=text("now() + interval '1 hour'"))
        )

    assert world.delivery().retry_failed() == RetryReport(attempted=0, sent=0, failed=0)
    assert record_of(world, participant).status == "failed"


def test_each_invitation_is_tried_once_per_call(
    world: World, participant_factory: ParticipantFactory
) -> None:
    register(world, participant_factory, "first@example.com")
    register(world, participant_factory, "second@example.com")
    world.sender.results.extend([FAILED, FAILED])

    report = world.delivery().retry_failed()

    assert report == RetryReport(attempted=2, sent=0, failed=2)
    assert len(world.sender.sent) == 4


def test_invitation_failed_by_a_parallel_call_is_not_taken_again(
    world: World, participant_factory: ParticipantFactory
) -> None:
    """Call B started first; call A fails an invitation meanwhile; B leaves it alone."""
    register(world, participant_factory, "first@example.com")
    register(world, participant_factory, "second@example.com")
    delivery = world.delivery()
    call_a: list[RetryReport] = []

    def run_call_a() -> None:
        world.sender.on_send = None  # once
        call_a.append(delivery.retry_failed())

    world.sender.on_send = run_call_a  # A runs while B sends its first invitation
    world.sender.results.extend([FAILED, FAILED])

    call_b = delivery.retry_failed()

    assert call_b == RetryReport(attempted=1, sent=0, failed=1)
    assert call_a == [RetryReport(attempted=1, sent=0, failed=1)]
    sent_to = sorted(message.to for message, _ in world.sender.sent[2:])
    assert sent_to == ["first@example.com", "second@example.com"]  # each invitation once


def test_least_recently_changed_invitation_goes_first(
    world: World, participant_factory: ParticipantFactory
) -> None:
    """An invitation that keeps failing does not hold back the others."""
    first = register(world, participant_factory, "first@example.com")
    register(world, participant_factory, "second@example.com")
    with world.engine.begin() as connection:
        connection.execute(
            update(EmailRecord)
            .where(EmailRecord.participant_id == first)
            .values(updated_at=text("now() - interval '1 minute'"))
        )
        connection.execute(
            update(EmailRecord)
            .where(EmailRecord.participant_id != first)
            .values(updated_at=text("now() - interval '2 minutes'"))
        )

    world.delivery().retry_failed()

    assert [message.to for message, _ in world.sender.sent[2:]] == [
        "second@example.com",
        "first@example.com",
    ]


def test_one_call_takes_at_most_the_limit(
    world: World, participant_factory: ParticipantFactory
) -> None:
    for number in range(RETRY_LIMIT + 1):
        register(world, participant_factory, f"visitor{number}@example.com")
    delivery = world.delivery()

    assert delivery.retry_failed() == RetryReport(attempted=RETRY_LIMIT, sent=RETRY_LIMIT, failed=0)
    assert delivery.retry_failed() == RetryReport(attempted=1, sent=1, failed=0)


def test_no_new_invitation_is_started_after_the_time_budget(
    world: World, participant_factory: ParticipantFactory
) -> None:
    for number in range(3):
        register(world, participant_factory, f"visitor{number}@example.com")
    world.sender.on_send = lambda: world.clock.advance(timedelta(seconds=20))

    report = world.delivery().retry_failed()

    assert report == RetryReport(attempted=2, sent=2, failed=0)  # 20 s < 30 s, then 40 s


@pytest.mark.parametrize(
    "refusal",
    [
        OUT_OF_QUOTA,
        NotDelivered(
            error="HTTP 429 monthly_quota_exceeded", attempts=1, rejected=True, out_of_quota=True
        ),
    ],
    ids=["daily", "monthly"],
)
def test_spent_quota_stops_the_call(
    world: World,
    participant_factory: ParticipantFactory,
    refusal: NotDelivered,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Until the quota renews every request is refused: no point in sending more."""
    for number in range(3):
        register(world, participant_factory, f"visitor{number}@example.com")
    world.sender.results.append(refusal)
    caplog.clear()

    report = world.delivery().retry_failed()

    assert report == RetryReport(attempted=1, sent=0, failed=1)
    assert len(world.sender.sent) == 4  # three first sends and one retry
    assert "Retry of failed emails stopped: the mail quota is spent" in app_log(caplog)
    assert {row.status for row in rows(world.engine, EmailRecord)} == {"failed"}


def test_storage_outage_reaches_the_caller(world: World) -> None:
    world.store = Unavailable()  # type: ignore[assignment]

    with pytest.raises(StorageUnavailable):
        world.delivery().retry_failed()


class FailsAfterOne:
    """The real store whose second ``claim_failed`` breaks a constraint."""

    def __init__(self, store: SqlInvitationStore) -> None:
        self.store = store
        self.claims = 0

    def claim_failed(self, *args: Any) -> ClaimedEmail | None:
        self.claims += 1
        if self.claims > 1:
            raise StorageConflict("claim failed invitation")
        return self.store.claim_failed(*args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.store, name)


def test_any_storage_failure_reaches_the_caller_with_the_counts_logged(
    world: World, participant_factory: ParticipantFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """One invitation is sent already: the operator learns how many before the failure."""
    register(world, participant_factory, "first@example.com")
    register(world, participant_factory, "second@example.com")
    world.store = FailsAfterOne(SqlInvitationStore(world.engine))
    caplog.clear()

    with pytest.raises(StorageConflict):
        world.delivery().retry_failed()

    logged = app_log(caplog)
    assert "attempted 1, sent 1, failed 0" in logged
    assert "StorageConflict" in logged


def test_log_has_only_masked_addresses(
    world: World, participant_factory: ParticipantFactory, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    register(world, participant_factory)
    world.sender.results.append(FAILED)
    caplog.clear()

    world.delivery().retry_failed()

    logged = app_log(caplog)
    assert EMAIL not in logged
    assert "v***@example.com" in logged
    assert "attempted 1, sent 0, failed 1" in logged


# --- the route -----------------------------------------------------------------------------


def test_the_route_resends_failed_invitations_and_leaves_sent_ones(
    site_factory: SiteFactory, participant_factory: ParticipantFactory
) -> None:
    sender = HookedSender()
    site = site_factory(email_sender=sender)
    failed = participant_factory("failed@example.com", emails={"lesson_invitation": "failed"})
    participant_factory("sent@example.com", emails={"lesson_invitation": "sent"})
    participant_factory("v1@example.com", origin=None, emails={"confirmation": "failed"})
    with site.engine.begin() as connection:  # changed before the call
        connection.execute(
            update(EmailRecord).values(updated_at=text("now() - interval '1 minute'"))
        )
    untouched = state_of(site.emails(), skip=failed.id)

    response = site.client.post("/admin/emails/retry", headers=ADMIN)

    assert response.status_code == 200
    assert response.json() == {"attempted": 1, "sent": 1, "failed": 0}
    assert response.headers["cache-control"] == "no-store"
    assert [message.to for message, _ in sender.sent] == ["failed@example.com"]
    [resent] = [row for row in site.emails() if row.participant_id == failed.id]
    assert (resent.status, resent.resend_id) == ("sent", "fake-1")
    assert state_of(site.emails(), skip=failed.id) == untouched  # sent and v1's: as they were


def state_of(emails: list[EmailRecord], *, skip: int) -> list[tuple[object, ...]]:
    return [
        (row.id, row.kind, row.status, row.attempts, row.updated_at, row.idempotency_key)
        for row in emails
        if row.participant_id != skip
    ]


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong-token-0123456789abcdef0123456789"}],
    ids=["none", "wrong"],
)
def test_the_route_needs_the_admin_token(
    site_factory: SiteFactory, participant_factory: ParticipantFactory, headers: dict[str, str]
) -> None:
    site = site_factory()
    participant_factory(EMAIL, emails={"lesson_invitation": "failed"})

    response = site.client.post("/admin/emails/retry", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert site.email_sender.sent == []


def test_the_route_answers_503_when_the_database_is_down(site_factory: SiteFactory) -> None:
    site = site_factory(overrides=[override(INVITATION_STORE, Unavailable())])

    response = site.client.post("/admin/emails/retry", headers=ADMIN)

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert response.headers["cache-control"] == "no-store"
