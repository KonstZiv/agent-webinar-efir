"""Fake port implementations for the tests of the foundation and every slice.

Each fake records what it was asked and answers as told; none reaches the network.
``fake_overrides()`` gives ``create_app`` a fake for every shared port at once:

    create_app(settings, db_probe=FakeDatabaseProbe(), overrides=fake_overrides())

The stores of participants and link tokens have no fakes: their tests run on the test
database (``migrated_engine``, ``participant_factory``).
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.core.entities import (
    Button,
    ChatMember,
    Delivered,
    DeliveryResult,
    HumanCheckResult,
    NotDelivered,
    OutgoingEmail,
)
from app.core.ports import (
    Clock,
    EmailSender,
    HumanCheck,
    HumanCheckUnavailable,
    Messenger,
    MessengerUnavailable,
)
from app.services import CLOCK, EMAIL_SENDER, HUMAN_CHECK, MESSENGER, Override, override

# The fake clock starts at the beginning of the webinar, 21.10.2026 19:00 in Kyiv (EVENT_START
# of tests/conftest.py).
WEBINAR_START = datetime(2026, 10, 21, 16, 0, tzinfo=UTC)


class FakeDatabaseProbe:
    """Database probe with a fixed answer."""

    def __init__(self, available: bool = True) -> None:
        self.available = available

    def is_available(self) -> bool:
        return self.available


class FixedClock:
    """Clock that stands still until a test moves it forward."""

    def __init__(self, now: datetime = WEBINAR_START) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


# Results a test can script for the email sender.
FAILED = NotDelivered(error="HTTP 500 application_error", attempts=3)  # fate unknown
REJECTED = NotDelivered(error="HTTP 422 validation_error", attempts=1, rejected=True)
OUT_OF_QUOTA = NotDelivered(
    error="HTTP 429 daily_quota_exceeded", attempts=1, rejected=True, out_of_quota=True
)


class FakeEmailSender:
    """Resend stand-in: answers with the given results in turn, then accepts everything."""

    def __init__(self, *results: DeliveryResult) -> None:
        self.results = list(results)
        self.sent: list[tuple[OutgoingEmail, uuid.UUID]] = []

    def send(self, message: OutgoingEmail, idempotency_key: uuid.UUID) -> DeliveryResult:
        self.sent.append((message, idempotency_key))
        if self.results:
            return self.results.pop(0)
        return Delivered(provider_id=f"fake-{len(self.sent)}", attempts=1)


class FakeHumanCheck:
    """Turnstile stand-in: a fixed verdict, or unavailable; remembers the tokens it saw."""

    def __init__(
        self,
        *,
        success: bool = True,
        hostname: str | None = "agent.pythoncourse.me",
        unavailable: bool = False,
    ) -> None:
        self.result = HumanCheckResult(success=success, hostname=hostname)
        self.unavailable = unavailable
        self.tokens: list[str] = []

    def verify(self, token: str) -> HumanCheckResult:
        self.tokens.append(token)
        if self.unavailable:
            raise HumanCheckUnavailable
        return self.result


@dataclass(frozen=True, slots=True)
class SentMessage:
    chat_id: int | str
    text: str
    buttons: tuple[tuple[Button, ...], ...] = ()


@dataclass
class FakeMessenger:
    """Telegram stand-in: channel statuses by user id (``left`` if unknown), or unavailable."""

    members: Mapping[int, ChatMember] = field(default_factory=dict)
    unavailable: bool = False
    sent: list[SentMessage] = field(default_factory=list)
    answered: list[tuple[str, str | None]] = field(default_factory=list)
    alerts: list[bool] = field(default_factory=list)  # ``show_alert`` of each answer, in step
    webhooks: list[tuple[str, str, tuple[str, ...]]] = field(default_factory=list)

    def send_message(
        self, chat_id: int | str, text: str, buttons: Sequence[Sequence[Button]] = ()
    ) -> None:
        self._check()
        self.sent.append(SentMessage(chat_id, text, tuple(tuple(row) for row in buttons)))

    def answer_callback(
        self, callback_id: str, text: str | None = None, show_alert: bool = False
    ) -> None:
        self._check()
        self.answered.append((callback_id, text))
        self.alerts.append(show_alert)

    def channel_member(self, channel: str, user_id: int) -> ChatMember:
        self._check()
        return self.members.get(user_id, ChatMember("left"))

    def set_webhook(self, url: str, secret: str, allowed_updates: Sequence[str]) -> None:
        self._check()
        self.webhooks.append((url, secret, tuple(allowed_updates)))

    def _check(self) -> None:
        if self.unavailable:
            raise MessengerUnavailable


def fake_overrides(
    *,
    clock: Clock | None = None,
    email_sender: EmailSender | None = None,
    human_check: HumanCheck | None = None,
    messenger: Messenger | None = None,
) -> list[Override]:
    """A fake for every shared port that talks to the outside world; pass your own to inspect."""
    return [
        override(CLOCK, clock if clock is not None else FixedClock()),
        override(EMAIL_SENDER, email_sender if email_sender is not None else FakeEmailSender()),
        override(HUMAN_CHECK, human_check if human_check is not None else FakeHumanCheck()),
        override(MESSENGER, messenger if messenger is not None else FakeMessenger()),
    ]
