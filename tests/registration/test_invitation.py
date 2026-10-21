"""The invitation's delivery: claim → bot link → letter → Resend → record (requirements, 6).

One invitation per participant, a v1 participant included. The idempotency key stays when the
fate of an attempt is unknown and is replaced after a sure refusal. ``deliver`` never raises: a
failure of mail or storage never reaches the visitor. The letter carries an ``email`` token of
the bot, reused for 24 hours (Resend keeps a key for 24 hours and refuses another body under it).
Runs on the test database with a fake Resend (tests/fakes.py).
"""

import logging
import re
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import Engine

from app.adapters.db.link_tokens import SqlLinkTokenStore
from app.adapters.db.models import EmailRecord, LinkToken
from app.adapters.registration.emails import SqlInvitationStore
from app.core.entities import Delivered, DeliveryResult, OutgoingEmail
from app.core.ports import StorageUnavailable
from app.core.registration.bot_links import TOKEN_TERM, BotLinks
from app.core.registration.invitation import EMAIL_TOKEN_REUSE, STALE_PENDING_AFTER, RetryReport
from app.core.unsubscribe import make_token
from tests.conftest import ParticipantFactory
from tests.factories import CreatedParticipant
from tests.fakes import FAILED, REJECTED, WEBINAR_START
from tests.registration.delivery import PUBLIC, SECRET, HookedSender, World
from tests.registration.helpers import BOT, Unavailable, age_emails, app_log, rows

EMAIL = "visitor@example.com"


@pytest.fixture
def world(migrated_engine: Engine) -> World:
    return World(migrated_engine)


@pytest.fixture
def visitor(participant_factory: ParticipantFactory) -> CreatedParticipant:
    return participant_factory(EMAIL)


def test_new_invitation_is_sent_and_recorded(world: World, visitor: CreatedParticipant) -> None:
    world.deliver(visitor.id)

    [(message, key)] = world.sender.sent
    token = make_token(visitor.unsubscribe_id, SECRET)
    assert message.to == EMAIL
    assert message.headers["List-Unsubscribe"] == f"<{PUBLIC}/unsubscribe/{token}>"
    record = world.record()
    assert key == record.idempotency_key
    assert (record.kind, record.status, record.resend_id, record.attempts, record.sent_at) == (
        "lesson_invitation",
        "sent",
        "fake-1",
        1,
        WEBINAR_START,
    )


def test_failure_is_recorded_without_personal_data(
    world: World, visitor: CreatedParticipant
) -> None:
    world.sender.results.append(FAILED)

    world.deliver(visitor.id)

    record = world.record()
    assert (record.status, record.last_error, record.attempts) == ("failed", FAILED.error, 3)
    assert EMAIL not in (record.last_error or "")


def test_sent_invitation_is_not_sent_again(world: World, visitor: CreatedParticipant) -> None:
    delivery = world.delivery()

    world.deliver(visitor.id, delivery)
    world.deliver(visitor.id, delivery)

    assert len(world.sender.sent) == 1


def test_a_participant_of_v1_gets_the_invitation_once(
    world: World, participant_factory: ParticipantFactory
) -> None:
    """Registered through v1 (``origin`` empty, a ``confirmation`` sent): one invitation."""
    from_v1 = participant_factory(EMAIL, origin=None, emails={"confirmation": "sent"})
    delivery = world.delivery()

    world.deliver(from_v1.id, delivery)
    world.deliver(from_v1.id, delivery)

    assert [message.to for message, _ in world.sender.sent] == [EMAIL]
    kinds = sorted((row.kind, row.status) for row in rows(world.engine, EmailRecord))
    assert kinds == [("confirmation", "sent"), ("lesson_invitation", "sent")]


def test_failure_of_unknown_fate_is_retried_with_the_same_key(
    world: World, visitor: CreatedParticipant
) -> None:
    """A network failure, a timeout or a 5xx may have sent the email: the key stops a duplicate."""
    world.sender.results.append(FAILED)
    delivery = world.delivery()

    world.deliver(visitor.id, delivery)
    world.deliver(visitor.id, delivery)

    first, second = world.keys()
    assert first == second
    record = world.record()
    assert (record.status, record.attempts, record.last_error) == ("sent", 4, None)


def test_rejected_invitation_is_retried_with_a_new_key(
    world: World, visitor: CreatedParticipant
) -> None:
    """A 4xx surely sent nothing; a new key keeps a re-rendered email from a 409."""
    world.sender.results.append(REJECTED)
    delivery = world.delivery()

    world.deliver(visitor.id, delivery)
    stored = world.record().idempotency_key
    world.deliver(visitor.id, delivery)

    first, second = world.keys()
    assert first != second == stored
    assert world.record().status == "sent"


