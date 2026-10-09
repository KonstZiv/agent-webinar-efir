"""``GET /``: the service page of the template: a neutral title and the deployed commit."""

from fastapi.testclient import TestClient

from app.adapters.web.routers.home import TITLE
from app.main import create_app
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe
from tests.html_tree import Node, normalize, parse

FULL_SHA = "0123456789abcdef0123456789abcdef01234567"


def get_home(make_settings: SettingsFactory, **env: str | None) -> tuple[Node, dict[str, str]]:
    app = create_app(make_settings(**env), db_probe=FakeDatabaseProbe())
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    return parse(response.text), dict(response.headers)


def test_service_page_shows_title_and_short_commit(make_settings: SettingsFactory) -> None:
    page, _ = get_home(make_settings, RAILWAY_GIT_COMMIT_SHA=FULL_SHA)
    main = page.find("main")

    assert normalize(page.find("title").text_raw()) == TITLE
    assert main.find("h1").text() == TITLE
    assert main.find("code").text() == FULL_SHA[:7]
    assert FULL_SHA[7:] not in main.text()


def test_service_page_without_commit_shows_no_code(make_settings: SettingsFactory) -> None:
    page, _ = get_home(make_settings, RAILWAY_GIT_COMMIT_SHA=None)

    assert page.find("main").find_all("code") == []


def test_service_page_is_never_indexed_nor_stored(make_settings: SettingsFactory) -> None:
    """The page tells which commit runs now: a cached copy would show an old one."""
    page, headers = get_home(make_settings, INDEXING_ENABLED="true")

    assert headers["cache-control"] == "no-store"
    assert headers["x-robots-tag"] == "noindex"
    assert [m.attrs["content"] for m in page.find_all("meta", name="robots")] == ["noindex"]
