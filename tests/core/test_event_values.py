"""Values of the webinar's date for texts (docs/copy.md, section 11), from naive Kyiv wall time."""

from dataclasses import fields
from datetime import datetime, timedelta

import pytest

from app.core.event_values import EventValues, event_values

WEEKDAYS_FROM_MONDAY = ("понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота", "неділя")
MONTHS = (
    "січня",
    "лютого",
    "березня",
    "квітня",
    "травня",
    "червня",
    "липня",
    "серпня",
    "вересня",
    "жовтня",
    "листопада",
    "грудня",
)


def test_the_webinar_of_21_10() -> None:
    values = event_values(datetime(2026, 10, 21, 19, 0), datetime(2026, 10, 21, 21, 0))

    assert values == EventValues(
        weekday="середа",
        weekday_capital="Середа",
        date="21 жовтня 2026 року",
        day_month="21 жовтня",
        start="19:00",
        end="21:00",
        start_moment="2026-10-21T19:00+03:00",
        end_moment="2026-10-21T21:00+03:00",
    )


@pytest.mark.parametrize("offset", range(7))
def test_every_weekday(offset: int) -> None:
    monday = datetime(2026, 10, 19, 19, 0)
    start = monday + timedelta(days=offset)

    values = event_values(start, start + timedelta(hours=2))

    assert values.weekday == WEEKDAYS_FROM_MONDAY[offset]
    assert values.weekday_capital == WEEKDAYS_FROM_MONDAY[offset].capitalize()


@pytest.mark.parametrize("month", range(1, 13))
def test_every_month_in_the_genitive(month: int) -> None:
    start = datetime(2027, month, 5, 9, 5)

    values = event_values(start, start + timedelta(minutes=50))

    assert values.date == f"5 {MONTHS[month - 1]} 2027 року"  # no leading zero
    assert values.day_month == f"5 {MONTHS[month - 1]}"
    assert (values.start, values.end) == ("09:05", "09:55")


def test_the_offset_is_the_zone_s_on_the_day() -> None:
    """Summer time ends on 25.10.2026: a webinar after it carries UTC+2."""
    values = event_values(datetime(2026, 11, 3, 18, 30), datetime(2026, 11, 3, 20, 15))

    assert (values.start_moment, values.end_moment) == (
        "2026-11-03T18:30+02:00",
        "2026-11-03T20:15+02:00",
    )


def test_placeholders_are_the_names_of_copy_md() -> None:
    values = event_values(datetime(2026, 10, 21, 19, 0), datetime(2026, 10, 21, 21, 0))

    placeholders = values.placeholders()

    assert set(placeholders) == {f"event_{field.name}" for field in fields(EventValues)}
    assert placeholders["event_date"] == "21 жовтня 2026 року"
    assert placeholders["event_start_moment"] == "2026-10-21T19:00+03:00"
