"""Unsubscribing (docs/contract.md, sections 3 and 4; requirements, section 6; copy.md, section 7).

The token is v1's: ``app.core.unsubscribe`` reproduces the contract's reference example, and a
link from an old email of v1 finds the same participant in the shared database. GET only shows
a page; POST from the page's form and the one-click POST of a mail client delete the
participant with everything the database cascades.
"""

import base64
import hashlib
import hmac
import logging
import uuid

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.adapters.db.models import Participant
from app.core.unsubscribe import make_token, read_token
from app.services import PARTICIPANTS, override
from tests import copy_oracle as copy
from tests.conftest import OPTIONAL_ENV, REQUIRED_ENV, ParticipantFactory
from tests.html_tree import normalize
from tests.registration.conftest import SiteFactory
from tests.registration.helpers import (
    Conflicting,
    Failing,
    Site,
    Unavailable,
    app_log,
    links,
    main_of,
    page,
)
from tests.test_contract import reference_token

SECRET = REQUIRED_ENV["UNSUBSCRIBE_SECRET"]
EMAIL = "visitor@example.com"
CONFIRM, DONE, FAILED = copy.section("7.1"), copy.section("7.2"), copy.section("7.3")
TITLE = copy.table(copy.group(copy.section("10"), "Службові сторінки"))["Відписка"]
ONE_CLICK = {"List-Unsubscribe": "One-Click"}
GA4 = {"GA4_MEASUREMENT_ID": OPTIONAL_ENV["GA4_MEASUREMENT_ID"]}

# v1's pinned example (agent-webinar-v1, tests/core/test_unsubscribe.py): the format never drifts.
V1_SECRET = "test-unsubscribe-secret-0123456789abcdef"
V1_ID = uuid.UUID("0123456789abcdef0123456789abcdef")
V1_TOKEN = "0123456789abcdef0123456789abcdef.kX_fckLtX_yJu1UX9FsTzHwSZ_NflbFFdeL5yZnoC8g"


# --- the token ------------------------------------------------------------------------------


def expected_token(unsubscribe_id: uuid.UUID, secret: str) -> str:
    """The format of docs/contract.md, section 4, computed independently of the application."""
    digest = hmac.new(
        secret.encode(), f"unsubscribe:{unsubscribe_id.hex}".encode(), hashlib.sha256
    ).digest()
    return f"{unsubscribe_id.hex}.{base64.urlsafe_b64encode(digest).decode().rstrip('=')}"


def test_the_reference_token_of_the_contract() -> None:
    example = reference_token()

    assert make_token(example.unsubscribe_id, example.secret) == example.token
    assert read_token(example.token, example.secret) == example.unsubscribe_id
    assert read_token(example.token, example.secret + "x") is None


def test_the_pinned_token_of_v1() -> None:
    assert make_token(V1_ID, V1_SECRET) == V1_TOKEN == expected_token(V1_ID, V1_SECRET)
    assert read_token(V1_TOKEN, V1_SECRET) == V1_ID


def test_random_ids_round_trip() -> None:
    for _ in range(20):
        unsubscribe_id = uuid.uuid4()
        token = make_token(unsubscribe_id, SECRET)

        assert token == expected_token(unsubscribe_id, SECRET)
        assert len(token) == 76
        assert read_token(token, SECRET) == unsubscribe_id


def _flip(token: str, position: int) -> str:
    char = token[position]
    return token[:position] + ("a" if char != "a" else "b") + token[position + 1 :]


@pytest.mark.parametrize(
    "token",
    [
        "",
        "garbage",
        V1_TOKEN.replace(".", ""),
        V1_TOKEN.replace(".", "-"),
        V1_TOKEN + ".extra",
        V1_TOKEN + "=",
        V1_TOKEN[:-1],
        _flip(V1_TOKEN, 0),  # another id with the old signature
        _flip(V1_TOKEN, 40),  # a damaged signature
        V1_TOKEN.upper(),
        V1_TOKEN[:32].upper() + V1_TOKEN[32:],
        "g" * 32 + V1_TOKEN[32:],
        V1_TOKEN[:-1] + "ж",
        "." + V1_TOKEN[1:],
        V1_TOKEN * 2,
    ],
)
def test_damaged_tokens_are_rejected(token: str) -> None:
    assert read_token(token, V1_SECRET) is None


