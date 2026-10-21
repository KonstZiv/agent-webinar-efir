"""Text oracle (docs/requirements.md, section 16): pages contain the texts of docs/copy.md verbatim.

The oracle reads docs/copy.md itself (tests/copy_oracle.py), never the application's texts.
``/`` is checked in both modes — blocks 1.1–1.7 and the service tags (10) — whatever template
it renders: the fallback page now, the landing later. The first screen has its own button to
the form (``#register``); no text that only the other mode has is shown; the likes goal of 1.2
is shown until its last day in Kyiv. The page has the blocks whoever renders it: the route or a
slice's answer with only ``hero``, ``page_meta`` and ``site_mode``. A green oracle is the
condition of done for the live slice «лендінг». The materials page shows docs/materials.md whole.

The date of the webinar comes from the settings only: the oracle puts its own formatting of
``EVENT_START`` and ``EVENT_END`` into copy.md, the pages follow other settings, and no value
``{…}`` is left on a page.
"""

import doctest
import html
import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from app.core.timezone import KYIV
from app.main import create_app
from tests import copy_oracle as copy
from tests.conftest import SettingsFactory
from tests.fakes import WEBINAR_START, FakeDatabaseProbe, FixedClock, fake_overrides
from tests.html_tree import Node, normalize, parse
from tests.markdown_text import document_texts

MODES = {"live": {}, "replay": {"SITE_MODE": "replay", "RECORDING_YOUTUBE_ID": "dQw4w9WgXcQ"}}
OTHER_MODE = {"live": "replay", "replay": "live"}
FIRST_SCREEN = (
    "Надзаголовок",
    "Заголовок",
    "Підзаголовок",
    "Коли",
    "Ведучий",
    "Кнопка",
    "Під кнопкою",
)
LANDING_BLOCKS = ("1.2", "1.3", "1.4", "1.5", "1.6", "1.7")
SLUG = "Materials_Slug-01"
SLICE_LIKE = "/slice-like"


def get(make_settings: SettingsFactory, path: str, **env: str) -> Node:
    app = create_app(make_settings(**env), db_probe=FakeDatabaseProbe())
    with TestClient(app) as client:
        response = client.get(path)
    assert response.status_code == 200
    return parse(response.text)


@pytest.fixture(params=sorted(MODES))
def home(request: pytest.FixtureRequest, make_settings: SettingsFactory) -> tuple[str, Node]:
    """``/`` in each mode, and the name of the mode."""
    mode: str = request.param
    return mode, get(make_settings, "/", **MODES[mode])


def content(page: Node, **attrs: str) -> str:
    value = page.find("meta", **attrs).attrs["content"]
    assert value is not None
    return value


def event_of(page: Node) -> dict[str, Any]:
    [script] = page.find_all("script", type="application/ld+json")
    event: dict[str, Any] = json.loads(script.text_raw())
    return event


def test_the_oracle_helpers() -> None:
    assert doctest.testmod(copy).failed == 0


def first_screen(mode: str) -> dict[str, str]:
    """The texts of docs/copy.md 1.1 for ``mode``, by label."""
    texts = copy.group(copy.section("1.1"), mode)
    return {label: copy.one(texts, label) for label in FIRST_SCREEN}


def first_screen_problems(page: Node, mode: str) -> list[str]:
    """What the first screen of ``page`` in ``mode`` gets wrong against docs/copy.md 1.1.

    Every text is there; the button is a link to the form (``#register``), not just the same
    words on the form's own button; no text that differs in the other mode is shown.
    """
    texts, other = first_screen(mode), first_screen(OTHER_MODE[mode])
    main = page.find("main")
    shown = main.text()
    problems = [f"lacks «{label}»" for label in FIRST_SCREEN if texts[label] not in shown]
    if texts["Кнопка"] not in [link.text() for link in main.find_all("a", href="#register")]:
        problems.append("no first-screen button to #register")
    problems += [
        f"shows «{label}» of {OTHER_MODE[mode]}"
        for label in FIRST_SCREEN
        if other[label] != texts[label] and other[label] in shown
    ]
    return problems


def test_first_screen(home: tuple[str, Node]) -> None:
    mode, page = home

    assert first_screen_problems(page, mode) == []


