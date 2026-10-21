"""The numbers of the page: 48 hourly buckets by Kyiv time (the issue «Statistic»).

The last bucket is the current hour. Kyiv's offsets are whole hours, so its hour borders are
the UTC ones, and the night of 25.10.2026 (clocks go back at 04:00 to 03:00) has the hour
03:00 twice, as two separate buckets.
"""

from datetime import UTC, datetime, timedelta

from app.core.stats.ports import Group
from app.core.stats.view import HOURS, build_view, window_start

LEVELS = {"level1": "Рівень 1 курсу", "level2": "Рівень 2 курсу"}
NOW = datetime(2026, 10, 21, 16, 30, tzinfo=UTC)  # 19:30 in Kyiv
LAST_HOUR = datetime(2026, 10, 21, 16, 0, tzinfo=UTC)  # 19:00 in Kyiv


def group(
    count: int = 1,
    *,
    level: str | None = None,
    linked: bool = False,
    hour: datetime | None = None,
) -> Group:
    return Group(level=level, telegram_linked=linked, hour=hour, count=count)


def test_the_window_is_48_hours_ending_with_the_current_hour() -> None:
    view = build_view([], NOW, LEVELS)

    assert HOURS == 48
    assert len(view.hours) == 48
    assert window_start(NOW) == LAST_HOUR - timedelta(hours=47)
    assert view.hours[-1].start == LAST_HOUR
    assert view.hours[-1].label == "19:00"
    assert view.hours[0].start == LAST_HOUR - timedelta(hours=47)
    assert view.hours[0].label == "20:00"  # 19.10, Kyiv


def test_an_empty_database_gives_zeros() -> None:
    view = build_view([], NOW, LEVELS)

    assert (view.total, view.telegram) == (0, 0)
    assert [hour.count for hour in view.hours] == [0] * 48
    assert [(level.name, level.count) for level in view.levels] == [
        ("Рівень 1 курсу", 0),
        ("Рівень 2 курсу", 0),
    ]
    assert view.unspecified == 0


def test_the_border_of_the_window() -> None:
    first = window_start(NOW)
    view = build_view(
        [
            group(2, hour=first),  # the first bucket
            group(3, hour=LAST_HOUR),  # the current hour
            group(5, hour=first - timedelta(hours=1)),  # an hour too old: only in the total
            group(7, hour=LAST_HOUR + timedelta(hours=1)),  # the future: only in the total
            group(11),  # the database found it outside the window
        ],
        NOW,
        LEVELS,
    )

    assert (view.hours[0].count, view.hours[-1].count) == (2, 3)
    assert sum(hour.count for hour in view.hours) == 5
    assert view.total == 2 + 3 + 5 + 7 + 11


def test_the_aggregates_agree() -> None:
    view = build_view(
        [
            group(4, level="level1", linked=True),
            group(3, level="level2"),
            group(2, level=None, linked=True),
            group(1, level="level9"),  # a value the quiz does not name
        ],
        NOW,
        LEVELS,
    )

    assert view.total == 10
    assert view.telegram == 6
    assert [(level.name, level.count) for level in view.levels] == [
        ("Рівень 1 курсу", 4),
        ("Рівень 2 курсу", 3),
    ]
    assert view.unspecified == 3  # no level, and a value without a name: never a code
    assert sum(level.count for level in view.levels) + view.unspecified == view.total


def test_the_night_of_the_clocks_going_back_has_two_buckets_of_the_same_hour() -> None:
    now = datetime(2026, 10, 25, 12, 30, tzinfo=UTC)  # 14:30 in Kyiv, winter time
    first_03 = datetime(2026, 10, 25, 0, 0, tzinfo=UTC)  # 03:00 EEST
    second_03 = datetime(2026, 10, 25, 1, 0, tzinfo=UTC)  # 03:00 EET

    view = build_view([group(2, hour=first_03), group(5, hour=second_03)], now, LEVELS)

    assert len(view.hours) == 48
    # 03:00 on the 24th, and twice on the 25th
    assert [hour.label for hour in view.hours].count("03:00") == 3
    repeated = [hour for hour in view.hours if hour.label == "03:00" and hour.start.day == 25]
    assert len(repeated) == 2
    assert [hour.count for hour in repeated] == [2, 5]
    assert repeated[0].start.utcoffset() != repeated[1].start.utcoffset()
    assert view.hours[-1].label == "14:00"


def test_the_buckets_follow_the_hours_in_a_row_across_the_change() -> None:
    now = datetime(2026, 10, 25, 12, 30, tzinfo=UTC)

    view = build_view([], now, LEVELS)

    starts = [hour.start.astimezone(UTC) for hour in view.hours]
    assert [b - a for a, b in zip(starts, starts[1:], strict=False)] == [timedelta(hours=1)] * 47
