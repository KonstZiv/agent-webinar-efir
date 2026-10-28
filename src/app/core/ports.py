"""Ports: interfaces the core needs from the outside world.

Shared by the slices (docs/requirements.md, section 12): the stores of participants and bot
link tokens, email and the messenger. A slice that needs more defines its own port in its own
package (``app/core/<slice>/``).
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from app.core.entities import (
    Button,
    ChatMember,
    DeliveryResult,
    HumanCheckResult,
    LinkToken,
    NewParticipant,
    OutgoingEmail,
    Participant,
    TelegramAccount,
)


class DatabaseProbe(Protocol):
    """Checks that the database accepts queries."""

    def is_available(self) -> bool:
        """Return ``True`` when a trivial query succeeds."""
        ...


class Clock(Protocol):
    """Source of the current time."""

    def now(self) -> datetime:
        """Return the current moment as a timezone-aware datetime."""
        ...


class HumanCheckUnavailable(Exception):
    """The human check service cannot give a verdict (network, outage, misconfiguration)."""


class HumanCheck(Protocol):
    """Server-side check of the widget answer that a person fills in the form."""

    def verify(self, token: str) -> HumanCheckResult:
        """Check the widget token. Raises ``HumanCheckUnavailable`` when there is no verdict."""
        ...


class RateLimiter(Protocol):
    """Counts attempts per key within a time window."""

    def allow(self, key: str) -> bool:
        """Record an attempt for ``key``; ``False`` when the limit is already reached."""
        ...

    def refund(self, key: str) -> None:
        """Forget the latest recorded attempt for ``key``: it did not take effect."""
        ...


class StorageError(Exception):
    """The database failed the operation; the subclasses tell an outage from bad data.

    Raised as is for any other failure (a value the column cannot hold, a broken statement):
    a bug to fix, not a state to show visitors.
    """


class StorageUnavailable(StorageError):
    """The database did not answer in time or refused the connection."""


class StorageConflict(StorageError):
    """The data broke a constraint: a taken unique value, a missing participant, a failed check."""


class ParticipantStore(Protocol):
    """Participants of v1 and v2 in the shared table; data operations only.

    Every method raises ``StorageUnavailable`` when the database does not answer,
    ``StorageConflict`` when the data breaks a constraint, ``StorageError`` otherwise.
    """

    def add_if_absent(self, participant: NewParticipant) -> tuple[Participant, bool]:
        """Store ``participant`` unless its address is taken.

        Return the stored participant and whether it was created now. An existing row is not
        changed: its source, consent and origin stay from the first registration. One
        statement: an unsubscribe running at the same time either waits for it or comes first.
        """
        ...

    def by_id(self, participant_id: int) -> Participant | None: ...

    def by_email(self, email: str) -> Participant | None:
        """Find by the normalised address."""
        ...

    def by_unsubscribe_id(self, unsubscribe_id: uuid.UUID) -> Participant | None: ...

    def by_telegram(self, tg_user_id: int) -> Participant | None: ...

    def remove_by_unsubscribe_id(self, unsubscribe_id: uuid.UUID) -> bool:
        """Delete the participant; the database deletes their emails, link tokens and clicks.

        Return whether a participant was deleted.
        """
        ...

    def link_telegram_if_free(
        self, participant_id: int, account: TelegramAccount, at: datetime
    ) -> bool:
        """Link ``account`` only if neither it nor this participant is linked yet.

        The condition is checked by the same statement that writes. Return whether the link
        was made. When another participant gets the same account at the same moment, one of
        the two raises ``StorageConflict``.
        """
        ...

    def transfer_telegram(
        self, participant_id: int, account: TelegramAccount, at: datetime
    ) -> bool:
        """Link ``account`` to this participant only, in one transaction.

        The account is cleared from any other participant (with their ``channel_member``);
        a different account linked to this participant is replaced, and ``channel_member``
        is reset then. Return whether the participant exists.
        """
        ...

    def set_channel_member(self, participant_id: int, tg_user_id: int, member: bool) -> bool:
        """Store the result of a channel check, if the participant still has this account.

        Return whether it was stored: the account may have moved while Telegram answered.
        """
        ...


class LinkTokenStore(Protocol):
    """Personal links to the bot; data operations only, rules belong to the slices.

    Failures raise as in ``ParticipantStore``: a token of a removed participant is a
    ``StorageConflict``.
    """

    def add(self, token: LinkToken) -> None: ...

    def find(self, token: str) -> LinkToken | None: ...

    def claim(self, token: str, tg_user_id: int, at: datetime) -> bool:
        """Record a use of a single-use token only if it is unused or this user used it.

        The condition is checked by the same statement that writes, so of two users claiming
        at once only one gets the token. ``used_at`` keeps the first use. Return whether the
        use was recorded; an unknown token is not.
        """
        ...

    def record_use(self, token: str, tg_user_id: int, at: datetime) -> bool:
        """Record a use: ``used_at`` keeps the first one, ``used_by_tg_user_id`` the latest.

        Return whether the token exists.
        """
        ...


class EmailSender(Protocol):
    """Sends one email; the same ``idempotency_key`` never sends it twice."""

    def send(self, message: OutgoingEmail, idempotency_key: uuid.UUID) -> DeliveryResult: ...


class MessengerUnavailable(Exception):
    """Telegram did not answer or refused the request."""


class Messenger(Protocol):
    """The Telegram Bot API calls the bot needs; failures raise ``MessengerUnavailable``."""

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        buttons: Sequence[Sequence[Button]] = (),
        *,
        html: bool = False,
        preview: bool = True,
    ) -> None:
        """Send ``text`` to a chat id, or to a channel given as ``@name``; ``buttons`` are rows.

        ``html`` sends ``text`` with ``parse_mode`` HTML (the caller escapes it);
        ``preview=False`` turns the link preview off.
        """
        ...

    def answer_callback(
        self, callback_id: str, text: str | None = None, show_alert: bool = False
    ) -> None:
        """Answer a button press; ``show_alert`` shows ``text`` as a dialog, not a toast."""
        ...

    def channel_member(self, channel: str, user_id: int) -> ChatMember: ...

    def set_webhook(self, url: str, secret: str, allowed_updates: Sequence[str]) -> None: ...
