"""Ports of the slice «реєстрація і лист»; the shared ones are in ``app.core.ports``.

The invitation needs its rows of ``emails`` and the bot links already issued for it; the
foundation's stores do not cover them, so the slice has its own port and SQL adapter. The check
of the mail domain asks DNS through its own port too (``MailDomains``).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from app.core.entities import DeliveryResult, LinkToken, OutgoingEmail


@dataclass(frozen=True, slots=True)
class ClaimedEmail:
    """An invitation taken for sending: no other process sends it until it is recorded.

    ``claimed_at`` is the ``updated_at`` the claim stamped: it tells this claim from a later
    one, made once the row looked failed (``pending`` longer than 15 minutes).
    """

    id: int
    participant_id: int
    recipient: str
    unsubscribe_id: uuid.UUID
    idempotency_key: uuid.UUID
    claimed_at: datetime


class InvitationStore(Protocol):
    """The invitation's rows of ``emails`` (one per participant) and its bot links.

    Failures raise as in ``ParticipantStore``: ``StorageUnavailable``, ``StorageConflict``,
    ``StorageError``.
    """

    def claim(
        self, participant_id: int, idempotency_key: uuid.UUID, stale_after: timedelta
    ) -> ClaimedEmail | None:
        """Take the participant's invitation for sending.

        A new row is ``pending`` with ``idempotency_key``; an existing one is taken only if it
        failed or stayed ``pending`` longer than ``stale_after`` (by the database clock), and
        keeps its key. ``None``: no such participant, or the invitation is sent or in flight.
        """
        ...

    def start(self, claimed: ClaimedEmail) -> ClaimedEmail | None:
        """Begin sending a claimed invitation: stamp ``updated_at`` again and return the claim.

        ``None`` when the row changed since the claim: another process took it (it looked
        failed meanwhile), or the participant is gone.
        """
        ...

    def database_now(self) -> datetime:
        """The database clock, the one ``updated_at`` is stamped with."""
        ...

    def claim_failed(self, stale_after: timedelta, changed_before: datetime) -> ClaimedEmail | None:
        """Take the least recently changed invitation awaiting resending, changed before then."""
        ...

    def record_delivery(
        self,
        claimed: ClaimedEmail,
        result: DeliveryResult,
        at: datetime,
        next_key: uuid.UUID | None,
    ) -> bool:
        """Store the outcome of this claim; ``next_key`` replaces the key after a sure refusal.

        Only while the row is still this claim (``pending``, ``updated_at`` unchanged), so a
        ``sent`` email is never overwritten. ``False``: another process took the email since.
        """
        ...

    def latest_email_token(self, participant_id: int, issued_since: datetime) -> LinkToken | None:
        """The participant's latest bot token of the source ``email`` issued at or after then."""
        ...


class InvitationComposer(Protocol):
    """Writes the invitation (docs/copy.md, section 3)."""

    def invitation(
        self, recipient: str, unsubscribe_token: str, bot_url: str | None
    ) -> OutgoingEmail:
        """The letter; without ``bot_url`` (no bot set up) the bot paragraph has no button."""
        ...


class MailDomains(Protocol):
    """Whether the domain of an address takes mail (docs/requirements.md, section 5)."""

    def accepts_mail(self, domain: str) -> bool:
        """False only when DNS answers that ``domain`` does not exist or takes no mail.

        A timeout or a failure of DNS gives no verdict: true, so registration is not blocked.
        """
        ...