# --- the pages ------------------------------------------------------------------------------


@pytest.fixture
def unsubscribing(
    site_factory: SiteFactory, participant_factory: ParticipantFactory
) -> tuple[Site, str]:
    """The site with two participants of v2; the token of ``EMAIL``."""
    created = participant_factory(
        EMAIL, emails={"lesson_invitation": "sent"}, link_tokens=["email"]
    )
    participant_factory("other@example.com")
    return site_factory(**GA4), make_token(created.unsubscribe_id, SECRET)


def path(token: str) -> str:
    return f"/unsubscribe/{token}"


def addresses(site: Site) -> set[str]:
    return {participant.email for participant in site.participants()}


def label_target(text: str, label: str) -> tuple[str, str]:
    """``Залишитися → /`` → (``Залишитися``, ``/``)."""
    name, target = copy.one(text, label).split(" → ")
    return name, target


def assert_service_page(response: httpx.Response) -> None:
    html = page(response)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert [m.attrs["content"] for m in html.find_all("meta", name="robots")] == ["noindex"]
    assert normalize(html.find("title").text_raw()) == TITLE
    assert html.find("body").attrs["data-ga4-id"] == ""  # no Google Analytics with a token
    assert "set-cookie" not in response.headers  # no cookie «src» with the token in it
    assert html.find("footer").find_all("a")


def assert_done_page(response: httpx.Response) -> None:
    content = main_of(response)
    assert content.find("h1").text() == copy.one(DONE, "Заголовок")
    text = content.text()
    for line in copy.labeled(DONE, "Текст"):
        assert line in text
    name, target = label_target(DONE, "Посилання")
    assert links(content) == {
        "edu@cbsystematics.com": "mailto:edu@cbsystematics.com",
        "політики приватності": "/privacy",
        name: target,
    }


def assert_failed_page(response: httpx.Response) -> None:
    content = main_of(response)
    assert content.find("h1").text() == copy.one(FAILED, "Заголовок")
    assert copy.one(FAILED, "Текст") in content.text()
    assert links(content) == {"privacy@pythoncourse.me": "mailto:privacy@pythoncourse.me"}
    assert content.find_all("form") == []


def test_get_asks_for_confirmation_and_changes_nothing(unsubscribing: tuple[Site, str]) -> None:
    site, token = unsubscribing

    first = site.client.get(path(token))
    second = site.client.get(path(token))

    assert first.status_code == second.status_code == 200
    assert_service_page(first)
    content = main_of(first)
    assert content.find("h1").text() == copy.one(CONFIRM, "Заголовок")
    text = content.text()
    for line in copy.labeled(CONFIRM, "Текст"):
        assert line.replace("{email}", EMAIL) in text
    form = content.find("form")
    assert form.attrs["method"] == "post"
    assert form.attrs["action"] == path(token)
    assert form.find("button").text() == copy.one(CONFIRM, "Кнопка")
    name, target = label_target(CONFIRM, "Посилання")
    assert links(content) == {name: target}
    assert addresses(site) == {EMAIL, "other@example.com"}


def test_form_post_removes_the_participant_and_their_rows(unsubscribing: tuple[Site, str]) -> None:
    site, token = unsubscribing

    response = site.client.post(path(token))

    assert response.status_code == 200
    assert_service_page(response)
    assert_done_page(response)
    assert addresses(site) == {"other@example.com"}
    assert site.emails() == []
    assert site.link_tokens() == []


def test_repeated_form_post_is_not_an_error(unsubscribing: tuple[Site, str]) -> None:
    site, token = unsubscribing
    site.client.post(path(token))

    again = site.client.post(path(token))
    after = site.client.get(path(token))

    assert again.status_code == after.status_code == 200
    assert_done_page(again)
    assert_done_page(after)


@pytest.mark.parametrize("multipart", [False, True], ids=["urlencoded", "multipart"])
def test_one_click_removes_without_a_page(unsubscribing: tuple[Site, str], multipart: bool) -> None:
    site, token = unsubscribing
    if multipart:
        response = site.client.post(path(token), files={"List-Unsubscribe": (None, "One-Click")})
    else:
        response = site.client.post(path(token), data=ONE_CLICK)

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    assert addresses(site) == {"other@example.com"}
    assert site.client.post(path(token), data=ONE_CLICK).status_code == 200


