"""Calendar files: ``/calendar.ics`` (the webinar, v1's UID) and ``/calendar/lesson.ics``.

Times are Kyiv wall time with ``TZID=Europe/Kyiv`` and a ``VTIMEZONE`` block from zoneinfo, no
fixed UTC offset: 21.10 is UTC+3, 28.10 already UTC+2 (requirements, section 6); the block has
winter time from 25.10.2026, 04:00 summer time. Texts come from docs/copy.md, sections 4 and 5
(the webinar's times put in from ``EVENT_START`` and ``EVENT_END``); addresses are built from
``PUBLIC_BASE_URL``. The webinar keeps v1's ``UID`` with ``SEQUENCE`` 1 or more: after the move
to 21.10 v1 gives ``SEQUENCE:1`` (docs/contract.md, section 6). The lesson has an event for each
date, ``lesson-{date of LESSON_START}@pythoncourse.me``, and no ``SEQUENCE``.
"""

from datetime import UTC, date, datetime, timedelta

import httpx
import icalendar
import pytest

from tests import copy_oracle as copy
from tests.conftest import REQUIRED_ENV
from tests.fakes import FixedClock
from tests.registration.conftest import ClientFactory

NOW = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)
PUBLIC = REQUIRED_ENV["PUBLIC_BASE_URL"]
PUBLIC_HOST = PUBLIC.split("://", 1)[1]
UID_DOMAIN = "@pythoncourse.me"  # an identifier of an event, not an address
MAIN_SITE = "https://agent.pythoncourse.me"
EVENTS = {
    "/calendar.ics": {
        "copy": copy.table(copy.section("5")),
        "uid": "webinar-2026-10-20@pythoncourse.me",
        "start": "DTSTART;TZID=Europe/Kyiv:20261021T190000",
        "end": "DTEND;TZID=Europe/Kyiv:20261021T210000",
        "utc_start": datetime(2026, 10, 21, 16, 0, tzinfo=UTC),
        "location": f"{PUBLIC}/go/stream",
    },
    "/calendar/lesson.ics": {
        "copy": copy.table(copy.section("4")),
        "uid": f"lesson-2026-10-28{UID_DOMAIN}",
        "start": "DTSTART;TZID=Europe/Kyiv:20261028T190000",
        "end": "DTEND;TZID=Europe/Kyiv:20261028T210000",
        "utc_start": datetime(2026, 10, 28, 17, 0, tzinfo=UTC),
        "location": f"{PUBLIC}/go/lesson",
    },
}
PATHS = sorted(EVENTS)


def fetch(client_factory: ClientFactory, path: str, **env: str | None) -> httpx.Response:
    client = client_factory(clock=FixedClock(NOW), **env)
    response = client.get(path)
    assert response.status_code == 200
    return response


def event_of(response: httpx.Response) -> icalendar.Event:
    calendar = icalendar.Calendar.from_ical(response.content)
    [event] = calendar.walk("VEVENT")
    return event


def public(value: str) -> str:
    return value.replace(MAIN_SITE, PUBLIC).replace("agent.pythoncourse.me", PUBLIC_HOST)


def moment(value: str) -> datetime:
    """A moment of copy.md: the webinar's is put in from the settings (ISO with the offset),
    the lesson's is written out (``28.10.2026, 19:00, пояс Europe/Kyiv``)."""
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return copy.kyiv_moment(value)


@pytest.mark.parametrize("path", PATHS)
def test_content_type(client_factory: ClientFactory, path: str) -> None:
    response = fetch(client_factory, path)

    assert response.headers["content-type"] == "text/calendar; charset=utf-8"
    assert response.content.startswith(b"BEGIN:VCALENDAR\r\n")


@pytest.mark.parametrize("path", PATHS)
def test_event_texts_come_from_the_copy(client_factory: ClientFactory, path: str) -> None:
    expected = EVENTS[path]
    texts = expected["copy"]
    assert isinstance(texts, dict)
    response = fetch(client_factory, path)
    event = event_of(response)

    assert str(event["SUMMARY"]) == texts["Назва"]
    assert str(event["LOCATION"]) == public(texts["Місце"]) == expected["location"]
    assert str(event["DESCRIPTION"]) == public(texts["Опис"])
    assert "agent.pythoncourse.me" not in response.text.replace("@pythoncourse.me", "")


@pytest.mark.parametrize("path", PATHS)
def test_time_is_kyiv_local_with_tzid(client_factory: ClientFactory, path: str) -> None:
    expected = EVENTS[path]
    texts = expected["copy"]
    assert isinstance(texts, dict)
    response = fetch(client_factory, path)
    event = event_of(response)
    lines = response.text.split("\r\n")

    assert expected["start"] in lines
    assert expected["end"] in lines
    assert event.decoded("DTSTART") == moment(texts["Початок"])
    assert event.decoded("DTEND") == moment(texts["Кінець"])
    assert event.decoded("DTSTART").astimezone(UTC) == expected["utc_start"]


@pytest.mark.parametrize("path", PATHS)
def test_time_zone_block_from_zoneinfo(client_factory: ClientFactory, path: str) -> None:
    response = fetch(client_factory, path)
    calendar = icalendar.Calendar.from_ical(response.content)
    [timezone] = calendar.walk("VTIMEZONE")

    assert str(timezone["TZID"]) == "Europe/Kyiv"
    block = response.text.split("BEGIN:VTIMEZONE", 1)[1].split("END:VTIMEZONE", 1)[0]
    offsets = {line for line in block.split("\r\n") if line.startswith("TZOFFSETTO:")}
    assert offsets == {"TZOFFSETTO:+0200", "TZOFFSETTO:+0300"}  # winter and summer time


