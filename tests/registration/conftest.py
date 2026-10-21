"""Fixtures of the slice «реєстрація і лист»: the application on the test database with fakes.

DNS is a fake too (``FakeMailDomains``), and a guard fails any query of a real resolver: the
network guard of tests/conftest.py does not stop the UDP queries of ``dnspython``.
"""

from collections.abc import Callable, Iterator, Sequence
from typing import NoReturn

import dns.resolver
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.adapters.registration.keys import MAIL_DOMAINS
from app.main import create_app
from app.services import Override, override
from tests.conftest import SettingsFactory
from tests.fakes import (
    FakeDatabaseProbe,
    FakeEmailSender,
    FakeHumanCheck,
    FixedClock,
    fake_overrides,
)
from tests.registration.helpers import FakeMailDomains, Site

type SiteFactory = Callable[..., Site]


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """A query of a real resolver in a test of the slice fails loudly."""

    def refuse(*args: object, **kwargs: object) -> NoReturn:
        raise RuntimeError("DNS in a test: use FakeMailDomains or a stub resolver")

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", refuse)


@pytest.fixture
def site_factory(
    make_settings: SettingsFactory, test_db_url: str, migrated_engine: Engine
) -> Iterator[SiteFactory]:
    """``site_factory(human_check=…, email_sender=…, clock=…, mail_domains=…, overrides=…, **env)``.

    The application runs on the migrated test database; the environment variables in ``env``
    come on top of the required ones (``None`` removes one).
    """
    clients: list[TestClient] = []

    def build(
        *,
        human_check: FakeHumanCheck | None = None,
        email_sender: FakeEmailSender | None = None,
        clock: FixedClock | None = None,
        mail_domains: FakeMailDomains | None = None,
        overrides: Sequence[Override] = (),
        **env: str | None,
    ) -> Site:
        human = human_check if human_check is not None else FakeHumanCheck()
        sender = email_sender if email_sender is not None else FakeEmailSender()
        fixed = clock if clock is not None else FixedClock()
        domains = mail_domains if mail_domains is not None else FakeMailDomains()
        settings = make_settings(DATABASE_URL=test_db_url, **env)
        app = create_app(
            settings,
            db_probe=FakeDatabaseProbe(),
            overrides=[
                *fake_overrides(clock=fixed, email_sender=sender, human_check=human),
                override(MAIL_DOMAINS, domains),
                *overrides,
            ],
        )
        client = TestClient(app, base_url="https://testserver")
        client.__enter__()
        clients.append(client)
        return Site(client, migrated_engine, settings, human, sender, fixed, domains)

    yield build
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def site(site_factory: SiteFactory) -> Site:
    return site_factory()


type ClientFactory = Callable[..., TestClient]


@pytest.fixture
def client_factory(make_settings: SettingsFactory) -> Iterator[ClientFactory]:
    """``client_factory(clock=…, **env)``: the application without a database, for pages that
    need none (links from emails, calendars)."""
    clients: list[TestClient] = []

    def build(*, clock: FixedClock | None = None, **env: str | None) -> TestClient:
        app = create_app(
            make_settings(**env),
            db_probe=FakeDatabaseProbe(),
            overrides=[*fake_overrides(clock=clock), override(MAIL_DOMAINS, FakeMailDomains())],
        )
        client = TestClient(app, base_url="https://testserver")
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)
