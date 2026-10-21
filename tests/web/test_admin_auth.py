"""Admin access: ``Authorization: Bearer <ADMIN_TOKEN>`` (docs/contract.md, section 8).

The slices «реєстрація і лист» and «лічильники й експорт» put ``AdminDep`` on their admin
routes. Every refusal is the same 401; the token is compared in constant time and never logged.
"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.web.admin_auth import AdminDep, bearer_token, is_admin_token
from app.main import create_app
from tests.conftest import REQUIRED_ENV, SettingsFactory
from tests.fakes import FakeDatabaseProbe

TOKEN = REQUIRED_ENV["ADMIN_TOKEN"]


def admin_app(app: FastAPI) -> FastAPI:
    @app.get("/admin/probe")
    def probe(_: AdminDep) -> dict[str, str]:
        return {"status": "ok"}

    return app


@pytest.fixture
def client(make_settings: SettingsFactory) -> Iterator[TestClient]:
    app = admin_app(create_app(make_settings(), db_probe=FakeDatabaseProbe()))
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER"])
def test_the_admin_token_opens_the_route(client: TestClient, scheme: str) -> None:
    response = client.get("/admin/probe", headers={"Authorization": f"{scheme} {TOKEN}"})

    assert (response.status_code, response.json()) == (200, {"status": "ok"})


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-token-0123456789abcdef0123456789"},
        {"Authorization": f"Bearer {TOKEN}x"},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": "Bearer "},
        {"Authorization": TOKEN},
        {"Authorization": "Bearer токен-адміністратора".encode()},  # raw UTF-8 bytes
    ],
    ids=["none", "wrong", "longer", "basic", "empty", "no-scheme", "non-ascii"],
)
def test_every_refusal_is_the_same_401(
    client: TestClient, headers: dict[str, str | bytes], caplog: pytest.LogCaptureFixture
) -> None:
    response = client.get("/admin/probe", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex"
    assert TOKEN not in caplog.text


def test_without_a_configured_token_nobody_is_admin(make_settings: SettingsFactory) -> None:
    """The redirect stub has no ADMIN_TOKEN; its admin routes are redirected anyway."""
    settings = make_settings().model_copy(update={"admin_token": None})
    app = admin_app(create_app(settings, db_probe=FakeDatabaseProbe()))

    with TestClient(app) as client:
        response = client.get("/admin/probe", headers={"Authorization": "Bearer "})

    assert response.status_code == 401


def test_parsing_and_comparison() -> None:
    assert bearer_token("Bearer abc") == "abc"
    assert bearer_token(None) is None
    assert is_admin_token("secret", "secret") is True
    assert is_admin_token("секрет", "secret") is False