def made_up_page(mode: str, *, button_href: str = "#register", extra: str = "") -> Node:
    """A first screen of ``mode`` built from docs/copy.md, to show what the oracle catches."""
    texts = first_screen(mode)
    items = "".join(
        f"<p>{html.escape(text)}</p>" for label, text in texts.items() if label != "Кнопка"
    )
    button = f'<a href="{button_href}">{html.escape(texts["Кнопка"])}</a>'
    return parse(
        f"<html><body><main><section>{items}{button}</section>{extra}</main></body></html>"
    )


@pytest.mark.parametrize("mode", sorted(MODES))
def test_the_oracle_accepts_a_right_first_screen(mode: str) -> None:
    assert first_screen_problems(made_up_page(mode), mode) == []


@pytest.mark.parametrize("mode", sorted(MODES))
def test_the_oracle_wants_the_button_to_lead_to_the_form(mode: str) -> None:
    """The form's own button says the same; the first screen still needs its link."""
    form = (
        f'<form id="register"><button>{html.escape(first_screen(mode)["Кнопка"])}</button></form>'
    )
    page = made_up_page(mode, button_href="#", extra=form)

    assert first_screen_problems(page, mode) == ["no first-screen button to #register"]


@pytest.mark.parametrize("mode", sorted(MODES))
def test_the_oracle_rejects_texts_of_the_other_mode(mode: str) -> None:
    """The page has no logic of modes: the route gives it the texts of the current one."""
    other = OTHER_MODE[mode]
    texts, foreign = first_screen(mode), first_screen(other)
    differing = [label for label in FIRST_SCREEN if foreign[label] != texts[label]]
    extra = "".join(f"<p>{html.escape(foreign[label])}</p>" for label in differing)

    problems = first_screen_problems(made_up_page(mode, extra=extra), mode)

    assert differing
    assert problems == [f"shows «{label}» of {other}" for label in differing]


# --- blocks 1.2–1.7 ------------------------------------------------------------------------------


def landing_texts(mode: str) -> list[str]:
    """The texts of docs/copy.md 1.2–1.7 for ``mode``, except the likes goal."""
    return [text for number in LANDING_BLOCKS for text in copy.block_texts(number, mode)]


def landing_problems(page: Node, mode: str, today: date) -> list[str]:
    """What blocks 1.2–1.7 of ``page`` in ``mode`` on ``today`` (in Kyiv) get wrong.

    Every text of the mode is there; the likes goal is there until its last day and gone after
    it; no text that differs in the other mode is shown.
    """
    shown = page.find("main").text()
    texts = landing_texts(mode)
    other = OTHER_MODE[mode]
    last_day, likes = copy.likes_goal()
    problems = [f"lacks «{text}»" for text in texts if text not in shown]
    if today <= last_day and likes not in shown:
        problems.append("lacks the likes goal")
    if today > last_day and likes in shown:
        problems.append(f"shows the likes goal after {last_day:%d.%m.%Y}")
    problems += [
        f"shows «{text}» of {other}"
        for text in landing_texts(other)
        if text not in texts and text in shown
    ]
    return problems


def page_problems(page: Node, mode: str, today: date) -> list[str]:
    """Blocks 1.1–1.7 of the page of ``/`` against docs/copy.md."""
    return first_screen_problems(page, mode) + landing_problems(page, mode, today)


def app_at(make_settings: SettingsFactory, mode: str, now: datetime) -> FastAPI:
    """The application in ``mode`` whose clock stands at ``now``."""
    return create_app(
        make_settings(**MODES[mode]),
        db_probe=FakeDatabaseProbe(),
        overrides=fake_overrides(clock=FixedClock(now)),
    )


def get_page(app: FastAPI, path: str = "/") -> Node:
    with TestClient(app) as client:
        response = client.get(path)
    assert response.status_code == 200
    return parse(response.text)


def kyiv_day(now: datetime) -> date:
    return now.astimezone(KYIV).date()


@pytest.mark.parametrize("mode", sorted(MODES))
def test_every_block_of_the_mode(make_settings: SettingsFactory, mode: str) -> None:
    page = get_page(app_at(make_settings, mode, WEBINAR_START))

    assert page_problems(page, mode, kyiv_day(WEBINAR_START)) == []


