"""The registration scenario (requirements, section 5): the order of checks, one row per address.

Checks run as in v1: attempts from the client address → form fields (all problems together) →
the human check → the allowlist of the staging site → attempts for the email address → storage.
The address counter only sees requests that passed the human check, so a bot cannot block
someone else's address; addresses on the allowlist are not counted at all. Before storage, last,
comes the mail domain (DNS): the slowest check, asked only for those past every other one.
Ported from v1 (tests/core/test_registration.py) with the in-memory store of this module.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from app.core.entities import NewParticipant, Participant, TrafficSource
from app.core.ports import StorageConflict, StorageUnavailable
from app.core.registration.registration import (
    ADDRESS_ATTEMPTS,
    CONSENT_VERSION,
    IP_ATTEMPTS,
    NotAllowed,
    Problem,
    Refused,
    Registered,
    Registration,
    RegistrationRequest,
    clean_ga_client_id,
)
from tests.fakes import FakeHumanCheck, FixedClock
from tests.markdown_text import LEGAL_DIR
from tests.registration.helpers import NO_MAIL, FakeMailDomains, app_log

NOW = datetime(2026, 10, 20, 16, 5, tzinfo=UTC)
HOST = "agent.pythoncourse.me"
EMAIL = "visitor@example.com"


class MemoryParticipants:
    """``add_if_absent`` of ``ParticipantStore`` in memory; or every call fails with ``fail``."""

    def __init__(self, fail: type[Exception] | None = None) -> None:
        self.fail = fail
        self.saved: dict[str, NewParticipant] = {}
        self.calls = 0

    def add_if_absent(self, participant: NewParticipant) -> tuple[Participant, bool]:
        self.calls += 1
        if self.fail is not None:
            raise self.fail("add participant")
        created = participant.email not in self.saved
        if created:
            self.saved[participant.email] = participant
        stored = self.saved[participant.email]
        number = list(self.saved).index(participant.email) + 1
        return (
            Participant(
                id=number,
                email=stored.email,
                unsubscribe_id=stored.unsubscribe_id,
                registered_at=stored.registered_at,
                origin=stored.origin,
            ),
            created,
        )


class CountingLimiter:
    """Rate limiter without time: allows ``limit`` attempts per key, records every call."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.allowed: dict[str, int] = {}
        self.keys: list[str] = []
        self.refunded: list[str] = []

    def allow(self, key: str) -> bool:
        self.keys.append(key)
        if self.allowed.get(key, 0) >= self.limit:
            return False
        self.allowed[key] = self.allowed.get(key, 0) + 1
        return True

    def refund(self, key: str) -> None:
        self.refunded.append(key)
        if self.allowed.get(key, 0) > 0:
            self.allowed[key] -= 1


@dataclass
class World:
    participants: MemoryParticipants = field(default_factory=MemoryParticipants)
    human_check: FakeHumanCheck = field(default_factory=lambda: FakeHumanCheck(hostname=HOST))
    ip_limiter: CountingLimiter = field(default_factory=lambda: CountingLimiter(IP_ATTEMPTS.limit))
    address_limiter: CountingLimiter = field(
        default_factory=lambda: CountingLimiter(ADDRESS_ATTEMPTS.limit)
    )
    allowed_hostnames: tuple[str, ...] = (HOST,)
    allowlist: tuple[str, ...] = ()
    mail_domains: FakeMailDomains = field(default_factory=lambda: FakeMailDomains([NO_MAIL]))

    def registration(self) -> Registration:
        return Registration(
            participants=self.participants,  # type: ignore[arg-type]
            human_check=self.human_check,
            ip_limiter=self.ip_limiter,
            address_limiter=self.address_limiter,
            clock=FixedClock(NOW),
            allowed_hostnames=self.allowed_hostnames,
            allowlist=self.allowlist,
            mail_domains=self.mail_domains,
        )


def request(**overrides: object) -> RegistrationRequest:
    values: dict[str, object] = {
        "email": "  Visitor@Example.com ",
        "consent": True,
        "human_token": "token",
        "client_ip": "192.0.2.10",
        "source": TrafficSource(),
        "ga_client_id": None,
    }
    values.update(overrides)
    return RegistrationRequest(**values)  # type: ignore[arg-type]


