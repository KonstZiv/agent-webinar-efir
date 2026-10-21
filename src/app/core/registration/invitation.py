"""The invitation to the first lesson, ``lesson_invitation`` (docs/requirements.md, section 6).

Registration claims the invitation before it answers (``claim``): the row of ``emails`` is
``pending`` from then on, so whatever stops the background — a storage failure, a restart —
leaves a ``pending`` row that counts as failed after 15 minutes and is resent by the operator.
The letter itself goes out in the background (``deliver``), for a new and for a known address
alike: whether to send is decided by the participant's row of ``emails``, never by whether the
registration created the participant. So a participant of v1 gets the invitation the first time
they enter the address in v2, and a repeated registration (or a repeat after a lost commit
acknowledgement) never sends a second one; only a failed invitation is sent again.

The logic is v1's ``ConfirmationDelivery``: the idempotency key stays when the fate of an attempt
is unknown and is replaced after a sure refusal; ``deliver`` never raises. The letter carries a
bot token of the source ``email``. Resend keeps a key for 24 hours from its first request and
answers 409 to the same key with another body, so the token follows the key: a key carries the
moment it appeared (``idempotency``), and the letter reuses the token issued since then — the one
of the key's first attempt — for 24 hours from that attempt; after that, a fresh token.

The operator's retry (``POST /admin/emails/retry``) runs the same steps for every invitation that
awaits resending, one at a time and within limits; a storage failure reaches the operator.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from app.core.entities import Delivered, DeliveryResult, NotDelivered
from app.core.masking import mask_email
from app.core.ports import Clock, EmailSender, StorageError
from app.core.registration.bot_links import BotLinks
from app.core.registration.idempotency import key_time, new_key
from app.core.registration.ports import ClaimedEmail, InvitationComposer, InvitationStore
from app.core.unsubscribe import make_token

logger = logging.getLogger(__name__)

# «pending» older than this means the process stopped before recording the outcome.
STALE_PENDING_AFTER = timedelta(minutes=15)
# One retry call: at most this many emails, and none started once the budget is spent; one
# email takes at most 15 s (the mail adapter's budget), so the answer comes within ~45 s.
RETRY_LIMIT = 20
RETRY_BUDGET = timedelta(seconds=30)
# Resend keeps an idempotency key this long from its first request; a letter resent with the
# same key within it keeps its bot token.
EMAIL_TOKEN_REUSE = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class RetryReport:
    """Outcome of one retry call: emails tried, accepted by the mail service, failed again."""

    attempted: int
    sent: int
    failed: int


class InvitationDelivery:
    """Sends the invitation of a participant at most once successfully."""

    def __init__(
        self,
        *,
        store: InvitationStore,
        sender: EmailSender,
        composer: InvitationComposer,
        links: BotLinks,
        clock: Clock,
        unsubscribe_secret: str,
    ) -> None:
        self._store = store
        self._sender = sender
        self._composer = composer
        self._links = links
        self._clock = clock
        self._unsubscribe_secret = unsubscribe_secret

    def claim(self, participant_id: int) -> ClaimedEmail | None:
        """Record the invitation as «pending» unless it is sent or being sent already.

        Called while registering, before the answer. ``None``: nothing to send. Storage
        failures raise: the registration then asks the visitor to try again.
        """
        key = new_key(self._clock.now())
        return self._store.claim(participant_id, key, STALE_PENDING_AFTER)

    def deliver(self, claimed: ClaimedEmail) -> None:
        """Send a claimed invitation unless another process took it since; never raises."""
        try:
            started = self._store.start(claimed)
        except StorageError as error:
            # The row stays «pending»: in 15 minutes it is a failure the operator resends.
            logger.error("Invitation not started: %s", type(error).__name__)
            return
        if started is None:
            logger.info("Invitation: taken by another process or the participant is gone")
            return
        self._send(started)

    def retry_failed(self) -> RetryReport:
        """Resend failed and stuck invitations; ``sent`` ones are never touched.

        Only emails unchanged since the call began (by the database clock) are taken: each at
        most once per call, and none that a parallel call has tried meanwhile. A spent quota
        stops the call. A storage failure (``StorageError`` of any kind) is raised as is; the
        counts of the emails tried before it are logged first.
        """
        deadline = self._clock.now() + RETRY_BUDGET
        attempted = sent = 0
        try:
            started = self._store.database_now()
            while attempted < RETRY_LIMIT and self._clock.now() < deadline:
                claimed = self._store.claim_failed(STALE_PENDING_AFTER, started)
                if claimed is None:
                    break
                attempted += 1
                result = self._send(claimed)
                if isinstance(result, Delivered):
                    sent += 1
                elif result.out_of_quota:
                    logger.warning("Retry of failed emails stopped: the mail quota is spent")
                    break
        except StorageError as error:
            logger.error(
                "Retry of failed emails interrupted (%s): attempted %d, sent %d, failed %d",
                type(error).__name__,
                attempted,
                sent,
                attempted - sent,
            )
            raise
        report = RetryReport(attempted=attempted, sent=sent, failed=attempted - sent)
        logger.info(
            "Retry of failed emails: attempted %d, sent %d, failed %d",
            report.attempted,
            report.sent,
            report.failed,
        )
        return report

    def _bot_url(self, claimed: ClaimedEmail) -> str | None:
        """The letter's link to the bot: the token of the key's first attempt, or a new one.

        The token issued since the key appeared is the one its first request carried; Resend
        remembers that body for 24 hours from then. A key without a time (written before keys
        carried one) keeps the earlier rule: the token of the last 24 hours.
        """
        if not self._links.enabled:
            return None
        now = self._clock.now()
        since = key_time(claimed.idempotency_key) or now - EMAIL_TOKEN_REUSE
        recent = self._store.latest_email_token(claimed.participant_id, since)
        if recent is not None and recent.created_at > now - EMAIL_TOKEN_REUSE:
            return self._links.link(recent.token)
        return self._links.issue(claimed.participant_id, "email")

    def _send(self, claimed: ClaimedEmail) -> DeliveryResult:
        """Compose, send and record a claimed email; never raises."""
        masked = mask_email(claimed.recipient)
        result: DeliveryResult
        try:
            token = make_token(claimed.unsubscribe_id, self._unsubscribe_secret)
            bot_url = self._bot_url(claimed)
            message = self._composer.invitation(claimed.recipient, token, bot_url)
            result = self._sender.send(message, claimed.idempotency_key)
        except Exception as error:  # anything: the row must not stay «pending»
            # Only the class name: an exception message may contain the address or a token.
            result = NotDelivered(error=f"unexpected {type(error).__name__}", attempts=0)

        if isinstance(result, Delivered):
            logger.info("Invitation sent to %s (attempts: %d)", masked, result.attempts)
        else:
            logger.warning(
                "Invitation to %s failed: %s (attempts: %d)", masked, result.error, result.attempts
            )
        # A sure refusal sent nothing: the next attempt gets a fresh key, so a re-rendered
        # email is not refused as a different payload under the old key.
        rejected = isinstance(result, NotDelivered) and result.rejected
        next_key = new_key(self._clock.now()) if rejected else None
        try:
            recorded = self._store.record_delivery(claimed, result, self._clock.now(), next_key)
        except StorageError as error:
            logger.error(
                "Outcome of the invitation to %s not stored: %s", masked, type(error).__name__
            )
        else:
            if not recorded:
                logger.warning(
                    "Outcome of the invitation to %s not stored: another process took it", masked
                )
        return result
