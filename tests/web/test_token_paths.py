"""One list of path prefixes whose next segment is a secret token (no drifting copies).

Routes with a ``{token}`` parameter, the access log and the analytics switch all follow it.
The template has no such routes yet, so the list is empty; the checks still run.
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


def test_the_template_has_no_token_paths_yet() -> None:
    assert TOKEN_PATH_PREFIXES == ()
    assert not carries_token("/t/abc")


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
