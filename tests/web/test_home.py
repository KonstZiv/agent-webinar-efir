"""``GET /``: the landing page once it exists, the foundation's fallback page until then.

Both get the same context (CLAUDE.md, «Маршрут /»): ``hero`` — the first screen of the current
mode, ready (docs/copy.md, 1.1); ``page_meta`` — the service tags; ``site_mode`` — for the
partials of slices only. ``blocks`` — blocks 1.2–1.7 of the mode and the day — come from the
foundation on every render, so a page a slice renders with its own context has them too, and a
route's own keys stay as they are. The fallback includes ``_form.html`` and ``_counters.html``
by name and skips the missing ones (requirements, sections 3, 4 and 12).
"""

from datetime import datetime

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from jinja2 import ChoiceLoader, DictLoader

from app.adapters.content.copy import load_page_texts
from app.core.event_values import event_values
from app.main import create_app
from tests.conftest import REPO_ROOT, REQUIRED_ENV, SettingsFactory
from tests.fakes import WEBINAR_START, FakeDatabaseProbe, fake_overrides
from tests.html_tree import Node, parse
from tests.web.slice_partials import without_slice_partials

# The texts as the application of these tests reads them: with its EVENT_START and EVENT_END.
EVENT = event_values(
    datetime.fromisoformat(REQUIRED_ENV["EVENT_START"]),
    datetime.fromisoformat(REQUIRED_ENV["EVENT_END"]),
)
TEXTS = load_page_texts(REPO_ROOT / "docs", event=EVENT)
REPLAY = {"SITE_MODE": "replay", "RECORDING_YOUTUBE_ID": "dQw4w9WgXcQ"}
LANDING = """{% extends "base.html" %}{% block main %}
<h1 class="hero__title">LANDING {{ hero.title }}</h1>
{% include "_form.html" ignore missing %}{% endblock %}"""
BLOCK_NAMES = ("on_air", "audience", "benefits", "channel", "presenter", "course")


def app_for(make_settings: SettingsFactory, **env: str) -> FastAPI:
    # The fake clock stands on the day of the webinar: the likes goal is shown.
    return create_app(
        make_settings(**env), db_probe=FakeDatabaseProbe(), overrides=fake_overrides()
    )


def with_templates(app: FastAPI, **templates: str) -> FastAPI:
    """Templates a slice would add, served before the files of the repository."""
    env = app.state.container.templates.env
    env.loader = ChoiceLoader([DictLoader(templates), env.loader])
    return app


def get_home(app: FastAPI) -> tuple[Node, dict[str, str]]:
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    return parse(response.text), dict(response.headers)


@pytest.mark.parametrize(("mode", "env"), [("live", {}), ("replay", REPLAY)])
def test_fallback_shows_the_first_screen_of_the_mode(
    make_settings: SettingsFactory, mode: str, env: dict[str, str]
) -> None:
    page, _ = get_home(app_for(make_settings, **env))
    hero = TEXTS.first_screen[mode]  # type: ignore[index]
    main = page.find("main")

    assert main.find("h1").text() == hero.title
    for value in (hero.eyebrow, hero.subtitle, hero.when, hero.host, hero.button, hero.note):
        assert value in main.text()
    assert main.find("a", href="#register").text() == hero.button


@pytest.mark.parametrize(("mode", "env"), [("live", {}), ("replay", REPLAY)])
def test_fallback_shows_every_block(
    make_settings: SettingsFactory, mode: str, env: dict[str, str]
) -> None:
    page, _ = get_home(without_slice_partials(app_for(make_settings, **env)))
    blocks = TEXTS.landing[mode].for_day(WEBINAR_START.date())  # type: ignore[index]
    main = page.find("main")
    course = blocks.course

    assert [h2.text() for h2 in main.find_all("h2")] == [
        getattr(blocks, name).title for name in BLOCK_NAMES
    ]
    assert blocks.on_air.likes_goal in main.text()
    assert blocks.channel.link.striptags() in [link.text() for link in main.find_all("a")]
    assert [h3.text() for h3 in main.find_all("h3")] == [
        blocks.audience.subtitle,
        *(section.title for section in course.sections if section.always_visible),
    ]
    summaries = [summary.text() for summary in main.find_all("summary")]
    collapsed = [section for section in course.sections if not section.always_visible]
    assert summaries == [
        text
        for section in collapsed
        for text in (section.title, *(block.title for block in section.blocks))
    ]