@pytest.mark.parametrize("mode", sorted(MODES))
def test_a_page_rendered_like_a_slice_has_every_block(
    make_settings: SettingsFactory, mode: str
) -> None:
    """A slice's answer without htmx renders the page with ``hero``, ``page_meta`` and
    ``site_mode`` only (routers/registration.py); the blocks come from the foundation."""
    app = app_at(make_settings, mode, WEBINAR_START)

    def render(request: Request) -> HTMLResponse:
        container = request.app.state.container
        site_mode = container.settings.site_mode
        return container.templates.TemplateResponse(
            request,
            "home.html",
            {
                "hero": container.page_texts.first_screen[site_mode],
                "page_meta": container.page_meta,
                "site_mode": site_mode,
            },
        )

    app.add_api_route(SLICE_LIKE, render)

    assert page_problems(get_page(app, SLICE_LIKE), mode, kyiv_day(WEBINAR_START)) == []


@pytest.mark.parametrize("mode", sorted(MODES))
def test_likes_goal_until_its_last_day_in_kyiv(make_settings: SettingsFactory, mode: str) -> None:
    last_day, likes = copy.likes_goal()
    last_minute = datetime.combine(last_day, time(23, 59), KYIV).astimezone(UTC)
    next_day = last_minute + timedelta(minutes=1)

    before = get_page(app_at(make_settings, mode, last_minute))
    after = get_page(app_at(make_settings, mode, next_day))

    assert next_day.date() == last_day  # in UTC the last day goes on: the day is Kyiv's
    assert likes in before.find("main").text()
    assert likes not in after.find("main").text()
    assert page_problems(before, mode, kyiv_day(last_minute)) == []
    assert page_problems(after, mode, kyiv_day(next_day)) == []


def made_up_landing(mode: str, *, without: str = "", extra: str = "", likes: bool = True) -> Node:
    """Blocks 1.2–1.7 of ``mode`` built from docs/copy.md, to show what the oracle catches."""
    texts = [text for text in landing_texts(mode) if text != without]
    if likes:
        texts.append(copy.likes_goal()[1])
    items = "".join(f"<p>{html.escape(text)}</p>" for text in [*texts, extra] if text)
    return parse(f"<html><body><main>{items}</main></body></html>")


@pytest.mark.parametrize("mode", sorted(MODES))
def test_the_oracle_accepts_right_blocks(mode: str) -> None:
    last_day, _ = copy.likes_goal()

    assert landing_problems(made_up_landing(mode), mode, last_day) == []
    after = last_day + timedelta(days=1)
    assert landing_problems(made_up_landing(mode, likes=False), mode, after) == []


@pytest.mark.parametrize("mode", sorted(MODES))
def test_the_oracle_rejects_a_missing_item(mode: str) -> None:
    item = copy.block_texts("1.4", mode)[-1]  # a numbered item of the mode's group

    problems = landing_problems(made_up_landing(mode, without=item), mode, WEBINAR_START.date())

    assert problems == [f"lacks «{item}»"]


@pytest.mark.parametrize("mode", sorted(MODES))
def test_the_oracle_rejects_blocks_of_the_other_mode(mode: str) -> None:
    other = OTHER_MODE[mode]
    foreign = [text for text in landing_texts(other) if text not in landing_texts(mode)]

    problems = landing_problems(made_up_landing(mode, extra=foreign[0]), mode, WEBINAR_START.date())

    assert foreign
    assert problems == [f"shows «{foreign[0]}» of {other}"]


@pytest.mark.parametrize("mode", sorted(MODES))
def test_the_oracle_wants_the_likes_goal_gone_after_its_last_day(mode: str) -> None:
    last_day, _ = copy.likes_goal()
    after = last_day + timedelta(days=1)

    assert landing_problems(made_up_landing(mode), mode, after) == [
        f"shows the likes goal after {last_day:%d.%m.%Y}"
    ]
    assert landing_problems(made_up_landing(mode, likes=False), mode, last_day) == [
        "lacks the likes goal"
    ]


def test_title_and_description(home: tuple[str, Node]) -> None:
    mode, page = home
    tags = copy.table(copy.group(copy.section("10"), mode))

    assert normalize(page.find("title").text_raw()) == tags["title"]
    assert content(page, name="description") == tags["description"]