@pytest.mark.parametrize("path", PATHS)
def test_winter_time_starts_on_25_10_at_four_summer_time(
    client_factory: ClientFactory, path: str
) -> None:
    """Summer time ends on 25.10.2026 at 04:00 Kyiv summer time (01:00 UTC): +03:00 → +02:00.

    In v1 the review found this transition an hour off in the block of ``add_missing_timezones``.
    """
    response = fetch(client_factory, path)
    [timezone] = icalendar.Calendar.from_ical(response.content).walk("VTIMEZONE")
    winter_day = date(2026, 10, 25)
    transitions = [
        part for part in timezone.walk("STANDARD") if part.decoded("DTSTART").date() == winter_day
    ]
    blocks = response.text.split("BEGIN:STANDARD")[1:]

    [winter] = transitions
    assert winter.decoded("DTSTART") == datetime(2026, 10, 25, 4, 0)
    assert winter.decoded("TZOFFSETFROM") == timedelta(hours=3)
    assert winter.decoded("TZOFFSETTO") == timedelta(hours=2)
    [raw] = [block for block in blocks if "DTSTART:20261025T040000" in block]
    assert "TZOFFSETFROM:+0300" in raw and "TZOFFSETTO:+0200" in raw


@pytest.mark.parametrize("path", PATHS)
def test_event_has_no_fixed_offsets(client_factory: ClientFactory, path: str) -> None:
    response = fetch(client_factory, path)
    event_block = response.text.split("BEGIN:VEVENT", 1)[1].split("END:VEVENT", 1)[0]

    for line in event_block.split("\r\n"):
        if line.startswith(("DTSTART", "DTEND")):
            assert not line.endswith("Z")
            assert "+03" not in line and "+02" not in line


@pytest.mark.parametrize("path", PATHS)
def test_uid_is_constant_and_method_is_publish(client_factory: ClientFactory, path: str) -> None:
    first = fetch(client_factory, path)
    later = fetch(client_factory, path, PUBLIC_BASE_URL=MAIN_SITE)

    assert str(event_of(first)["UID"]) == EVENTS[path]["uid"]
    assert str(event_of(later)["UID"]) == str(event_of(first)["UID"])
    calendar = icalendar.Calendar.from_ical(first.content)
    assert str(calendar["METHOD"]) == "PUBLISH"
    assert str(calendar["VERSION"]) == "2.0"
    assert event_of(first).decoded("DTSTAMP") == NOW


def test_the_webinar_event_supersedes_v1s(client_factory: ClientFactory) -> None:
    """After the move v1 gives ``SEQUENCE:1``: a calendar takes the event of v2 for the same
    ``UID`` only with a ``SEQUENCE`` not lower."""
    webinar = event_of(fetch(client_factory, "/calendar.ics"))

    assert int(webinar.decoded("SEQUENCE")) >= 1


def test_each_lesson_is_its_own_event_without_sequence(client_factory: ClientFactory) -> None:
    """The ``UID`` holds the date of ``LESSON_START``: the lesson of 02.11 is a new event beside
    the one of 28.10, which stays in calendars as a past one; no ``SEQUENCE`` is written."""
    first = fetch(client_factory, "/calendar/lesson.ics")
    next_lesson = fetch(
        client_factory,
        "/calendar/lesson.ics",
        LESSON_START="2026-11-02T19:00",
        LESSON_END="2026-11-02T21:00",
    )
    event = event_of(next_lesson)
    lines = next_lesson.text.split("\r\n")
    start, end = datetime(2026, 11, 2, 19), datetime(2026, 11, 2, 21)
    texts = copy.table(copy.section("4", copy.copy_text(lesson_start=start, lesson_end=end)))

    assert str(event_of(first)["UID"]) == f"lesson-2026-10-28{UID_DOMAIN}"
    assert str(event["UID"]) == f"lesson-2026-11-02{UID_DOMAIN}"
    assert not any(line.startswith("SEQUENCE") for line in lines + first.text.split("\r\n"))
    assert "DTSTART;TZID=Europe/Kyiv:20261102T190000" in lines
    assert "DTEND;TZID=Europe/Kyiv:20261102T210000" in lines
    assert str(event["SUMMARY"]) == texts["Назва"] == (
        "Заняття курсу «Агентна розробка на Python» — 2 листопада"
    )
    assert str(event["DESCRIPTION"]) == public(texts["Опис"])


@pytest.mark.parametrize(
    ("path", "env", "start", "end"),
    [
        (
            "/calendar.ics",
            {"EVENT_START": "2026-10-21T18:30", "EVENT_END": "2026-10-21T20:45"},
            "DTSTART;TZID=Europe/Kyiv:20261021T183000",
            "DTEND;TZID=Europe/Kyiv:20261021T204500",
        ),
        (
            "/calendar/lesson.ics",
            {"LESSON_START": "2026-10-28T18:00", "LESSON_END": "2026-10-28T20:30"},
            "DTSTART;TZID=Europe/Kyiv:20261028T180000",
            "DTEND;TZID=Europe/Kyiv:20261028T203000",
        ),
    ],
)
def test_events_follow_the_settings(
    client_factory: ClientFactory, path: str, env: dict[str, str], start: str, end: str
) -> None:
    lines = fetch(client_factory, path, **env).text.split("\r\n")

    assert start in lines
    assert end in lines
