"""``/m/{slug}``: the materials page from docs/materials.md (docs/contract.md, section 13).

Only the bot gives its address: without ``MATERIALS_SLUG`` or with another slug — 404, as for
any unknown path. The page is not indexed, not cached and loads no analytics; its address is
masked in the access log (tests/web/test_access_log.py). The text itself is compared by the
text oracle (tests/test_copy_oracle.py).
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.content.copy import load_page_texts
from app.main import create_app
from tests.conftest import OPTIONAL_ENV, REPO_ROOT, SettingsFactory
from tests.fakes import FakeDatabaseProbe
from tests.html_tree import normalize, parse

SLUG = "Materials_Slug-01"


def get(make_settings: SettingsFactory, path: str, **env: str | None) -> httpx.Response:
    app = create_app(make_settings(**OPTIONAL_ENV, **env), db_probe=FakeDatabaseProbe())
    with TestClient(app) as client:
        return client.get(path)


def test_without_a_slug_there_is_no_page(make_settings: SettingsFactory) -> None:
    assert get(make_settings, f"/m/{SLUG}").status_code == 404


@pytest.mark.parametrize(
    "slug", [SLUG.lower(), f"{SLUG}x", SLUG[:-1], "other-slug-01", "%20" + SLUG]
)
def test_another_slug_is_404(make_settings: SettingsFactory, slug: str) -> None:
    response = get(make_settings, f"/m/{slug}", MATERIALS_SLUG=SLUG)

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_the_page_with_its_slug(make_settings: SettingsFactory) -> None:
    response = get(make_settings, f"/m/{SLUG}", MATERIALS_SLUG=SLUG)
    page = parse(response.text)

    assert response.status_code == 200
    assert (
        normalize(page.find("title").text_raw())
        == load_page_texts(REPO_ROOT / "docs", event=None).materials_title
    )
    assert page.find("meta", name="robots").attrs["content"] == "noindex"
    assert response.headers["x-robots-tag"] == "noindex"
    assert response.headers["cache-control"] == "no-store"
    assert page.find("body").attrs["data-ga4-id"] == ""  # no analytics, even with GA4 set
    assert page.find_all("meta", property="og:title") == []
