"""A world for the tests of the invitation: the delivery on the test database, a fake Resend."""

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import Engine

from app.adapters.db.link_tokens import SqlLinkTokenStore
from app.adapters.db.models import EmailRecord
from app.adapters.registration.composer import JinjaInvitationComposer
from app.adapters.registration.emails import SqlInvitationStore
from app.core.entities import DeliveryResult, OutgoingEmail
from app.core.ports import LinkTokenStore
from app.core.registration.bot_links import BotLinks
from app.core.registration.invitation import InvitationDelivery
from app.core.registration.ports import InvitationComposer, InvitationStore
from tests.fakes import FakeEmailSender, FixedClock
from tests.registration.helpers import BOT, rows

SECRET = "test-unsubscribe-secret-0123456789abcdef"
PUBLIC = "https://public-sentinel.example.com"
SENDER = "sender-sentinel@example.com"
BOT_LINK = re.compile(rf"https://t\.me/{BOT}\?start=([A-Za-z0-9_-]+)")


class HookedSender(FakeEmailSender):
    """The fake Resend that also runs ``on_send`` before answering (time passes, a call nests)."""

    def __init__(self, *results: DeliveryResult) -> None:
        super().__init__(*results)
        self.on_send: Callable[[], None] | None = None

    def send(self, message: OutgoingEmail, idempotency_key: uuid.UUID) -> DeliveryResult:
        if self.on_send is not None:
            self.on_send()
        return super().send(message, idempotency_key)


@dataclass
class World:
    engine: Engine
    sender: HookedSender = field(default_factory=HookedSender)
    clock: FixedClock = field(default_factory=FixedClock)
    bot: str = BOT
    store: InvitationStore | None = None
    composer: InvitationComposer | None = None
    tokens: LinkTokenStore | None = None

    def delivery(self) -> InvitationDelivery:
        links = BotLinks(
            tokens=self.tokens or SqlLinkTokenStore(self.engine),
            clock=self.clock,
            bot_username=self.bot,
        )
        return InvitationDelivery(
            store=self.store or SqlInvitationStore(self.engine),
            sender=self.sender,
            composer=self.composer
            or JinjaInvitationComposer(public_base_url=PUBLIC, sender_email=SENDER),
            links=links,
            clock=self.clock,
            unsubscribe_secret=SECRET,
        )

    def deliver(self, participant_id: int, delivery: InvitationDelivery | None = None) -> None:
        """What a registration does: claim the invitation, then deliver it in the background."""
        delivery = delivery or self.delivery()
        claimed = delivery.claim(participant_id)
        if claimed is not None:
            delivery.deliver(claimed)

    def record(self) -> EmailRecord:
        [row] = rows(self.engine, EmailRecord)
        return row

    def keys(self) -> list[uuid.UUID]:
        return [key for _, key in self.sender.sent]

    def bot_tokens(self) -> list[str]:
        """The bot token of every letter sent, in order."""
        return [
            found.group(1)
            for message, _ in self.sender.sent
            if (found := BOT_LINK.search(message.text))
        ]