@pytest.mark.parametrize(
    "token", ["garbage", "0" * 32 + "." + "A" * 43, "x" * 500], ids=["short", "forged", "long"]
)
def test_invalid_token_page(unsubscribing: tuple[Site, str], token: str) -> None:
    site, _ = unsubscribing

    for response in (site.client.get(path(token)), site.client.post(path(token))):
        assert response.status_code == 400
        assert_service_page(response)
        assert_failed_page(response)
    assert len(site.participants()) == 2


def test_damaged_signature_is_refused_to_one_click(unsubscribing: tuple[Site, str]) -> None:
    site, token = unsubscribing

    response = site.client.post(path(_flip(token, 40)), data=ONE_CLICK)

    assert response.status_code == 400
    assert response.content == b""
    assert len(site.participants()) == 2


@pytest.mark.parametrize(
    ("store", "error", "level"),
    [
        (Unavailable, "StorageUnavailable", logging.WARNING),
        (Conflicting, "StorageConflict", logging.ERROR),
        (Failing, "StorageError", logging.ERROR),
    ],
    ids=["unavailable", "conflict", "other"],
)
def test_any_storage_failure_is_503_with_the_address_for_a_manual_request(
    site_factory: SiteFactory,
    caplog: pytest.LogCaptureFixture,
    store: type,
    error: str,
    level: int,
) -> None:
    """As in v1: whatever the database failure, the page of 7.3 names the address to write to.

    A failure other than an outage is a bug here (nothing to conflict with on a delete): the log
    says so at the level of an error, with the class only.
    """
    site = site_factory(overrides=[override(PARTICIPANTS, store())])
    token = make_token(uuid.uuid4(), SECRET)

    shown = site.client.get(path(token))
    form = site.client.post(path(token))
    one_click = site.client.post(path(token), data=ONE_CLICK)

    assert shown.status_code == form.status_code == one_click.status_code == 503
    assert_failed_page(shown)
    assert_failed_page(form)
    assert one_click.content == b""
    logged = [
        (record.levelno, record.getMessage())
        for record in caplog.records
        if record.name.startswith("app.adapters.web") and record.levelno >= logging.WARNING
    ]
    assert logged == [(level, f"Unsubscribe failed: {error}")] * 3


def test_pages_stay_noindex_after_launch(site_factory: SiteFactory) -> None:
    site = site_factory(INDEXING_ENABLED="true")

    response = site.client.get(path("garbage"))

    assert response.headers["x-robots-tag"] == "noindex"
    assert [m.attrs["content"] for m in page(response).find_all("meta", name="robots")] == [
        "noindex"
    ]


def test_a_link_from_an_old_email_of_v1_finds_the_same_participant(
    site_factory: SiteFactory, participant_factory: ParticipantFactory
) -> None:
    """The reference token was computed by v1's ``make_token``; the database is shared."""
    example = reference_token()
    created = participant_factory(
        "from-v1@example.com", origin=None, emails={"confirmation": "sent"}, link_tokens=["email"]
    )
    participant_factory("other@example.com")
    site = site_factory(UNSUBSCRIBE_SECRET=example.secret)
    with Session(site.engine) as session, session.begin():
        session.execute(
            update(Participant)
            .where(Participant.id == created.id)
            .values(unsubscribe_id=example.unsubscribe_id)
        )

    shown = site.client.get(path(example.token))
    removed = site.client.post(path(example.token), data=ONE_CLICK)

    assert shown.status_code == 200
    assert "from-v1@example.com" in main_of(shown).text()
    assert removed.status_code == 200
    assert addresses(site) == {"other@example.com"}
    assert site.emails() == []
    assert site.link_tokens() == []


def test_log_has_neither_the_token_nor_the_address(
    unsubscribing: tuple[Site, str], caplog: pytest.LogCaptureFixture
) -> None:
    site, token = unsubscribing
    caplog.set_level(logging.DEBUG)

    site.client.get(path(token))
    site.client.post(path(token))
    site.client.post(path(token), data=ONE_CLICK)
    site.client.get(path("garbage"))

    logged = app_log(caplog)
    assert "Unsubscribe: participant removed" in logged
    assert token.split(".")[0] not in logged
    assert token.split(".")[1] not in logged
    assert EMAIL not in logged
