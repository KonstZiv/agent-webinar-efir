"""Whether the domain of an address takes mail (``MailDomains`` port): DNS by ``email-validator``.

docs/requirements.md, section 5, «Поштовий домен». The library's check of deliverability asks
for MX and, without MX, for A or AAAA with a global address; it is run for the domain alone, so
the address keeps the syntax and the normalization of v1. Refused: a domain that does not exist
(NXDOMAIN), takes no mail (Null MX; no MX, A or AAAA) or, without MX, rejects all mail by SPF
(``v=spf1 -all``). A timeout, nameservers that fail, or any other error give no verdict: the
address is taken, so a lead is not lost to the network, and the log says why — never the address
or its domain.

The call is synchronous, in the thread of the request: ``/register`` is a ``def`` route, and the
check runs last, past Turnstile and the limits. One resolver with a cache serves the application,
so frequent domains are answered without the network; the whole check has ``DNS_TIMEOUT``
seconds, however many queries it makes.
"""

import logging
import time
from collections.abc import Callable

import dns.exception
import dns.name
import dns.rdataclass
import dns.rdatatype
import dns.resolver
from email_validator import EmailUndeliverableError, caching_resolver
from email_validator.deliverability import validate_email_deliverability

logger = logging.getLogger(__name__)

DNS_TIMEOUT = 2  # seconds for the whole check (requirements, section 5)
# What the library refuses a domain for, when it says why: the domain has no such records.
_VERDICTS = (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer)


class _Deadline(dns.resolver.Resolver):
    """The resolver of one check: the queries share one deadline on the shared resolver.

    Past the deadline a query is not sent: ``Timeout``, which the library takes for no verdict.
    """

    def __init__(
        self, shared: dns.resolver.Resolver, timeout: float, monotonic: Callable[[], float]
    ) -> None:
        super().__init__(configure=False)
        self._shared = shared
        self._monotonic = monotonic
        self._deadline = monotonic() + timeout

    def resolve(
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
    ) -> dns.resolver.Answer:
        left = self._deadline - self._monotonic()
        if left <= 0:
            raise dns.exception.Timeout
        return self._shared.resolve(
            qname,
            rdtype,
            rdclass,
            tcp,
            source,
            raise_on_no_answer,
            source_port,
            left if lifetime is None else min(lifetime, left),
            search,
        )


class DnsMailDomains:
    """Asks DNS whether a domain takes mail; ``resolver`` — the shared one, with its cache."""

    def __init__(
        self,
        resolver: dns.resolver.Resolver | None = None,
        *,
        timeout: float = DNS_TIMEOUT,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._resolver = resolver if resolver is not None else caching_resolver(timeout=DNS_TIMEOUT)
        self._timeout = timeout
        self._monotonic = monotonic

    def accepts_mail(self, domain: str) -> bool:
        lookup = _Deadline(self._resolver, self._timeout, self._monotonic)
        try:
            info = validate_email_deliverability(domain, domain, dns_resolver=lookup)
        except EmailUndeliverableError as error:
            cause = error.__cause__
            if cause is None or isinstance(cause, _VERDICTS):
                return False
            # The library turns any other error into «undeliverable»; it is no verdict.
            return self._no_verdict(type(cause).__name__)
        if (reason := info.get("unknown-deliverability")) is not None:
            return self._no_verdict(reason)  # a timeout, or no nameserver answered
        return True

    @staticmethod
    def _no_verdict(reason: str) -> bool:
        logger.warning("Mail domain check gave no verdict (%s): the address is taken", reason)
        return True
