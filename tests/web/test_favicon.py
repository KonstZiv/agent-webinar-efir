"""Browsers ask for /favicon.ico on every site: a neutral icon instead of a 404."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe

ICO_HEADER = b"\x00\x00\x01\x00"  # reserved, type 1 (icon)


def test_favicon_is_served(make_settings: SettingsFactory) -> None:
    app = create_app(make_settings(), db_probe=FakeDatabaseProbe())

    with TestClient(app) as client:
        response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/x-icon"
    assert response.content.startswith(ICO_HEADER)
    assert int.from_bytes(response.content[4:6], "little") >= 1  # at least one image