def test_stuck_pending_invitation_is_sent_again_with_the_same_key(
    world: World, visitor: CreatedParticipant
) -> None:
    delivery = world.delivery()
    claimed = SqlInvitationStore(world.engine).claim(visitor.id, uuid.uuid4(), STALE_PENDING_AFTER)
    assert claimed is not None  # the process died after this

    world.deliver(visitor.id, delivery)
    assert world.sender.sent == []  # a fresh «pending» may still be on its way
    age_emails(world.engine, 16)
    world.deliver(visitor.id, delivery)

    [key] = world.keys()
    assert key == claimed.idempotency_key
    assert world.record().status == "sent"


class BrokenComposer:
    def invitation(
        self, recipient: str, unsubscribe_token: str, bot_url: str | None
    ) -> OutgoingEmail:
        raise KeyError(f"template variable for {recipient}")


class BrokenSender(HookedSender):
    def send(self, message: OutgoingEmail, idempotency_key: uuid.UUID) -> DeliveryResult:
        raise ZeroDivisionError(message.to)


@pytest.mark.parametrize(
    ("broken", "error"),
    [
        ("composer", "unexpected KeyError"),
        ("sender", "unexpected ZeroDivisionError"),
        ("bot tokens", "unexpected StorageUnavailable"),
    ],
)
def test_any_error_after_the_claim_is_recorded_as_failed(
    world: World,
    visitor: CreatedParticipant,
    broken: str,
    error: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    if broken == "composer":
        world.composer = BrokenComposer()
    elif broken == "sender":
        world.sender = BrokenSender()
    else:
        world.tokens = Unavailable()  # type: ignore[assignment]

    world.deliver(visitor.id)  # does not raise

    record = world.record()
    assert (record.status, record.last_error) == ("failed", error)
    assert error in app_log(caplog)
    assert EMAIL not in app_log(caplog)


def test_unknown_participant_gets_nothing(world: World) -> None:
    world.deliver(404)

    assert world.sender.sent == []


def test_a_claim_during_a_storage_outage_raises(world: World, visitor: CreatedParticipant) -> None:
    """The registration has not answered yet: it asks the visitor to try again."""
    world.store = Unavailable()  # type: ignore[assignment]

    with pytest.raises(StorageUnavailable):
        world.delivery().claim(visitor.id)


def test_storage_outage_in_the_background_leaves_the_invitation_pending(
    world: World, visitor: CreatedParticipant, caplog: pytest.LogCaptureFixture
) -> None:
    """Logged, not raised; the «pending» row is a failure for the operator in 15 minutes."""
    claimed = world.delivery().claim(visitor.id)
    assert claimed is not None
    world.store = Unavailable()  # type: ignore[assignment]

    world.delivery().deliver(claimed)

    assert world.sender.sent == []
    assert "Invitation not started: StorageUnavailable" in app_log(caplog)
    assert world.record().status == "pending"


def test_an_invitation_taken_by_another_process_is_not_sent(
    world: World, visitor: CreatedParticipant
) -> None:
    """It waited in the queue past 15 minutes, and the operator's retry sent it meanwhile."""
    delivery = world.delivery()
    claimed = delivery.claim(visitor.id)
    assert claimed is not None
    age_emails(world.engine, 16)
    assert delivery.retry_failed().sent == 1

    delivery.deliver(claimed)

    assert len(world.sender.sent) == 1
    assert world.record().status == "sent"


def test_a_late_outcome_never_overwrites_a_sent_invitation(
    world: World, visitor: CreatedParticipant, caplog: pytest.LogCaptureFixture
) -> None:
    """Process A hangs past 15 minutes; the operator's retry sends the email meanwhile.

    A's late sure refusal would mark the email failed under a new key, and the next retry
    would send a second letter: it is logged instead, and the row stays as the retry left it.
    """
    delivery = world.delivery()
    claimed = delivery.claim(visitor.id)
    assert claimed is not None

    def operator_retries_meanwhile() -> None:
        world.sender.on_send = None
        age_emails(world.engine, 16)
        assert delivery.retry_failed() == RetryReport(attempted=1, sent=1, failed=0)

    world.sender.on_send = operator_retries_meanwhile
    world.sender.results.extend([Delivered(provider_id="re_retry", attempts=1), REJECTED])

    delivery.deliver(claimed)  # A's own answer comes last: a sure refusal

    record = world.record()
    assert (record.status, record.resend_id, record.last_error, record.attempts) == (
        "sent",
        "re_retry",
        None,
        1,
    )
    assert record.idempotency_key == claimed.idempotency_key
    assert "Outcome of the invitation to v***@example.com not stored" in app_log(caplog)


def test_log_has_only_the_masked_address(
    world: World, visitor: CreatedParticipant, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    world.sender.results.extend([FAILED, Delivered(provider_id="re_1", attempts=2)])
    delivery = world.delivery()

    world.deliver(visitor.id, delivery)
    world.deliver(visitor.id, delivery)
    world.deliver(visitor.id, delivery)

    logged = app_log(caplog)
    assert EMAIL not in logged
    assert "v***@example.com" in logged
    assert FAILED.error in logged
    assert make_token(visitor.unsubscribe_id, SECRET) not in logged
    for bot_token in world.bot_tokens():
        assert bot_token not in logged


# --- the bot link of the letter (requirements, section 7) ----------------------------------


def test_the_letter_carries_an_email_token_of_the_bot(
    world: World, visitor: CreatedParticipant
) -> None:
    world.deliver(visitor.id)

    [token] = rows(world.engine, LinkToken)
    assert world.bot_tokens() == [token.token]
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token.token)
    assert (token.participant_id, token.source) == (visitor.id, "email")
    assert (token.created_at, token.expires_at) == (WEBINAR_START, WEBINAR_START + TOKEN_TERM)
    assert (token.used_at, token.used_by_tg_user_id) == (None, None)


def test_without_a_bot_no_token_is_issued(world: World, visitor: CreatedParticipant) -> None:
    world.bot = ""

    world.deliver(visitor.id)

    [(message, _)] = world.sender.sent
    assert "https://t.me/agentic_engineers" in message.text
    assert "?start=" not in message.text
    assert rows(world.engine, LinkToken) == []


def test_a_retry_within_a_day_sends_the_same_letter(
    world: World, visitor: CreatedParticipant
) -> None:
    """The same key with another body would get 409 from Resend: the token is reused."""
    world.sender.results.append(FAILED)
    delivery = world.delivery()

    world.deliver(visitor.id, delivery)
    world.clock.advance(EMAIL_TOKEN_REUSE / 2)
    world.deliver(visitor.id, delivery)

    [(first, first_key), (second, second_key)] = world.sender.sent
    assert first_key == second_key
    assert (first.html, first.text) == (second.html, second.text)
    assert len(rows(world.engine, LinkToken)) == 1


def test_a_letter_after_a_day_gets_a_fresh_token(world: World, visitor: CreatedParticipant) -> None:
    """Resend has forgotten the key; the letter gets a token with the whole term ahead."""
    world.sender.results.append(REJECTED)
    delivery = world.delivery()

    world.deliver(visitor.id, delivery)
    world.clock.advance(EMAIL_TOKEN_REUSE)
    world.deliver(visitor.id, delivery)

    first, second = world.bot_tokens()
    assert first != second
    assert len(rows(world.engine, LinkToken)) == 2


def test_the_same_key_carries_the_same_letter_for_a_day_from_its_first_attempt(
    world: World, visitor: CreatedParticipant
) -> None:
    """Resend keeps a key 24 hours from its first request and answers 409 to another body.

    The review's case: a sure refusal at T0 replaces the key; the new key is first used just
    before T0 + 24 h with an unknown fate; the retry after T0 + 24 h sends the same letter.
    """
    world.sender.results.extend([REJECTED, FAILED])
    world.sender.on_send = lambda: world.clock.advance(timedelta(seconds=1))  # a request
    delivery = world.delivery()

    world.deliver(visitor.id, delivery)  # T0: refused for sure, the key is replaced
    world.clock.advance(timedelta(hours=23, minutes=59))
    world.deliver(visitor.id, delivery)  # the first attempt with the new key: fate unknown
    world.clock.advance(timedelta(minutes=2))
    world.deliver(visitor.id, delivery)

    [(_, refused_key), (unknown, key), (again, again_key)] = world.sender.sent
    assert refused_key != key == again_key
    assert (again.html, again.text) == (unknown.html, unknown.text)


def test_a_key_of_the_previous_version_keeps_the_rule_of_the_last_day(
    world: World, visitor: CreatedParticipant
) -> None:
    """Rows written before keys carried their time (uuid4): the token of the last 24 hours."""
    store = SqlInvitationStore(world.engine)
    claimed = store.claim(visitor.id, uuid.uuid4(), STALE_PENDING_AFTER)
    assert claimed is not None
    links = BotLinks(tokens=SqlLinkTokenStore(world.engine), clock=world.clock, bot_username=BOT)
    issued = links.issue(visitor.id, "email")
    world.clock.advance(timedelta(hours=2))

    world.delivery().deliver(claimed)

    [(message, key)] = world.sender.sent
    assert key == claimed.idempotency_key
    assert issued is not None and issued in message.text
