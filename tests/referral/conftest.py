"""Fixtures of the feature Ф1: the application on the test database, with fake ports.

DNS is a fake too: ``example.com`` publishes a Null MX, so a real check would refuse every
address of the tests.
"""

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.adapters.db.models import Participant
from app.main import create_app
from app.services import Key, override
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe, FixedClock, fake_overrides

HTMX = {"HX-Request": "true"}
BASE_URL = "https://public-sentinel.example.com"  # PUBLIC_BASE_URL of tests/conftest.py


# The key of the registration's DNS check: named here, not imported (slices do not import).
MAIL_DOMAINS = Key[object]("registration.mail_domains")


class AcceptingMailDomains:
    """``MailDomains`` without DNS: every domain takes mail."""

    def accepts_mail(self, domain: str) -> bool:
        return True


@dataclass
class Site:
    client: TestClient
    engine: Engine

    def register(self, email: str, *, ref: str | None = None) -> str:
        """``POST /register`` as the form does; ``ref`` is the value of the cookie ``ref``."""
        self.client.cookies.clear()
        if ref is not None:
            self.client.cookies.set("ref", ref)
        response = self.client.post(
            "/register",
            data={"email": email, "consent": "yes", "cf-turnstile-response": "tok"},
            headers=HTMX,
        )
        assert response.status_code == 200, response.text
        return response.text

    def row(self, email: str) -> Participant:
        with Session(self.engine) as session:
            return session.scalars(select(Participant).where(Participant.email == email)).one()


@pytest.fixture
def site(
    make_settings: SettingsFactory, test_db_url: str, migrated_engine: Engine
) -> Iterator[Site]:
    app = create_app(
        make_settings(DATABASE_URL=test_db_url),
        db_probe=FakeDatabaseProbe(),
        overrides=[
            *fake_overrides(clock=FixedClock()),
            override(MAIL_DOMAINS, AcceptingMailDomains()),
        ],
    )
    with TestClient(app, base_url="https://testserver") as client:
        yield Site(client, migrated_engine)
