"""Service tags of ``/`` (requirements, section 13): the same for the fallback and the landing.

Texts come from docs/copy.md, section 10 (the text oracle compares them, tests/test_copy_oracle.py);
here — the rules: the canonical address is the main site everywhere, the image is absolute from
``PUBLIC_BASE_URL``, the event times carry the offset of the Kyiv zone on that date. Service pages
carry none of these tags.
"""

import json
from dataclasses import replace
from typing import Any

from fastapi.testclient import TestClient

from app.adapters.content.copy import load_page_texts
from app.adapters.web.page_meta import CANONICAL_URL, build_page_meta
from app.main import create_app
from tests.conftest import REPO_ROOT, SettingsFactory
from tests.fakes import FakeDatabaseProbe
from tests.html_tree import Node, parse

STAGING = "https://agent-next.pythoncourse.me"


def get_page(make_settings: SettingsFactory, path: str = "/", **env: str) -> Node:
    app = create_app(make_settings(**env), db_probe=FakeDatabaseProbe())
    with TestClient(app) as client:
        response = client.get(path)
    assert response.status_code == 200
    return parse(response.text)


def meta(page: Node, **attrs: str) -> str | None:
    return page.find("meta", **attrs).attrs["content"]


def event_of(page: Node) -> dict[str, Any]:
    [script] = page.find_all("script", type="application/ld+json")
    event: dict[str, Any] = json.loads(script.text_raw())
    return event


def test_canonical_address_is_the_main_site_on_staging_too(make_settings: SettingsFactory) -> None:
    page = get_page(make_settings, PUBLIC_BASE_URL=STAGING)

    assert page.find("link", rel="canonical").attrs["href"] == CANONICAL_URL
    assert meta(page, property="og:url") == CANONICAL_URL
    assert CANONICAL_URL == "https://agent.pythoncourse.me/"


def test_link_card(make_settings: SettingsFactory) -> None:
    page = get_page(make_settings, PUBLIC_BASE_URL=STAGING)

    assert meta(page, property="og:image") == f"{STAGING}/static/og-image.png"
    assert meta(page, property="og:type") == "website"
    assert meta(page, property="og:locale") == "uk_UA"
    assert meta(page, name="twitter:card") == "summary_large_image"


def test_event_markup(make_settings: SettingsFactory) -> None:
    event = event_of(get_page(make_settings))

    assert event["@context"] == "https://schema.org"
    assert event["@type"] == "Event"
    assert event["eventAttendanceMode"] == "https://schema.org/OnlineEventAttendanceMode"
    assert event["eventStatus"] == "https://schema.org/EventScheduled"
    assert event["location"] == {"@type": "VirtualLocation", "url": CANONICAL_URL}
    assert event["organizer"]["@type"] == "Person"
    assert event["isAccessibleForFree"] is True


def test_event_offsets_come_from_the_kyiv_zone(make_settings: SettingsFactory) -> None:
    """Summer time ends on 25.10.2026: the offset is the zone's, not a constant."""
    summer = event_of(get_page(make_settings))
    winter = event_of(
        get_page(make_settings, EVENT_START="2026-10-26T19:00", EVENT_END="2026-10-26T21:00")
    )

    assert (summer["startDate"], summer["endDate"]) == (
        "2026-10-21T19:00+03:00",
        "2026-10-21T21:00+03:00",
    )
    assert (winter["startDate"], winter["endDate"]) == (
        "2026-10-26T19:00+02:00",
        "2026-10-26T21:00+02:00",
    )


def test_event_markup_cannot_close_its_script(make_settings: SettingsFactory) -> None:
    texts = load_page_texts(REPO_ROOT / "docs", event=None)
    hostile = replace(texts, event=replace(texts.event, name="</script><script>x()</script>"))

    json_ld = str(build_page_meta(hostile, make_settings()).json_ld)

    assert "</" not in json_ld
    assert json.loads(json_ld)["name"] == "</script><script>x()</script>"


def test_service_pages_carry_no_service_tags(make_settings: SettingsFactory) -> None:
    page = get_page(make_settings, "/privacy")

    assert page.find_all("link", rel="canonical") == []
    assert page.find_all("meta", property="og:title") == []
    assert page.find_all("script", type="application/ld+json") == []
