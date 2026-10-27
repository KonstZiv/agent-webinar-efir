"""Links from emails: ``/go/stream``, ``/go/lesson``, ``/go/course`` (requirements, section 6).

A temporary redirect (302) while the target is set, since it may change; until then the page
«the link will appear» (docs/copy.md, 6.1 and 6.2), never indexed. ``/go/stream`` serves the
links of old emails of v1 (docs/contract.md, section 3). The date of the webinar on 6.1 comes
from ``EVENT_START``; no value ``{…}`` of copy.md is left on the pages or in the calendars.
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from tests import copy_oracle as copy
from tests.html_tree import normalize
from tests.registration.conftest import ClientFactory
from tests.registration.helpers import links, main_of, page

STREAM_URL = "https://www.youtube.com/live/sentinel-stream"
LESSON_URL = "https://teams.microsoft.com/l/meetup-join/sentinel-lesson"
COURSE_URL = "https://course-sentinel.example.com/course"  # REQUIRED_ENV of tests/conftest.py
# Another webinar: a Tuesday in winter time, other hours.
MOVED = {"EVENT_START": "2026-11-03T18:30", "EVENT_END": "2026-11-03T20:15"}
TITLES = copy.table(copy.group(copy.section("10"), "Службові сторінки"))
PENDING = {
    "/go/stream": (copy.section("6.1"), TITLES["/go/stream до появи посилання"]),
    "/go/lesson": (copy.section("6.2"), TITLES["/go/lesson до появи посилання"]),
}


@pytest.mark.parametrize(
    ("path", "env", "target"),
    [
        ("/go/stream", {"STREAM_URL": STREAM_URL}, STREAM_URL),
        ("/go/lesson", {"LESSON_URL": LESSON_URL}, LESSON_URL),
        ("/go/course", {}, COURSE_URL),
    ],
)
def test_a_set_target_is_a_temporary_redirect(
    client_factory: ClientFactory, path: str, env: dict[str, str], target: str
) -> None:
    client = client_factory(**env)

    response = client.get(path, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == target
    assert response.headers["cache-control"] == "no-store"


def test_the_lesson_page_follows_lesson_start(client_factory: ClientFactory) -> None:
    """6.2 shows the nearest lesson: the date comes from ``LESSON_START``."""
    start, end = datetime(2026, 11, 2, 19), datetime(2026, 11, 2, 21)
    texts = copy.section("6.2", copy.copy_text(lesson_start=start, lesson_end=end))
    client = client_factory(LESSON_START="2026-11-02T19:00", LESSON_END="2026-11-02T21:00")

    content = main_of(client.get("/go/lesson", follow_redirects=False))

    assert copy.one(texts, "Текст") in content.text()
    assert "Найближче заняття курсу «Агентна розробка на Python» — понеділок, 2 листопада 2026" in (
        content.text()
    )
    assert "28 жовтня" not in content.text()


@pytest.mark.parametrize("path", sorted(PENDING))
def test_without_a_target_the_page_says_the_link_will_appear(
    client_factory: ClientFactory, path: str
) -> None:
    texts, title = PENDING[path]
    client = client_factory()

    response = client.get(path, follow_redirects=False)

    assert response.status_code == 200
    html = page(response)
    assert normalize(html.find("title").text_raw()) == title
    content = main_of(response)
    assert content.find("h1").text() == copy.one(texts, "Заголовок")
    shown = content.text()
    assert copy.one(texts, "Текст") in shown
    for line in copy.labeled(texts, "Посилання"):
        assert line in shown
    found = links(content)
    assert found["Зареєструватися"] == "/#register"
    if path == "/go/stream":
        assert found["Telegram-канал «Agentic Engineers»"] == "https://t.me/agentic_engineers"
    else:
        assert len(found) == 1


@pytest.mark.parametrize("path", sorted(PENDING))
def test_the_pages_are_never_indexed(client_factory: ClientFactory, path: str) -> None:
    client: TestClient = client_factory(INDEXING_ENABLED="true")

    response = client.get(path)

    assert response.headers["x-robots-tag"] == "noindex"
    assert response.headers["cache-control"] == "no-store"
    robots = [meta.attrs["content"] for meta in page(response).find_all("meta", name="robots")]
    assert robots == ["noindex"]
    assert page(response).find_all("link", rel="canonical") == []  # no service tags of /


def test_the_stream_page_follows_the_settings(client_factory: ClientFactory) -> None:
    """Moving the webinar is a change of ``EVENT_START`` and ``EVENT_END``: 6.1 follows them."""
    start, end = (datetime.fromisoformat(MOVED[name]) for name in ("EVENT_START", "EVENT_END"))
    texts = copy.section("6.1", copy.copy_text(start, end))

    shown = main_of(client_factory(**MOVED).get("/go/stream")).text()

    assert copy.one(texts, "Текст") in shown
    assert "вівторок, 3 листопада 2026 року, 18:30" in shown
    assert "21 жовтня" not in shown


@pytest.mark.parametrize(
    "path", ["/go/stream", "/go/lesson", "/calendar.ics", "/calendar/lesson.ics"]
)
def test_no_value_reaches_a_page(client_factory: ClientFactory, path: str) -> None:
    """No ``{name}`` of copy.md, section 11, is left on a page or in a calendar of the slice."""
    response = client_factory().get(path, follow_redirects=False)
    text = response.text.replace("\r\n ", "")  # a calendar folds its long lines

    assert response.status_code == 200
    assert [name for name in sorted(copy.value_names()) if f"{{{name}}}" in text] == []
