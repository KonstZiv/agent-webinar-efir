"""Entities the ports exchange with the core.

The participant entities follow the shared model (docs/requirements.md, section 10); the
email and messenger entities carry exactly what the adapters need, nothing about the slices'
rules.
"""

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Literal

# Value of ``participants.origin`` for rows created by v2; v1 leaves it empty.
ORIGIN_V2 = "v2"

type LinkSource = Literal["screen", "email"]

# Length of every ``TrafficSource`` column of ``participants`` (varchar(500)).
SOURCE_VALUE_LENGTH = 500
# PostgreSQL text cannot hold NUL, and lone surrogates cannot be encoded as UTF-8.
_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")


@dataclass(frozen=True, slots=True)
class HumanCheckResult:
    """Verdict of the check that a person fills in a form (Turnstile)."""

    success: bool
    hostname: str | None = None


# --- participants --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrafficSource:
    """Where a visitor came from: UTM tags, Google click identifiers, entry and referring page.

    The values come from the visitor's address bar, so they are made storable on creation:
    NUL and lone surrogates are dropped, the rest is cut to ``SOURCE_VALUE_LENGTH``, and an
    empty value becomes ``None``.

    >>> source = TrafficSource(utm_source="tele\\x00gram", utm_medium="", referrer="x" * 600)
    >>> source.utm_source, source.utm_medium, len(source.referrer or "")
    ('telegram', None, 500)
    """

    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_term: str | None = None
    utm_content: str | None = None
    gclid: str | None = None
    gbraid: str | None = None
    wbraid: str | None = None
    landing_url: str | None = None
    referrer: str | None = None

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if value is not None:
                storable = _UNSTORABLE.sub("", value)[:SOURCE_VALUE_LENGTH] or None
                object.__setattr__(self, item.name, storable)  # frozen: set once, on creation


@dataclass(frozen=True, slots=True)
class NewParticipant:
    """A registration to store; ``email`` is already normalised (trimmed, lower case)."""

    email: str
    unsubscribe_id: uuid.UUID
    registered_at: datetime
    consent_version: str
    consent_at: datetime
    source: TrafficSource = field(default_factory=TrafficSource)
    ga_client_id: str | None = None
    origin: str | None = ORIGIN_V2


@dataclass(frozen=True, slots=True)
class TelegramAccount:
    """A Telegram user: the numeric id is the identity, the username may change or be absent."""

    user_id: int
    username: str | None = None


@dataclass(frozen=True, slots=True)
class Participant:
    """A stored participant, created by v1 (``origin`` empty) or by v2."""

    id: int
    email: str
    unsubscribe_id: uuid.UUID
    registered_at: datetime
    origin: str | None = None
    telegram: TelegramAccount | None = None
    telegram_linked_at: datetime | None = None
    channel_member: bool | None = None  # ``None``: never checked
    level: str | None = None
    ref_code: str | None = None
    referred_by: int | None = None


@dataclass(frozen=True, slots=True)
class LinkToken:
    """A personal link to the bot, ``t.me/<bot>?start=<token>``."""

    token: str
    participant_id: int
    source: LinkSource
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None  # the first use
    used_by_tg_user_id: int | None = None  # the latest user


# --- email ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    """A composed email; ``headers`` holds extra headers such as ``List-Unsubscribe``."""

    sender: str
    to: str
    subject: str
    html: str
    text: str
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Delivered:
    """The provider accepted the email."""

    provider_id: str
    attempts: int


@dataclass(frozen=True, slots=True)
class NotDelivered:
    """The email did not go out; ``error`` holds no personal data.

    ``rejected``: the provider surely did not send it (a retry needs a new idempotency key);
    otherwise its fate is unknown. ``out_of_quota``: the provider's daily limit is reached.
    """

    error: str
    attempts: int
    rejected: bool = False
    out_of_quota: bool = False


type DeliveryResult = Delivered | NotDelivered


# --- messenger -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Button:
    """An inline button: opens ``url`` or sends ``callback_data`` back to the bot."""

    text: str
    url: str | None = None
    callback_data: str | None = None


@dataclass(frozen=True, slots=True)
class ChatMember:
    """A user's status in a channel as Telegram reports it (``member``, ``left``, …)."""

    status: str
    is_member: bool | None = None  # reported for ``restricted`` only
