"""The link card image (requirements, section 13): a PNG of 1200 × 630, served as a static file.

The foundation's image is temporary; the real one from Claude Design replaces this one file.
"""

import struct

from fastapi.testclient import TestClient

from app.adapters.web.dependencies import STATIC_DIR
from app.main import create_app
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == PNG_SIGNATURE
    assert data[12:16] == b"IHDR"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def test_og_image_is_a_1200_by_630_png() -> None:
    assert png_size((STATIC_DIR / "og-image.png").read_bytes()) == (1200, 630)


def test_og_image_is_served(make_settings: SettingsFactory) -> None:
    with TestClient(create_app(make_settings(), db_probe=FakeDatabaseProbe())) as client:
        response = client.get("/static/og-image.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert png_size(response.content) == (1200, 630)