def render_like_a_slice(app: FastAPI, template: str, context: dict[str, object]) -> Node:
    """``template`` rendered by a route of its own with only ``context``, as a slice renders."""

    def render(request: Request) -> HTMLResponse:
        templates = request.app.state.container.templates
        return templates.TemplateResponse(request, template, dict(context))

    app.add_api_route("/slice-like", render)
    with TestClient(app) as client:
        response = client.get("/slice-like")
    assert response.status_code == 200
    return parse(response.text)


def test_a_landing_rendered_like_a_slice_sees_every_block(make_settings: SettingsFactory) -> None:
    fields = "".join(f"<p>{{{{ blocks.{name}.title }}}}</p>" for name in BLOCK_NAMES)
    landing = '{% extends "base.html" %}{% block main %}' + fields + "{% endblock %}"
    app = with_templates(app_for(make_settings, **REPLAY), **{"landing.html": landing})
    hero = TEXTS.first_screen["replay"]
    blocks = TEXTS.landing["replay"].blocks

    page = render_like_a_slice(
        app, "landing.html", {"hero": hero, "page_meta": None, "site_mode": "replay"}
    )

    assert [p.text() for p in page.find("main").find_all("p")] == [
        getattr(blocks, name).title for name in BLOCK_NAMES
    ]


def test_blocks_keep_the_keys_of_a_route(make_settings: SettingsFactory) -> None:
    """All the blocks come under one name, ``blocks``: a route's ``on_air`` stays its own."""
    probe = (
        '<p id="route">{{ on_air }} {{ course }}</p>'
        '<p id="blocks">{{ blocks.on_air.title }} {{ blocks.course.title }}</p>'
    )
    app = with_templates(app_for(make_settings), **{"probe.html": probe})
    blocks = TEXTS.landing["live"].blocks

    page = render_like_a_slice(app, "probe.html", {"on_air": "ROUTE-1", "course": "ROUTE-2"})

    assert page.find("p", id="route").text() == "ROUTE-1 ROUTE-2"
    assert page.find("p", id="blocks").text() == f"{blocks.on_air.title} {blocks.course.title}"


def test_fallback_works_without_partials(make_settings: SettingsFactory) -> None:
    """The partials a slice adds are hidden: the foundation's page stands on its own."""
    app = with_templates(
        app_for(make_settings),
        **{"_form.html": "<form>FORM</form>", "_counters.html": "<p>COUNTERS</p>"},
    )

    page, _ = get_home(without_slice_partials(app))

    assert page.find_all("form") == []
    assert "COUNTERS" not in page.find("main").text()


def test_fallback_includes_the_partials_of_slices(make_settings: SettingsFactory) -> None:
    app = with_templates(
        app_for(make_settings, **REPLAY),
        **{
            "_form.html": '<form id="register">FORM</form>',
            "_counters.html": '<p class="counters">COUNTERS {{ site_mode }}</p>',
        },
    )

    page, _ = get_home(app)

    assert page.find("form", id="register").text() == "FORM"
    assert page.find("p", class_="counters").text() == "COUNTERS replay"


def test_landing_replaces_the_fallback(make_settings: SettingsFactory) -> None:
    app = with_templates(
        app_for(make_settings), **{"landing.html": LANDING, "_form.html": "<form>FORM</form>"}
    )

    page, _ = get_home(app)

    assert page.find("h1").text() == f"LANDING {TEXTS.first_screen['live'].title}"
    assert page.find("form").text() == "FORM"
    # The service tags come from base.html, whatever the landing looks like.
    assert page.find("meta", property="og:title").attrs["content"]


def test_home_is_noindex_until_launch(make_settings: SettingsFactory) -> None:
    page, headers = get_home(app_for(make_settings))

    assert page.find("meta", name="robots").attrs["content"] == "noindex"
    assert headers["x-robots-tag"] == "noindex"


def test_home_is_indexed_after_launch(make_settings: SettingsFactory) -> None:
    page, headers = get_home(app_for(make_settings, INDEXING_ENABLED="true"))

    assert page.find_all("meta", name="robots") == []
    assert "x-robots-tag" not in headers
    assert "no-store" not in headers.get("cache-control", "")
