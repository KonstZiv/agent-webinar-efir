"""Every HTML page has the footer, the hidden cookie banner, the consent script and htmx."""

import json
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import OPTIONAL_ENV, SettingsFactory
from tests.fakes import FakeDatabaseProbe
from tests.html_tree import Node, parse
from tests.markdown_text import LEGAL_DIR, labelled, plain
from tests.web.slice_partials import without_slice_partials

PAGES = ["/", "/privacy"]
BANNER = (LEGAL_DIR / "cookie-banner.md").read_text(encoding="utf-8")
PRIVACY = (LEGAL_DIR / "privacy.md").read_text(encoding="utf-8")
GA4_ID = OPTIONAL_ENV["GA4_MEASUREMENT_ID"]
SCRIPTS = ["/static/js/consent.js", "/static/js/htmx.min.js"]
# v1's landing page (agent-webinar-v1, fee3439): htmx puts the answers 422, 429 and 503 of a form
# into the page (their bodies say what went wrong), other errors stay out.
V1_HTMX_CONFIG = {
    "responseHandling": [
        {"code": "204", "swap": False},
        {"code": "[23]..", "swap": True},
        {"code": "422|429|503", "swap": True},
        {"code": "[45]..", "swap": False, "error": True},
    ]
}
MATERIALS_SLUG = "Materials_Slug-01"


def get_response(
    make_settings: SettingsFactory, path: str, *, foundation_only: bool = False, **env: str | None
) -> httpx.Response:
    """``foundation_only``: the partials of slices are hidden (tests/web/slice_partials.py)."""
    app = create_app(make_settings(**env), db_probe=FakeDatabaseProbe())
    if foundation_only:
        without_slice_partials(app)
    with TestClient(app) as client:
        response = client.get(path)
    assert response.status_code == 200
    return response


def get_page(
    make_settings: SettingsFactory, path: str, *, foundation_only: bool = False, **env: str | None
) -> Node:
    response = get_response(
        make_settings, path, foundation_only=foundation_only, GA4_MEASUREMENT_ID=GA4_ID, **env
    )
    return parse(response.text)


def robots_meta(page: Node) -> list[str | None]:
    return [meta.attrs.get("content") for meta in page.find_all("meta", name="robots")]


@pytest.mark.parametrize("path", [*PAGES, "/static/css/site.css", "/favicon.ico"])
def test_nothing_is_indexed_before_launch(make_settings: SettingsFactory, path: str) -> None:
    response = get_response(make_settings, path)

    assert response.headers["x-robots-tag"] == "noindex"
    if path in PAGES:
        assert robots_meta(parse(response.text)) == ["noindex"]


def test_public_pages_are_indexed_after_launch(make_settings: SettingsFactory) -> None:
    response = get_response(make_settings, "/privacy", INDEXING_ENABLED="true")

    assert "x-robots-tag" not in response.headers
    assert robots_meta(parse(response.text)) == []


@pytest.mark.parametrize("path", PAGES)
def test_footer_has_two_links(make_settings: SettingsFactory, path: str) -> None:
    footer = get_page(make_settings, path).find("footer")
    privacy_title = re.search(r"^# (.+)$", PRIVACY, flags=re.MULTILINE)
    settings_link = re.search(r"«(.+?)»", labelled(BANNER, "Посилання внизу кожної сторінки:"))
    assert privacy_title is not None and settings_link is not None

    links = footer.find_all("a")
    assert [a.text() for a in links] == [plain(privacy_title.group(1)), settings_link.group(1)]
    assert links[0].attrs["href"] == "/privacy"
    assert "data-cookie-settings" in links[1].attrs


@pytest.mark.parametrize("path", PAGES)
def test_cookie_banner_is_hidden_with_texts_from_docs(
    make_settings: SettingsFactory, path: str
) -> None:
    banner = get_page(make_settings, path).find(class_="cookie-banner")
    buttons = [
        part.strip().strip("«»") for part in labelled(BANNER, "Кнопки:").split(" · ")
    ]

    assert "hidden" in banner.attrs
    assert banner.find("h2").text() == labelled(BANNER, "Заголовок:")
    assert labelled(BANNER, "Текст:") in banner.text()
    assert [b.text() for b in banner.find_all("button")] == buttons
    assert [b.attrs.get("data-consent") for b in banner.find_all("button")] == [
        "granted",
        "denied",
    ]


@pytest.mark.parametrize("path", PAGES)
def test_page_carries_ga4_id_and_consent_script(make_settings: SettingsFactory, path: str) -> None:
    """The base page's own scripts; a slice's partial adds its own (requirements, section 12)."""
    page = get_page(make_settings, path, foundation_only=True)

    assert page.find("body").attrs["data-ga4-id"] == GA4_ID
    # Scripts loaded from files; ``/`` also carries its event markup inline (JSON-LD).
    loaded = [s for s in page.find_all("script") if "src" in s.attrs]
    assert [s.attrs["src"] for s in loaded] == SCRIPTS
    assert all("defer" in script.attrs for script in loaded)
    assert page.find("link", rel="stylesheet").attrs["href"] == "/static/css/site.css"


def test_without_ga4_id_the_page_carries_an_empty_one(make_settings: SettingsFactory) -> None:
    page = parse(get_response(make_settings, "/privacy", GA4_MEASUREMENT_ID=None).text)

    assert page.find("body").attrs["data-ga4-id"] == ""


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/static/css/site.css", "text/css"),
        ("/static/js/consent.js", "javascript"),
        ("/static/js/htmx.min.js", "javascript"),
    ],
)
def test_static_files_are_served(
    make_settings: SettingsFactory, path: str, content_type: str
) -> None:
    response = get_response(make_settings, path)

    assert content_type in response.headers["content-type"]


def test_assets_carry_the_commit_as_version(make_settings: SettingsFactory) -> None:
    """After a deploy browsers fetch the new CSS and JS instead of a cached copy."""
    sha = "0123456789abcdef0123456789abcdef01234567"
    response = get_response(make_settings, "/", foundation_only=True, RAILWAY_GIT_COMMIT_SHA=sha)
    page = parse(response.text)

    assert page.find("link", rel="stylesheet").attrs["href"] == "/static/css/site.css?v=0123456"
    loaded = [s.attrs["src"] for s in page.find_all("script") if "src" in s.attrs]
    assert loaded == [f"{script}?v=0123456" for script in SCRIPTS]


@pytest.mark.parametrize("path", [*PAGES, f"/m/{MATERIALS_SLUG}"])
def test_the_base_page_loads_htmx_once_with_v1_config(
    make_settings: SettingsFactory, path: str
) -> None:
    """The slices' partials (the form, the counters) rely on it and never load htmx themselves."""
    page = get_page(make_settings, path, MATERIALS_SLUG=MATERIALS_SLUG)

    [config] = page.find_all("meta", name="htmx-config")
    assert json.loads(config.attrs["content"] or "") == V1_HTMX_CONFIG
    loaded = [s.attrs["src"] for s in page.find_all("script") if "src" in s.attrs]
    assert loaded.count("/static/js/htmx.min.js") == 1
