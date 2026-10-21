"""Redirect mode: with ``REDIRECT_BASE_URL`` every request except /healthz gets a 307.

The same path and query go to the new address unchanged; neither browsers nor caches keep
the answer, because another site will serve this address later.
"""

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from app.adapters.web.redirect import HEALTH_PATH, RedirectEverything, redirect_location
from app.main import create_app
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe

BASE = "https://new.example.com"


@pytest.fixture
def client(make_settings: SettingsFactory) -> Iterator[TestClient]:
    app = create_app(make_settings(REDIRECT_BASE_URL=BASE), db_probe=FakeDatabaseProbe())
    with TestClient(app, follow_redirects=False) as client:
        yield client


@pytest.mark.parametrize(
    "target",
    [
        "/",
        "/privacy",
        "/go/stream",
        "/?utm_source=test&gclid=test",
        "/static/css/site.css",
        "/favicon.ico",
        "/a%20b?x=%2F&y=%D1%97",
        "/healthz/",
        "/path//with//slashes?empty=&flag",
    ],
)
def test_get_is_redirected_with_path_and_query(client: TestClient, target: str) -> None:
    response = client.get(target)

    assert response.status_code == 307
    assert response.headers["location"] == BASE + target
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def test_every_method_is_redirected(client: TestClient, method: str) -> None:
    response = client.request(method, "/register?utm_source=test", content=b"email=a@example.com")

    assert response.status_code == 307  # keeps the method and body; never 301, 302 or 308
    assert response.headers["location"] == f"{BASE}/register?utm_source=test"
    assert response.headers["cache-control"] == "no-store"


def test_redirect_is_never_stored(client: TestClient) -> None:
    response = client.get("/?utm_source=test&gclid=test")

    assert response.headers["cache-control"] == "no-store"
    assert response.content == b""


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_healthz_is_answered_here(client: TestClient, method: str) -> None:
    response = client.request(method, f"{HEALTH_PATH}?probe=1")

    assert response.status_code == 200
    assert "location" not in response.headers
    if method == "GET":
        assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("method", ["GET", "POST", "HEAD"])
def test_redirect_is_noindex_before_launch(client: TestClient, method: str) -> None:
    response = client.request(method, "/privacy?x=1")

    assert response.status_code == 307
    assert response.headers["x-robots-tag"] == "noindex"


def test_redirect_is_indexable_after_launch(make_settings: SettingsFactory) -> None:
    settings = make_settings(REDIRECT_BASE_URL=BASE, INDEXING_ENABLED="true")
    app = create_app(settings, db_probe=FakeDatabaseProbe())

    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/privacy?x=1")

    assert response.status_code == 307
    assert "x-robots-tag" not in response.headers
    assert response.headers["cache-control"] == "no-store"


def test_internationalised_base_goes_out_as_ascii(make_settings: SettingsFactory) -> None:
    app = create_app(
        make_settings(REDIRECT_BASE_URL="https://пошта.укр"), db_probe=FakeDatabaseProbe()
    )

    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/privacy")

    assert response.status_code == 307
    assert response.headers["location"] == "https://xn--80a1acn3a.xn--j1amh/privacy"


def test_trailing_slash_of_the_base_gives_no_double_slash(
    make_settings: SettingsFactory,
) -> None:
    app = create_app(make_settings(REDIRECT_BASE_URL=f"{BASE}/"), db_probe=FakeDatabaseProbe())

    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/privacy?x=1")

    assert response.headers["location"] == f"{BASE}/privacy?x=1"


@pytest.mark.parametrize("value", [None, ""])
def test_without_redirect_base_url_the_site_works(
    make_settings: SettingsFactory, value: str | None
) -> None:
    app = create_app(make_settings(REDIRECT_BASE_URL=value), db_probe=FakeDatabaseProbe())

    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/").status_code == 200
        assert client.get("/privacy").status_code == 200
        assert client.get("/favicon.ico").status_code == 200
        # A path no part of the site serves (the slices add /go/stream and others).
        assert client.get("/no-such-page").status_code == 404


# --- the location itself -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw_path", "query", "expected"),
    [
        (b"/", b"", f"{BASE}/"),
        (b"/a%20b", b"x=1&y=%2F", f"{BASE}/a%20b?x=1&y=%2F"),
        (b"//evil.example.org/x", b"", f"{BASE}//evil.example.org/x"),
        (b"http://evil.example.org/x", b"", f"{BASE}/http://evil.example.org/x"),
        (b"", b"q=1", f"{BASE}/?q=1"),
    ],
)
def test_location_always_stays_on_the_base_host(
    raw_path: bytes, query: bytes, expected: str
) -> None:
    assert redirect_location(BASE, raw_path, query) == expected


async def _not_called(scope: Scope, receive: Receive, send: Send) -> None:
    raise AssertionError("the wrapped application must not be called")


def run_middleware(scope: Scope) -> list[Message]:
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(RedirectEverything(_not_called, base_url=BASE)(scope, receive, send))
    return sent


def http_scope(path: str, query: bytes = b"", raw_path: bytes | None = None) -> Scope:
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "query_string": query,
        "headers": [],
        "server": ("testserver", 80),
        "client": ("192.0.2.10", 5000),
    }
    if raw_path is not None:
        scope["raw_path"] = raw_path
    return scope


def location_of(messages: list[Message]) -> str:
    start = messages[0]
    assert start["type"] == "http.response.start"
    assert start["status"] == 307
    headers = {name.decode(): value.decode("latin-1") for name, value in start["headers"]}
    return headers["location"]


def test_scope_without_raw_path_uses_the_encoded_path() -> None:
    messages = run_middleware(http_scope("/a b/ї", b"x=%2F"))

    assert location_of(messages) == f"{BASE}/a%20b/%D1%97?x=%2F"


def test_raw_path_wins_over_the_decoded_path() -> None:
    messages = run_middleware(http_scope("/a/b", b"", raw_path=b"/a%2Fb"))

    assert location_of(messages) == f"{BASE}/a%2Fb"


def test_health_path_and_other_scopes_pass_through() -> None:
    calls: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        calls.append(scope["type"])

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(message: Message) -> None:
        raise AssertionError("nothing is sent by the middleware itself")

    middleware = RedirectEverything(inner, base_url=BASE)
    asyncio.run(middleware(http_scope(HEALTH_PATH), receive, send))
    asyncio.run(middleware({"type": "lifespan", "asgi": {"version": "3.0"}}, receive, send))

    assert calls == ["http", "lifespan"]
