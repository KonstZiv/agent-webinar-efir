"""Calendar files: the webinar (``/calendar.ics``), the nearest lesson (``/calendar/lesson.ics``).

Texts are verbatim from docs/copy.md, sections 5 and 4; addresses are built from
``PUBLIC_BASE_URL``; start and end are the settings (``EVENT_*``, ``LESSON_*``). They are Kyiv
wall time with ``TZID=Europe/Kyiv`` and a ``VTIMEZONE`` block built from ``zoneinfo``: no fixed
UTC offset anywhere in the file, since daylight saving time ends between the two events. The
webinar keeps v1's ``UID``, so a calendar that already has it updates the event instead of adding
a second one (docs/contract.md, section 6). A calendar takes the update only with a ``SEQUENCE``
not lower than the one it has: after the move to 21.10 v1 gives ``SEQUENCE:1``, so the webinar
has 1. The lesson exists in v2 only: each date has its own event (the ``UID`` holds the date
of ``LESSON_START``) and no ``SEQUENCE``.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

from icalendar import Calendar, Event

from app.adapters.content.copy import lesson_values
from app.core.timezone import in_kyiv

PRODID = "-//pythoncourse.me//webinar//UK"
WEBINAR_UID = "webinar-2026-10-20@pythoncourse.me"
LESSON_UID = "lesson-{date}@pythoncourse.me"  # the date of the lesson, YYYY-MM-DD
# v1 gives SEQUENCE:1 with the start of 21.10 since the move; raise it with each later change
# of the webinar's time or description.
WEBINAR_SEQUENCE = 1
WEBINAR_SUMMARY = (
    "Відкритий вебінар «Архітектор замість кодера: як працює агентна розробка на Python»"
)
WEBINAR_DESCRIPTION = (
    "Прямий ефір. Ведучий — Костянтин Зівенко. Перехід на трансляцію: {stream_url}. "
    "Голосування ефіру — у Telegram-каналі «Agentic Engineers»: https://t.me/agentic_engineers"
)
LESSON_SUMMARY = "Заняття курсу «Агентна розробка на Python» — {day_month}"
LESSON_DESCRIPTION = (
    "Відкрите відвідування заняття для зареєстрованих на {site_host}. "
    "Тренер — Костянтин Зівенко. Перехід на заняття: {lesson_url} (запрацює за добу до заняття)."
)


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    """One event; ``start`` and ``end`` are naive Kyiv wall time (``EVENT_*``, ``LESSON_*``)."""

    uid: str
    summary: str
    description: str
    location: str
    start: datetime
    end: datetime
    sequence: int = 0  # 0: no SEQUENCE in the file, as iCalendar's default


def webinar_event(*, start: datetime, end: datetime, public_base_url: str) -> CalendarEvent:
    """The webinar (docs/copy.md, section 5), for the links of v1's emails."""
    stream_url = f"{public_base_url}/go/stream"
    return CalendarEvent(
        uid=WEBINAR_UID,
        summary=WEBINAR_SUMMARY,
        description=WEBINAR_DESCRIPTION.format(stream_url=stream_url),
        location=stream_url,
        start=start,
        end=end,
        sequence=WEBINAR_SEQUENCE,
    )


def lesson_event(*, start: datetime, end: datetime, public_base_url: str) -> CalendarEvent:
    """The nearest lesson (docs/copy.md, section 4), for the invitation."""
    lesson_url = f"{public_base_url}/go/lesson"
    return CalendarEvent(
        uid=LESSON_UID.format(date=f"{start:%Y-%m-%d}"),
        summary=LESSON_SUMMARY.format(day_month=lesson_values(start, end)["lesson_day_month"]),
        description=LESSON_DESCRIPTION.format(
            site_host=urlsplit(public_base_url).hostname, lesson_url=lesson_url
        ),
        location=lesson_url,
        start=start,
        end=end,
    )


def build_calendar(event: CalendarEvent, *, now: datetime) -> bytes:
    """The ``.ics`` file of ``event``; ``now`` is its ``DTSTAMP``."""
    item = Event()
    item.add("uid", event.uid)
    item.add("dtstamp", now.astimezone(UTC))
    item.add("dtstart", in_kyiv(event.start))
    item.add("dtend", in_kyiv(event.end))
    if event.sequence:
        item.add("sequence", event.sequence)
    item.add("summary", event.summary)
    item.add("location", event.location)
    item.add("description", event.description)

    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    calendar.add("method", "PUBLISH")
    calendar.add_component(item)
    calendar.add_missing_timezones(
        first_date=date(event.start.year, 1, 1), last_date=date(event.end.year + 1, 1, 1)
    )
    return calendar.to_ical()
