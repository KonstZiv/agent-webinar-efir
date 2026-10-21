"""Unsubscribing (docs/contract.md, section 3; docs/requirements.md, section 10).

The participant's row is deleted and the database deletes their emails, link tokens and clicks:
unsubscribing withdraws the consent, nothing is kept. The logic is v1's; storage errors reach
the caller, which answers 503 to any of them.
"""

import logging
from dataclasses import dataclass

from app.core.ports import ParticipantStore
from app.core.unsubscribe import read_token

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class InvalidToken:
    """The link is damaged or forged (copy.md 7.3)."""


@dataclass(frozen=True, slots=True)
class Subscribed:
    """The participant exists; the page asks for confirmation (copy.md 7.1)."""

    email: str


@dataclass(frozen=True, slots=True)
class AlreadyGone:
    """The token is genuine, but the participant has unsubscribed already (copy.md 7.2)."""


@dataclass(frozen=True, slots=True)
class Removed:
    """The participant is gone, now or earlier (copy.md 7.2)."""


class Unsubscription:
    """Looks up and removes participants by token; never logs the token or the address."""

    def __init__(self, *, participants: ParticipantStore, secret: str) -> None:
        self._participants = participants
        self._secret = secret

    def preview(self, token: str) -> InvalidToken | Subscribed | AlreadyGone:
        """What the confirmation page shows; changes nothing."""
        unsubscribe_id = read_token(token, self._secret)
        if unsubscribe_id is None:
            logger.info("Unsubscribe page: invalid token")
            return InvalidToken()
        participant = self._participants.by_unsubscribe_id(unsubscribe_id)
        return AlreadyGone() if participant is None else Subscribed(email=participant.email)

    def confirm(self, token: str) -> InvalidToken | Removed:
        """Delete the participant of ``token``; repeating it is not an error."""
        unsubscribe_id = read_token(token, self._secret)
        if unsubscribe_id is None:
            logger.info("Unsubscribe refused: invalid token")
            return InvalidToken()
        if self._participants.remove_by_unsubscribe_id(unsubscribe_id):
            logger.info("Unsubscribe: participant removed")
        else:
            logger.info("Unsubscribe: the participant was already removed")
        return Removed()
