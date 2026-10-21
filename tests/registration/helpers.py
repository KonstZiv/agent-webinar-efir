"""Helpers of the slice tests: the application on the test database, its rows, broken stores.

``Site`` is the application of ``create_app`` on the migrated test database: the stores of
participants and link tokens are real, Turnstile, Resend and the clock are fakes
(tests/fakes.py), and so is DNS (``FakeMailDomains``). Addresses are ``…@example.com`` only.
"""

import re
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, func, select, text, update
from sqlalchemy.orm import Session

from app.adapters.db.models import EmailRecord, LinkToken, Participant
from app.core.ports import StorageConflict, StorageError, StorageUnavailable
from app.settings import Settings
from tests.fakes import FakeEmailSender, FakeHumanCheck, FixedClock
from tests.html_tree import Node, parse

HTMX = {"HX-Request": "true"}
CONSENT = "yes"  # the value of the consent checkbox
VALID = {"email": " Visitor@Example.com ", "consent": CONSENT, "cf-turnstile-response": "tok"}
EMAIL = "visitor@example.com"
BOT = "sentinel_webinar_bot"  # TELEGRAM_BOT_USERNAME of tests/conftest.py, BOT_ENV
NO_MAIL = "no-mail.example.com"  # a domain that FakeMailDomains(refused=[NO_MAIL]) refuses


class FakeMailDomains:
    """``MailDomains`` without DNS: every domain takes mail but the ``refused`` ones.

    ``asked`` — the domains checked, in order. Slice tests never ask DNS: ``example.com``
    publishes a Null MX, so a real check would refuse every address of the tests.
    """

    def __init__(self, refused: Collection[str] = ()) -> None:
        self.refused = frozenset(refused)
        self.asked: list[str] = []

    def accepts_mail(self, domain: str) -> bool:
        self.asked.append(domain)
        return domain not in self.refused


@dataclass
class Site:
    client: TestClient
    engine: Engine
    settings: Settings
    human_check: FakeHumanCheck
    email_sender: FakeEmailSender
    clock: FixedClock
    mail_domains: FakeMailDomains

    def register(
        self,
        data: dict[str, str] | None = None,
        *,
        htmx: bool = True,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """``POST /register`` with the valid form unless ``data`` is given."""
        return self.client.post(
            "/register",
            data=VALID if data is None else data,
            headers={**(HTMX if htmx else {}), **(headers or {})},
        )

    def participants(self) -> list[Participant]:
        return rows(self.engine, Participant)

    def emails(self) -> list[EmailRecord]:
        return rows(self.engine, EmailRecord)

    def link_tokens(self) -> list[LinkToken]:
        return rows(self.engine, LinkToken)


def rows[T: (Participant, EmailRecord, LinkToken)](engine: Engine, model: type[T]) -> list[T]:
    """Every row of ``model``'s table, in the order of insertion."""
    with Session(engine) as session:
        return list(session.scalars(select(model).order_by(model.id)))


class Unavailable:
    """A store whose every method raises ``StorageUnavailable``: the database is down."""

    def __getattr__(self, name: str) -> Any:
        def fail(*args: object, **kwargs: object) -> None:
            raise StorageUnavailable(name)

        return fail


class Conflicting:
    """A store whose every method raises ``StorageConflict``."""

    def __getattr__(self, name: str) -> Any:
        def fail(*args: object, **kwargs: object) -> None:
            raise StorageConflict(name)

        return fail


class Failing:
    """A store whose every method raises a bare ``StorageError``: a bug, not an outage."""

    def __getattr__(self, name: str) -> Any:
        def fail(*args: object, **kwargs: object) -> None:
            raise StorageError(name)

        return fail


def app_log(caplog: pytest.LogCaptureFixture) -> str:
    """What the application logged; the test client logs full request URLs on its own."""
    return "\n".join(
        record.getMessage() for record in caplog.records if record.name.startswith("app.")
    )


def page(response: httpx.Response) -> Node:
    return parse(response.text)


def main_of(response: httpx.Response) -> Node:
    return parse(response.text).find("main")


def links(node: Node) -> dict[str, str | None]:
    """Link texts and their targets."""
    return {a.text(): a.attrs.get("href") for a in node.find_all("a")}


def quotes(section_text: str) -> list[list[str]]:
    """Every block quote of a copy.md section as its lines, without the ``> `` marks."""
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in section_text.splitlines():
        if line.startswith(">"):
            if current is None:
                current = []
                blocks.append(current)
            current.append(re.sub(r"^> ?", "", line))
        else:
            current = None
    return blocks


@contextmanager
def captured_sql(engine: Engine) -> Iterator[list[str]]:
    """Every statement ``engine`` sends to PostgreSQL while the context is open."""
    statements: list[str] = []

    def capture(*args: object) -> None:
        statements.append(str(args[2]))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def age_emails(engine: Engine, minutes: int) -> None:
    """Make every email row look ``minutes`` old by the database clock, as ``updated_at`` uses."""
    with engine.begin() as connection:
        connection.execute(
            update(EmailRecord).values(
                updated_at=func.now() - text(f"interval '{minutes} minutes'")
            )
        )
