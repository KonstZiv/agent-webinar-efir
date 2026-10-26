"""Fixtures of the slice «course»: the application on the test database, with fakes.

The page of the course posts to ``/register``, so its tests run the real stores of participants
and link tokens with the fakes of Turnstile, Resend and the clock (tests/fakes.py). DNS is a fake
too: the key is named, not imported, because slices do not import each other (not in tests either).
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.adapters.db.models import Participant
from app.main import create_app
from app.services import Key, override
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe, fake_overrides

VALID = {"email": "visitor@example.com", "consent": "yes", "cf-turnstile-response": "tok"}


class AnyDomain:
    """``MailDomains`` without DNS: every domain takes mail."""

    def accepts_mail(self, domain: str) -> bool:
        return True


MAIL_DOMAINS = Key[AnyDomain]("registration.mail_domains")


@dataclass
class Site:
    client: TestClient
    engine: Engine

    def register(self, *, htmx: bool = True) -> httpx.Response:
        """``POST /register`` with a valid form."""
        return self.client.post(
            "/register", data=VALID, headers={"HX-Request": "true"} if htmx else {}
        )

    def refuse(self, *, htmx: bool = True, **form: str) -> httpx.Response:
        """``POST /register`` with an empty email (a validation problem) and the extra ``form``."""
        data = {**VALID, "email": "", **form}
        headers = {"HX-Request": "true"} if htmx else {}
        return self.client.post("/register", data=data, headers=headers)

    def participants(self) -> list[Participant]:
        with Session(self.engine) as session:
            return list(session.scalars(select(Participant).order_by(Participant.id)))


type SiteFactory = Callable[..., Site]


@pytest.fixture
def site_factory(
    make_settings: SettingsFactory, test_db_url: str, migrated_engine: Engine
) -> Iterator[SiteFactory]:
    """``site_factory(**env)``: the application in the mode the variables ``env`` set."""
    clients: list[TestClient] = []

    def build(**env: str) -> Site:
        app = create_app(
            make_settings(DATABASE_URL=test_db_url, **env),
            db_probe=FakeDatabaseProbe(),
            overrides=[*fake_overrides(), override(MAIL_DOMAINS, AnyDomain())],
        )
        client = TestClient(app, base_url="https://testserver")
        client.__enter__()
        clients.append(client)
        return Site(client, migrated_engine)

    yield build
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def site(site_factory: SiteFactory) -> Site:
    return site_factory()
