from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.adapters.web import redirect, routers
from app.adapters.web.routers.health import healthz
from app.adapters.web.routing import discover_routers
from app.main import create_app
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe


def test_health_route_is_the_path_the_redirect_spares() -> None:
    """Renaming the check must not leave the redirect stub redirecting its own health check."""
    paths = [
        route.path
        for router in discover_routers(routers)
        for route in router.routes
        if isinstance(route, APIRoute) and route.endpoint is healthz
    ]

    assert paths == [redirect.HEALTH_PATH]


def test_healthz_answers_head(make_settings: SettingsFactory) -> None:
    """Uptime monitors often probe with HEAD."""
    app = create_app(make_settings(), db_probe=FakeDatabaseProbe())

    with TestClient(app) as client:
        response = client.head("/healthz")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_healthz_ok_with_database(make_settings: SettingsFactory, test_db_url: str) -> None:
    app = create_app(make_settings(DATABASE_URL=test_db_url))

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex"


def test_healthz_fails_without_database(make_settings: SettingsFactory) -> None:
    unreachable = "postgresql://app@127.0.0.1:1/unreachable"
    app = create_app(make_settings(DATABASE_URL=unreachable))

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 503
    assert response.text == '{"status":"unavailable"}'


def test_healthz_reports_probe_failure(make_settings: SettingsFactory) -> None:
    app = create_app(make_settings(), db_probe=FakeDatabaseProbe(available=False))

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert response.headers["cache-control"] == "no-store"