def registered(outcome: object, *, created: bool) -> bool:
    return (
        isinstance(outcome, Registered)
        and outcome.participant.email == EMAIL
        and outcome.created is created
    )


@pytest.fixture
def world() -> World:
    return World()


def test_limits_from_the_requirements() -> None:
    assert (IP_ATTEMPTS.limit, IP_ATTEMPTS.window.total_seconds()) == (30, 60)
    assert (ADDRESS_ATTEMPTS.limit, ADDRESS_ATTEMPTS.window.total_seconds()) == (5, 3600)


def test_consent_version_matches_the_consent_text() -> None:
    consent = (LEGAL_DIR / "consent.md").read_text(encoding="utf-8")
    assert f"`{CONSENT_VERSION}`" in consent.split("\n## ", 1)[0]
    assert CONSENT_VERSION == "consent-v1"


def test_new_participant_is_saved_with_consent_source_and_origin(world: World) -> None:
    source = TrafficSource(utm_source="telegram", landing_url="https://example.com/?a=1")

    outcome = world.registration().register(request(source=source, ga_client_id="123.456"))

    assert registered(outcome, created=True)
    saved = world.participants.saved[EMAIL]
    assert (saved.consent_version, saved.consent_at, saved.registered_at) == (
        "consent-v1",
        NOW,
        NOW,
    )
    assert saved.source == source
    assert saved.ga_client_id == "123.456"
    assert saved.origin == "v2"
    assert saved.unsubscribe_id.version == 4


def test_repeated_address_gets_the_same_answer_and_no_second_record(world: World) -> None:
    registration = world.registration()
    first = registration.register(request(source=TrafficSource(utm_source="first")))

    outcome = registration.register(
        request(email="VISITOR@example.com", source=TrafficSource(utm_source="second"))
    )

    assert registered(outcome, created=False)
    assert isinstance(first, Registered) and isinstance(outcome, Registered)
    assert outcome.participant == first.participant
    assert len(world.participants.saved) == 1
    assert world.participants.saved[EMAIL].source.utm_source == "first"


@pytest.mark.parametrize(
    ("email", "consent", "problems"),
    [
        ("   ", True, (Problem.EMAIL_EMPTY,)),
        ("not-an-address", True, (Problem.EMAIL_INVALID,)),
        ("visitor@example.com", False, (Problem.CONSENT_MISSING,)),
        ("", False, (Problem.EMAIL_EMPTY, Problem.CONSENT_MISSING)),
        ("name@", False, (Problem.EMAIL_INVALID, Problem.CONSENT_MISSING)),
    ],
)
def test_field_problems_come_together_and_skip_turnstile(
    world: World, email: str, consent: bool, problems: tuple[Problem, ...]
) -> None:
    outcome = world.registration().register(request(email=email, consent=consent))

    assert outcome == Refused(problems)
    assert world.human_check.tokens == []
    assert world.address_limiter.keys == []
    assert world.participants.calls == 0


def test_failed_turnstile_refuses(world: World) -> None:
    world.human_check = FakeHumanCheck(success=False, hostname=HOST)

    assert world.registration().register(request()) == Refused((Problem.HUMAN_CHECK_FAILED,))
    assert world.human_check.tokens == ["token"]
    assert world.participants.calls == 0


def test_hostname_outside_the_list_refuses(world: World) -> None:
    world.human_check = FakeHumanCheck(hostname="evil.example.net")

    assert world.registration().register(request()) == Refused((Problem.HUMAN_CHECK_FAILED,))
    assert world.participants.calls == 0


def test_hostname_is_not_checked_when_the_list_is_empty(world: World) -> None:
    world.human_check = FakeHumanCheck(hostname="example.com")  # Cloudflare's test keys
    world.allowed_hostnames = ()

    assert registered(world.registration().register(request()), created=True)


def test_hostname_comparison_ignores_case(world: World) -> None:
    world.human_check = FakeHumanCheck(hostname="Agent.PythonCourse.ME")

    assert registered(world.registration().register(request()), created=True)


def test_turnstile_unavailable_is_a_service_problem(world: World) -> None:
    world.human_check = FakeHumanCheck(unavailable=True)

    assert world.registration().register(request()) == Refused((Problem.SERVICE_UNAVAILABLE,))
    assert world.participants.calls == 0