def test_link_card(home: tuple[str, Node]) -> None:
    mode, page = home
    tags = copy.table(copy.group(copy.section("10"), mode))
    shared = copy.table(copy.group(copy.section("10"), "Спільне"))

    assert content(page, property="og:title") == tags["og:title"]
    assert content(page, property="og:description") == tags["og:description"]
    assert content(page, property="og:site_name") == shared["og:site_name"]
    assert content(page, property="og:image:alt") == shared["og:image:alt"]


def test_event_markup(home: tuple[str, Node]) -> None:
    _, page = home
    fields = copy.table(copy.group(copy.section("10"), "Розмітка події"))
    event = event_of(page)

    assert event["name"] == fields["name"]
    assert event["description"] == fields["description"]
    assert event["organizer"]["name"] == fields["organizer"]
    assert event["inLanguage"] == fields["inLanguage"]
    assert (event["startDate"], event["endDate"]) == (fields["startDate"], fields["endDate"])


# --- the date of the webinar: values {event_…} from EVENT_START and EVENT_END ---------------------

# Another webinar: a Tuesday in winter time (UTC+2), other hours.
MOVED = {"EVENT_START": "2026-11-03T18:30", "EVENT_END": "2026-11-03T20:15"}


def test_event_values_stand_only_where_the_site_puts_them() -> None:
    """The site fills ``{event_…}`` in 1.1, 5, 6.1 and 10 (11 lists them): written in any other
    section, the value would reach a page, a letter or the bot as it is."""
    assert copy.event_value_sections(copy.raw_copy_text()) <= copy.EVENT_SECTIONS


@pytest.mark.parametrize("mode", sorted(MODES))
def test_the_date_follows_the_settings(make_settings: SettingsFactory, mode: str) -> None:
    """Moving the webinar is a change of ``EVENT_START`` and ``EVENT_END``: the first screen,
    the service tags and the event markup follow them."""
    settings = make_settings(**MODES[mode], **MOVED)
    assert settings.event_start is not None and settings.event_end is not None
    text = copy.copy_text(settings.event_start, settings.event_end)
    when = copy.one(copy.group(copy.section("1.1", text), mode), "Коли")
    tags = copy.table(copy.group(copy.section("10", text), mode))
    fields = copy.table(copy.group(copy.section("10", text), "Розмітка події"))
    with TestClient(create_app(settings, db_probe=FakeDatabaseProbe())) as client:
        response = client.get("/")
    page = parse(response.text)
    event = event_of(page)

    assert when in page.find("main").text()
    assert normalize(page.find("title").text_raw()) == tags["title"]
    assert content(page, name="description") == tags["description"]
    assert content(page, property="og:description") == tags["og:description"]
    assert (event["startDate"], event["endDate"]) == (fields["startDate"], fields["endDate"])
    assert event["startDate"] == "2026-11-03T18:30+02:00"
    assert "21 жовтня" not in response.text
    assert "Середа" not in response.text


@pytest.mark.parametrize(
    ("path", "env"),
    [("/", MODES["live"]), ("/", MODES["replay"]), (f"/m/{SLUG}", {"MATERIALS_SLUG": SLUG})],
    ids=["home-live", "home-replay", "materials"],
)
def test_no_value_reaches_a_page(
    make_settings: SettingsFactory, path: str, env: dict[str, str]
) -> None:
    """No ``{name}`` of copy.md, section 11, is left on a page of the foundation."""
    with TestClient(create_app(make_settings(**env), db_probe=FakeDatabaseProbe())) as client:
        response = client.get(path)

    assert response.status_code == 200
    assert [name for name in sorted(copy.value_names()) if f"{{{name}}}" in response.text] == []


def test_materials_page(make_settings: SettingsFactory) -> None:
    page = get(make_settings, f"/m/{SLUG}", MATERIALS_SLUG=SLUG)
    titles = copy.table(copy.group(copy.section("10"), "Службові сторінки"))
    shown = page.find("main").text()

    missing = [
        unit
        for unit in document_texts(copy.MATERIALS_FILE.read_text(encoding="utf-8"))
        if unit not in shown
    ]
    assert missing == []
    assert normalize(page.find("title").text_raw()) == titles["Сторінка матеріалів"]
