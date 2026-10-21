"""The registration scenario (docs/requirements.md, section 5).

Checks run in a fixed order, as in v1: attempts from the client address → form fields (all
problems together) → the human check → the allowlist of the staging site → attempts for the
email address → the mail domain → storage. The address counter only sees requests that passed
the human check, so a bot cannot block someone else's address; addresses on the allowlist are not
counted at all (rehearsals register them again and again). The mail domain asks DNS, the slowest
check, so it comes last, for those past every other one; addresses on the allowlist go through it
too, and a failure of DNS lets the address through («Поштовий домен», section 5). A known address
gets the same outcome as a new one: its row, source and consent stay from the first registration.
"""

import logging
import re
import uuid
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum

from app.core.entities import NewParticipant, Participant, TrafficSource
from app.core.masking import mask_email
from app.core.ports import (
    Clock,
    HumanCheck,
    HumanCheckUnavailable,
    ParticipantStore,
    RateLimiter,
    StorageConflict,
    StorageUnavailable,
)
from app.core.registration.addresses import is_allowed, is_valid_email, normalize_email
from app.core.registration.ports import MailDomains

logger = logging.getLogger(__name__)

CONSENT_VERSION = "consent-v1"  # docs/legal/consent.md
GA_CLIENT_ID_LENGTH = 100
_GA_CLIENT_ID = re.compile(r"\d+\.\d+", re.ASCII)


@dataclass(frozen=True, slots=True)
class AttemptLimit:
    limit: int
    window: timedelta


IP_ATTEMPTS = AttemptLimit(limit=30, window=timedelta(minutes=1))
ADDRESS_ATTEMPTS = AttemptLimit(limit=5, window=timedelta(hours=1))


class Problem(StrEnum):
    """Why a registration was refused; the form shows the matching text of docs/copy.md 1.8."""

    EMAIL_EMPTY = "email_empty"
    EMAIL_INVALID = "email_invalid"
    EMAIL_DOMAIN = "email_domain"  # «Домен адреси не приймає пошту»
    CONSENT_MISSING = "consent_missing"
    HUMAN_CHECK_FAILED = "human_check_failed"
    TOO_MANY_ATTEMPTS = "too_many_attempts"
    SERVICE_UNAVAILABLE = "service_unavailable"


@dataclass(frozen=True, slots=True)
class RegistrationRequest:
    """What the form sent; ``email`` is as typed."""

    email: str
    consent: bool
    human_token: str
    client_ip: str
    source: TrafficSource = field(default_factory=TrafficSource)
    ga_client_id: str | None = None


@dataclass(frozen=True, slots=True)
class Registered:
    """The address is registered; ``created`` is false when it already was (through v1 too)."""

    participant: Participant
    created: bool


@dataclass(frozen=True, slots=True)
class NotAllowed:
    """The address is not on the allowlist of the staging site: nothing is stored or sent."""


@dataclass(frozen=True, slots=True)
class Refused:
    problems: tuple[Problem, ...]


def clean_ga_client_id(value: str) -> str | None:
    """The GA client id as gtag reports it (``<digits>.<digits>``), otherwise ``None``.

    >>> clean_ga_client_id("123456789.1234567890")
    '123456789.1234567890'
    >>> clean_ga_client_id("GA1.1.123.456") is None
    True
    """
    value = value.strip()
    if len(value) > GA_CLIENT_ID_LENGTH or not _GA_CLIENT_ID.fullmatch(value):
        return None
    return value


def _field_problems(email: str, consent: bool) -> list[Problem]:
    problems = []
    if not email:
        problems.append(Problem.EMAIL_EMPTY)
    elif not is_valid_email(email):
        problems.append(Problem.EMAIL_INVALID)
    if not consent:
        problems.append(Problem.CONSENT_MISSING)
    return problems


class Registration:
    """Registers visitors; the dependencies are ports, so tests pass fakes."""

    def __init__(
        self,
        *,
        participants: ParticipantStore,
        human_check: HumanCheck,
        ip_limiter: RateLimiter,
        address_limiter: RateLimiter,
        clock: Clock,
        allowed_hostnames: Collection[str],
        allowlist: Collection[str],
        mail_domains: MailDomains,
    ) -> None:
        self._participants = participants
        self._human_check = human_check
        self._ip_limiter = ip_limiter
        self._address_limiter = address_limiter
        self._clock = clock
        self._allowed_hostnames = frozenset(name.lower() for name in allowed_hostnames)
        self._allowlist = frozenset(allowlist)
        self._mail_domains = mail_domains

    def register(self, request: RegistrationRequest) -> Registered | NotAllowed | Refused:
        if not self._ip_limiter.allow(request.client_ip):
            logger.info("Registration refused: too many attempts from one client address")
            return Refused((Problem.TOO_MANY_ATTEMPTS,))

        email = normalize_email(request.email)
        if problems := _field_problems(email, request.consent):
            logger.info("Registration refused: %s", ", ".join(problems))
            return Refused(tuple(problems))

        try:
            verdict = self._human_check.verify(request.human_token)
        except HumanCheckUnavailable:
            logger.warning("Registration failed: the human check is unavailable")
            return Refused((Problem.SERVICE_UNAVAILABLE,))
        hostname = (verdict.hostname or "").lower()  # DNS names ignore case
        hostname_ok = not self._allowed_hostnames or hostname in self._allowed_hostnames
        if not (verdict.success and hostname_ok):
            logger.info("Registration refused: the human check did not pass")
            return Refused((Problem.HUMAN_CHECK_FAILED,))

        if self._allowlist:
            if not is_allowed(email, self._allowlist):
                logger.info("Registration refused: %s is not on the allowlist", mask_email(email))
                return NotAllowed()
        elif not self._address_limiter.allow(email):
            logger.info("Registration refused: too many attempts for %s", mask_email(email))
            return Refused((Problem.TOO_MANY_ATTEMPTS,))

        if not self._mail_domains.accepts_mail(email.rpartition("@")[2]):
            logger.info("Registration refused: the domain of %s takes no mail", mask_email(email))
            return Refused((Problem.EMAIL_DOMAIN,))

        now = self._clock.now()
        participant = NewParticipant(
            email=email,
            unsubscribe_id=uuid.uuid4(),
            registered_at=now,
            consent_version=CONSENT_VERSION,
            consent_at=now,
            source=request.source,
            ga_client_id=request.ga_client_id,
        )
        try:
            stored, created = self._participants.add_if_absent(participant)
        except (StorageUnavailable, StorageConflict) as error:
            self.give_back(email)
            logger.warning(
                "Registration failed for %s: %s", mask_email(email), type(error).__name__
            )
            return Refused((Problem.SERVICE_UNAVAILABLE,))
        state = "new participant" if created else "already registered"
        logger.info("Registration: %s %s", state, mask_email(email))
        return Registered(participant=stored, created=created)

    def give_back(self, email: str) -> None:
        """Return the attempt for ``email``: storage failed, the attempt did not take effect.

        A database outage must not lock the address out (as in v1) — neither here nor when the
        caller fails to record what follows the registration. The allowlist counts nothing.
        """
        if not self._allowlist:
            self._address_limiter.refund(normalize_email(email))