@pytest.mark.parametrize("failure", [StorageUnavailable, StorageConflict])
def test_storage_failure_is_a_service_problem_and_gives_the_attempt_back(
    world: World, failure: type[Exception]
) -> None:
    """The attempt did not take effect: a database outage must not lock the address out."""
    world.participants = MemoryParticipants(fail=failure)
    registration = world.registration()
    for _ in range(ADDRESS_ATTEMPTS.limit + 2):
        assert registration.register(request()) == Refused((Problem.SERVICE_UNAVAILABLE,))
    assert world.address_limiter.refunded == [EMAIL] * (ADDRESS_ATTEMPTS.limit + 2)

    world.participants.fail = None

    assert registered(registration.register(request()), created=True)


def test_give_back_returns_the_attempt_of_the_address(world: World) -> None:
    """A later storage failure (the invitation's row) does not lock the address out either."""
    registration = world.registration()
    for _ in range(ADDRESS_ATTEMPTS.limit + 2):
        assert isinstance(registration.register(request()), Registered)
        registration.give_back(" Visitor@EXAMPLE.com ")

    assert world.address_limiter.refunded == [EMAIL] * (ADDRESS_ATTEMPTS.limit + 2)
    assert world.ip_limiter.refunded == []


def test_give_back_counts_nothing_for_the_allowlist(world: World) -> None:
    world.allowlist = (EMAIL,)

    world.registration().give_back(EMAIL)

    assert world.address_limiter.refunded == []


def test_ip_limit_comes_first(world: World) -> None:
    registration = world.registration()
    for _ in range(IP_ATTEMPTS.limit):
        registration.register(request(email="", consent=False))

    outcome = registration.register(request())

    assert outcome == Refused((Problem.TOO_MANY_ATTEMPTS,))
    assert world.human_check.tokens == []
    assert world.participants.calls == 0
    assert set(world.ip_limiter.keys) == {"192.0.2.10"}


def test_ip_limit_is_per_client_address(world: World) -> None:
    registration = world.registration()
    for _ in range(IP_ATTEMPTS.limit):
        registration.register(request(email="", client_ip="192.0.2.10"))

    assert registered(registration.register(request(client_ip="198.51.100.20")), created=True)


def test_address_limit_after_turnstile(world: World) -> None:
    registration = world.registration()
    for _ in range(ADDRESS_ATTEMPTS.limit):
        assert isinstance(registration.register(request()), Registered)

    outcome = registration.register(request(email="visitor@EXAMPLE.com"))

    assert outcome == Refused((Problem.TOO_MANY_ATTEMPTS,))
    assert world.address_limiter.keys == [EMAIL] * (ADDRESS_ATTEMPTS.limit + 1)


def test_address_counter_does_not_grow_without_turnstile(world: World) -> None:
    """A bot cannot block someone else's address: only requests past Turnstile count."""
    world.human_check = FakeHumanCheck(success=False, hostname=HOST)
    registration = world.registration()
    for _ in range(10):
        registration.register(request())
    for _ in range(10):
        registration.register(request(consent=False))

    assert world.address_limiter.keys == []
    world.human_check.result = FakeHumanCheck(hostname=HOST).result
    assert registered(registration.register(request()), created=True)


# --- the mail domain ---------------------------------------------------------------------------


def test_a_domain_that_takes_no_mail_is_refused(world: World) -> None:
    outcome = world.registration().register(request(email=f" Visitor@{NO_MAIL.upper()} "))

    assert outcome == Refused((Problem.EMAIL_DOMAIN,))
    assert world.participants.calls == 0
    assert world.mail_domains.asked == [NO_MAIL]  # the domain of the normalized address


def test_a_domain_that_takes_mail_registers(world: World) -> None:
    outcome = world.registration().register(request())

    assert registered(outcome, created=True)
    assert world.mail_domains.asked == ["example.com"]


def _many_attempts(world: World) -> None:
    world.ip_limiter = CountingLimiter(0)


def _as_it_is(world: World) -> None:
    """The world stays; the request is wrong."""


def _not_human(world: World) -> None:
    world.human_check = FakeHumanCheck(success=False, hostname=HOST)


