"""One list of path prefixes whose next segment is a secret token (no drifting copies).

Routes with a ``{token}`` parameter, the access log and the analytics switch all follow it.
The foundation lists ``/unsubscribe/`` before its route exists (docs/contract.md, section 10)
and ``/m/``, the materials page whose address only the bot gives.
"""

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.adapters.web import routers, token_paths
from app.adapters.web.routing import discover_routers
from app.adapters.web.token_paths import TOKEN_PATH_PREFIXES, carries_token
from app.main import create_app
from tests.conftest import OPTIONAL_ENV, SettingsFactory
from tests.fakes import FakeDatabaseProbe
from tests.html_tree import parse


def token_routes_outside(routers_: list[APIRouter], prefixes: tuple[str, ...]) -> list[str]:
    """Paths of routes that take a ``{token}`` but are not under one of ``prefixes``."""
    return [
        route.path
        for router in routers_
        for route in router.routes
        if isinstance(route, APIRoute)
        and "{token}" in route.path
        and not carries_token(route.path, prefixes)
    ]


def test_unsubscribe_and_materials_are_token_paths() -> None:
    assert TOKEN_PATH_PREFIXES == ("/unsubscribe/", "/m/")
    assert carries_token("/unsubscribe/abc.def")
    assert carries_token("/m/Secret_Slug-01")
    assert not carries_token("/materials")
    assert not carries_token("/")


def test_carries_token() -> None:
    assert carries_token("/t/abc", ("/t/",))
    assert not carries_token("/t", ("/t/",))
    assert not carries_token("/privacy", ("/t/",))


def test_every_token_route_sits_under_a_prefix() -> None:
    assert token_routes_outside(discover_routers(routers), TOKEN_PATH_PREFIXES) == []


def test_the_check_finds_a_token_route_outside_the_prefixes() -> None:
    router = APIRouter()
    router.add_api_route("/t/{token}", lambda token: token)
    router.add_api_route("/other/{token}", lambda token: token)

    assert token_routes_outside([router], ("/t/",)) == ["/other/{token}"]


@pytest.mark.parametrize(("prefixes", "ga4_id"), [((), "G-SENTINEL01"), (("/privacy",), "")])
def test_pages_under_a_token_prefix_load_no_analytics(
    make_settings: SettingsFactory,
    monkeypatch: pytest.MonkeyPatch,
    prefixes: tuple[str, ...],
    ga4_id: str,
) -> None:
    """Google would receive the token with the page address."""
    monkeypatch.setattr(token_paths, "TOKEN_PATH_PREFIXES", prefixes)
    app = create_app(make_settings(**OPTIONAL_ENV), db_probe=FakeDatabaseProbe())

    with TestClient(app) as client:
        page = parse(client.get("/privacy").text)

    assert page.find("body").attrs["data-ga4-id"] == ga4_id


SLUG = "Materials_Slug-01"


@pytest.mark.parametrize(
    ("path", "statuses"),
    [
        (f"/m/{SLUG}", {200}),
        ("/m/wrong-slug", {404}),
        # 404 until the slice «реєстрація і лист» adds the route, then 400 for a forged token.
        ("/unsubscribe/abc.def", {400, 404}),
    ],
)
def test_pages_under_a_token_prefix_send_no_referrer(
    make_settings: SettingsFactory, path: str, statuses: set[int]
) -> None:
    """A click from such a page to another page of the site must not carry the token along.

    The same origin would get the full address in ``Referer``, and analytics there would
    report it to Google as the referring page.
    """
    app = create_app(make_settings(MATERIALS_SLUG=SLUG), db_probe=FakeDatabaseProbe())

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code in statuses
    assert response.headers["Referrer-Policy"] == "no-referrer"


@pytest.mark.parametrize("prefix", TOKEN_PATH_PREFIXES)
def test_every_token_prefix_sends_no_referrer(make_settings: SettingsFactory, prefix: str) -> None:
    with TestClient(create_app(make_settings(), db_probe=FakeDatabaseProbe())) as client:
        response = client.get(f"{prefix}token")

    assert response.headers["Referrer-Policy"] == "no-referrer"


@pytest.mark.parametrize("path", ["/", "/privacy", "/healthz"])
def test_other_pages_keep_the_default_policy(make_settings: SettingsFactory, path: str) -> None:
    with TestClient(create_app(make_settings(), db_probe=FakeDatabaseProbe())) as client:
        response = client.get(path)

    assert "Referrer-Policy" not in response.headers
