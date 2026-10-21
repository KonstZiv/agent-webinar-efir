"""Cookie ``src``: where the visitor came from (requirements, section 5; contract, section 10).

Set on the first HTML page a browser opens and never overwritten while it lives; the
registration reads it. Name and format are v1's: host-only, ``HttpOnly``, 30 days, base64url of
compact JSON. Pages with a token in the path never set it. Ported from v1
(tests/web/test_source_cookie.py).
"""

import base64
import json
from http.cookies import SimpleCookie

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.registration.source import (
    MAX_COOKIE_LENGTH,
    SOURCE_COOKIE,
    SOURCE_FIELDS,
    decode_source,
    encode_source,
)
from app.core.entities import TrafficSource
from tests.registration.conftest import ClientFactory

THIRTY_DAYS = 30 * 24 * 60 * 60
SITE = "https://agent.pythoncourse.me"


@pytest.fixture
def client(client_factory: ClientFactory) -> TestClient:
    client = client_factory()
    client.base_url = SITE  # type: ignore[assignment]
    return client


def source_cookies(response: httpx.Response) -> list[SimpleCookie]:
    cookies = []
    for header in response.headers.get_list("set-cookie"):
        cookie: SimpleCookie = SimpleCookie()
        cookie.load(header)
        if SOURCE_COOKIE in cookie:
            cookies.append(cookie)
    return cookies


def test_the_name_is_v1s() -> None:
    assert SOURCE_COOKIE == "src"


def test_first_page_sets_the_source(client: TestClient) -> None:
    response = client.get(
        "/?utm_source=telegram&utm_medium=post&utm_campaign=webinar&utm_term=agents"
        "&utm_content=pinned&gclid=g1&gbraid=g2&wbraid=g3&other=x",
        headers={"Referer": "https://t.me/agentic_engineers"},
    )

    [cookie] = source_cookies(response)
    morsel = cookie[SOURCE_COOKIE]
    assert morsel["httponly"] is True
    assert morsel["secure"] is True
    assert morsel["samesite"].lower() == "lax"
    assert morsel["path"] == "/"
    assert morsel["domain"] == ""  # host-only
    assert int(morsel["max-age"]) == THIRTY_DAYS
    assert decode_source(morsel.value) == TrafficSource(
        utm_source="telegram",
        utm_medium="post",
        utm_campaign="webinar",
        utm_term="agents",
        utm_content="pinned",
        gclid="g1",
        gbraid="g2",
        wbraid="g3",
        landing_url=(
            f"{SITE}/?utm_source=telegram&utm_medium=post&utm_campaign=webinar&utm_term=agents"
            "&utm_content=pinned&gclid=g1&gbraid=g2&wbraid=g3&other=x"
        ),
        referrer="https://t.me/agentic_engineers",
    )


def test_values_are_cut_to_500_characters(client: TestClient) -> None:
    response = client.get("/?utm_source=" + "s" * 700, headers={"Referer": "r" * 700})

    [cookie] = source_cookies(response)
    source = decode_source(cookie[SOURCE_COOKIE].value)
    assert source.utm_source == "s" * 500
    assert source.referrer == "r" * 500
    assert source.landing_url is not None and len(source.landing_url) == 500


def test_existing_source_is_not_overwritten(client: TestClient) -> None:
    assert source_cookies(client.get("/?utm_source=first"))

    for path in ("/?utm_source=second", "/privacy", "/go/stream"):
        assert source_cookies(client.get(path)) == []
    assert decode_source(client.cookies[SOURCE_COOKIE]).utm_source == "first"


@pytest.mark.parametrize("path", ["/privacy", "/go/stream", "/go/lesson"])
def test_any_html_page_can_be_the_first(client: TestClient, path: str) -> None:
    assert source_cookies(client.get(path + "?utm_source=x"))


@pytest.mark.parametrize(
    "path", ["/unsubscribe/garbage?utm_source=x", "/m/Materials_Slug-01?utm_source=x"]
)
def test_pages_with_a_token_never_set_it(client_factory: ClientFactory, path: str) -> None:
    """The landing address would carry the token into the participant's row."""
    client = client_factory(MATERIALS_SLUG="Materials_Slug-01")

    assert source_cookies(client.get(path)) == []


def test_non_html_and_non_get_responses_do_not_set_it(client_factory: ClientFactory) -> None:
    client = client_factory(STREAM_URL="https://youtube.com/live/x")
    for response in (
        client.get("/go/stream", follow_redirects=False),
        client.get("/healthz"),
        client.get("/static/css/site.css"),
        client.get("/calendar.ics"),
        client.get("/register", follow_redirects=False),
        client.head("/"),
    ):
        assert source_cookies(response) == [], response.request.url


def test_oversized_source_is_shortened_not_dropped(client: TestClient) -> None:
    """Without the cookie the next page would pass for the first one, minus UTM."""
    names = ("utm_source", "utm_medium", "utm_term", "gclid")
    query = "&".join(f"{name}={name[0] + 'я' * 499}" for name in names)

    response = client.get("/?" + query, headers={"Referer": "https://t.me/" + "r" * 600})

    [cookie] = source_cookies(response)
    value = cookie[SOURCE_COOKIE].value
    assert len(value) <= MAX_COOKIE_LENGTH
    source = decode_source(value)
    for name in names:
        kept = getattr(source, name)
        assert kept is not None and kept.startswith(name[0] + "я"), name
        assert len(kept) < 500, name
    assert source.referrer is not None and source.referrer.startswith("https://t.me/")


def test_every_source_fits_into_the_cookie() -> None:
    worst = TrafficSource(**dict.fromkeys(SOURCE_FIELDS, "я" * 500))

    value = encode_source(worst)

    assert len(value) <= MAX_COOKIE_LENGTH
    shortened = decode_source(value)
    assert all(getattr(shortened, name) for name in SOURCE_FIELDS)


def test_a_source_that_fits_is_kept_whole() -> None:
    source = TrafficSource(utm_source="s" * 500, landing_url="https://example.com/" + "p" * 480)

    assert decode_source(encode_source(source)) == source


def test_encoding_round_trip_and_size_limit() -> None:
    source = TrafficSource(utm_source="telegram", referrer="https://t.me/«канал»")

    encoded = encode_source(source)

    assert encoded.isascii() and ";" not in encoded and "," not in encoded and " " not in encoded
    assert decode_source(encoded) == source
    assert MAX_COOKIE_LENGTH == 3800


def as_cookie(payload: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, TrafficSource()),
        ("", TrafficSource()),
        ("%%%", TrafficSource()),
        (as_cookie(["utm_source", "x"]), TrafficSource()),
        (as_cookie("text"), TrafficSource()),
        (
            as_cookie({"utm_source": "x", "unknown": "y", "gclid": 5}),
            TrafficSource(utm_source="x"),
        ),
        (as_cookie({"utm_source": "x" * 900}), TrafficSource(utm_source="x" * 500)),
        (as_cookie({"utm_source": "tele\u0000gram"}), TrafficSource(utm_source="telegram")),
        (base64.urlsafe_b64encode(b"\xff\xfe").decode(), TrafficSource()),
    ],
)
def test_damaged_values_are_ignored(value: str | None, expected: TrafficSource) -> None:
    assert decode_source(value) == expected