def _human_check_down(world: World) -> None:
    world.human_check = FakeHumanCheck(unavailable=True)


def _off_the_allowlist(world: World) -> None:
    world.allowlist = ("tester@example.com",)


def _address_attempts_used(world: World) -> None:
    world.address_limiter = CountingLimiter(0)


@pytest.mark.parametrize(
    ("prepare", "overrides"),
    [
        (_many_attempts, {}),
        (_as_it_is, {"email": "name@example"}),
        (_as_it_is, {"consent": False}),
        (_not_human, {}),
        (_human_check_down, {}),
        (_off_the_allowlist, {}),
        (_address_attempts_used, {}),
    ],
    ids=["ip-limit", "format", "consent", "human-check", "human-check-down", "allowlist", "limit"],
)
def test_the_domain_is_asked_only_past_every_other_check(
    world: World, prepare: object, overrides: dict[str, object]
) -> None:
    """DNS is the slowest check: bots, refused forms and spent limits never reach it."""
    assert callable(prepare)
    prepare(world)

    outcome = world.registration().register(request(**overrides))

    assert not isinstance(outcome, Registered)
    assert world.mail_domains.asked == []
    assert world.participants.calls == 0


def test_an_address_on_the_allowlist_is_checked_too(world: World) -> None:
    world.allowlist = (f"tester@{NO_MAIL}",)

    outcome = world.registration().register(request(email=f"tester@{NO_MAIL}"))

    assert outcome == Refused((Problem.EMAIL_DOMAIN,))
    assert world.mail_domains.asked == [NO_MAIL]


# --- the allowlist of the staging site -----------------------------------------------------


def test_an_address_off_the_allowlist_is_neither_stored_nor_counted(world: World) -> None:
    world.allowlist = ("tester@example.com",)

    outcome = world.registration().register(request())

    assert outcome == NotAllowed()
    assert world.participants.calls == 0
    assert world.address_limiter.keys == []
    assert world.human_check.tokens == ["token"]  # only past the human check


def test_the_allowlist_is_checked_after_the_human_check(world: World) -> None:
    """A bot learns nothing about the list: it does not get past Turnstile."""
    world.allowlist = ("tester@example.com",)
    world.human_check = FakeHumanCheck(success=False, hostname=HOST)

    assert world.registration().register(request()) == Refused((Problem.HUMAN_CHECK_FAILED,))


def test_addresses_on_the_allowlist_are_not_limited_per_address(world: World) -> None:
    """Rehearsals register the same test addresses again and again."""
    world.allowlist = ("visitor@example.com",)
    registration = world.registration()

    outcomes = [
        registration.register(request(email=f"visitor+{number}@example.com"))
        for number in range(ADDRESS_ATTEMPTS.limit + 3)
    ] + [registration.register(request()) for _ in range(ADDRESS_ATTEMPTS.limit + 3)]

    assert all(isinstance(outcome, Registered) for outcome in outcomes)
    assert world.address_limiter.keys == []


def test_log_masks_the_address(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    world.allowlist = ("visitor.secret@example.com",)
    registration = world.registration()

    registration.register(request(email="Visitor.Secret@Example.com"))
    registration.register(request(email="visitor.secret@example.com"))
    registration.register(request(email="visitor.secret@example", consent=False))
    registration.register(request(email="other.secret@example.com"))

    logged = app_log(caplog)
    assert "secret" not in logged.lower()
    assert "v***@example.com" in logged
    assert "o***@example.com" in logged


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("123456789.1234567890", "123456789.1234567890"),
        (" 1.2 ", "1.2"),
        ("", None),
        ("GA1.1.123.456", None),
        ("abc.def", None),
        ("<script>", None),
        ("1" * 60 + "." + "2" * 60, None),
    ],
)
def test_ga_client_id_is_kept_only_in_its_format(value: str, expected: str | None) -> None:
    assert clean_ga_client_id(value) == expected


def test_unique_unsubscribe_ids(world: World) -> None:
    registration = world.registration()
    for number in range(3):
        registration.register(request(email=f"visitor{number}@example.com"))

    ids = {participant.unsubscribe_id for participant in world.participants.saved.values()}
    assert len(ids) == 3
    assert all(isinstance(value, uuid.UUID) for value in ids)
