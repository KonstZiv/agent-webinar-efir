"""Every slice and the layout add their own file to static/css; every page links all of them.

``site.css`` comes first, the rest by name (requirements, section 12): a slice never edits
another file to style its partial.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.web.dependencies import STATIC_DIR, stylesheets
from app.main import create_app
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe
from tests.html_tree import parse


def test_site_css_first_then_the_rest_by_name(tmp_path: Path) -> None:
    for name in ("registration.css", "counters.css", "site.css", "landing.css", "notes.txt"):
        (tmp_path / name).write_text("", encoding="utf-8")

    assert stylesheets(tmp_path) == ("site.css", "counters.css", "landing.css", "registration.css")


def test_site_css_is_required(tmp_path: Path) -> None:
    (tmp_path / "landing.css").write_text("", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="site.css"):
        stylesheets(tmp_path)


def test_every_page_links_every_stylesheet(make_settings: SettingsFactory) -> None:
    app = create_app(
        make_settings(RAILWAY_GIT_COMMIT_SHA="0123456789abcdef"), db_probe=FakeDatabaseProbe()
    )

    with TestClient(app) as client:
        page = parse(client.get("/privacy").text)

    links = [
        link.attrs["href"]
        for link in page.find_all("link")
        if link.attrs.get("rel") == "stylesheet"
    ]
    assert links == [f"/static/css/{name}?v=0123456" for name in stylesheets(STATIC_DIR / "css")]
    assert links[0].startswith("/static/css/site.css")
