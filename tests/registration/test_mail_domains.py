"""Whether a mail domain takes mail: ``DnsMailDomains`` (docs/requirements.md, section 5).

MX, or A or AAAA without MX, by ``email-validator``. A domain that does not exist or takes no
mail is refused; a timeout or a failure of DNS gives no verdict, and the address is taken. The
whole check has 2 seconds. The resolver here is a stub: no test asks DNS.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass

import dns.exception
import dns.name
import dns.rdataclass
import dns.rdatatype
import dns.resolver
import pytest

from app.adapters.registration.mail_domains import DNS_TIMEOUT, DnsMailDomains

DOMAIN = "mail.example.com"
LOGGER = "app.adapters.registration.mail_domains"


@dataclass(frozen=True)
class Mx:
    preference: int
    exchange: str


@dataclass(frozen=True)
class Address:
    address: str


@dataclass(frozen=True)
class Txt:
    strings: tuple[bytes, ...]


class Clock:
    """``time.monotonic`` of the tests: stands still unless a query takes time."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


type Reply = Iterable[object] | Exception


class StubResolver(dns.resolver.Resolver):
    """Answers each record type from ``replies``; a missing type is ``NoAnswer``.

    Every query takes ``delay`` seconds of ``clock``; ``asked`` — the types and lifetimes.
    """

    def __init__(self, replies: dict[str, Reply], clock: Clock, delay: float = 0.0) -> None:
        super().__init__(configure=False)
        self.replies = replies
        self.clock = clock
        self.delay = delay
        self.asked: list[tuple[str, float | None]] = []

    def resolve(  # type: ignore[override]
        self,
        qname: dns.name.Name | str,
        rdtype: dns.rdatatype.RdataType | str = dns.rdatatype.A,
        rdclass: dns.rdataclass.RdataClass | str = dns.rdataclass.IN,
        tcp: bool = False,
        source: str | None = None,
        raise_on_no_answer: bool = True,
        source_port: int = 0,
        lifetime: float | None = None,
        search: bool | None = None,
    ) -> object:
        assert str(qname) == DOMAIN
        self.asked.append((str(rdtype), lifetime))
        self.clock.now += self.delay
        reply = self.replies.get(str(rdtype), dns.resolver.NoAnswer())
        if isinstance(reply, Exception):
            raise reply
        return reply


def check(replies: dict[str, Reply], *, delay: float = 0.0) -> tuple[bool, StubResolver]:
    clock = Clock()
    resolver = StubResolver(replies, clock, delay)
    verdict = DnsMailDomains(resolver, monotonic=clock).accepts_mail(DOMAIN)
    return verdict, resolver


def kinds(resolver: StubResolver) -> list[str]:
    return [kind for kind, _ in resolver.asked]


def test_a_domain_with_mx_takes_mail() -> None:
    verdict, resolver = check({"MX": [Mx(10, "mx1.example.com.")]})

    assert verdict is True
    assert resolver.asked == [("MX", DNS_TIMEOUT)]


@pytest.mark.parametrize(
    ("replies", "asked"),
    [
        ({"MX": [Mx(0, ".")]}, ["MX"]),  # Null MX (RFC 7505)
        ({"MX": dns.resolver.NXDOMAIN()}, ["MX"]),
        ({}, ["MX", "A", "AAAA"]),  # no MX, A or AAAA
        ({"A": [Address("192.0.2.1")]}, ["MX", "A", "AAAA"]),  # documentation range, not global
        ({"A": [Address("93.184.215.14")], "TXT": [Txt((b"v=spf1 -all",))]}, ["MX", "A", "TXT"]),
    ],
    ids=["null-mx", "no-such-domain", "no-records", "no-global-address", "spf-reject-all"],
)
def test_a_domain_that_takes_no_mail_is_refused(
    replies: dict[str, Reply], asked: list[str]
) -> None:
    verdict, resolver = check(replies)

    assert verdict is False
    assert kinds(resolver) == asked


def test_without_mx_an_address_record_will_do() -> None:
    verdict, resolver = check({"A": [Address("93.184.215.14")]})

    assert verdict is True
    assert kinds(resolver) == ["MX", "A", "TXT"]


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (dns.exception.Timeout(), "timeout"),
        (dns.resolver.NoNameservers(), "no_nameservers"),
        (OSError("network is unreachable"), "OSError"),
        (ValueError("odd answer"), "ValueError"),
    ],
    ids=["timeout", "no-nameservers", "network", "unexpected"],
)
def test_without_a_verdict_the_address_is_taken(
    caplog: pytest.LogCaptureFixture, failure: Exception, reason: str
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER)

    verdict, _ = check({"MX": failure})

    assert verdict is True
    [record] = [record for record in caplog.records if record.name == LOGGER]
    assert reason in record.getMessage()
    assert DOMAIN not in record.getMessage()  # neither the address nor its domain


def test_every_query_has_what_is_left_of_the_two_seconds() -> None:
    verdict, resolver = check({"A": [Address("93.184.215.14")]}, delay=0.5)

    assert verdict is True
    assert resolver.asked == [("MX", 2.0), ("A", 1.5), ("TXT", 1.0)]


def test_after_two_seconds_no_more_queries_and_the_address_is_taken() -> None:
    verdict, resolver = check({"A": [Address("93.184.215.14")]}, delay=DNS_TIMEOUT + 0.1)

    assert verdict is True
    assert kinds(resolver) == ["MX"]
