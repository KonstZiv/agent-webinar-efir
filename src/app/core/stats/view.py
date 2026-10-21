"""What ``/stats`` shows, built from the groups of the source.

The chart has ``HOURS`` hourly buckets by Kyiv time, the last one the current hour. The offsets
of ``Europe/Kyiv`` are whole hours, so its hours begin at the UTC hours: the buckets are
consecutive real hours, and in the night when the clocks go back (25.10.2026, 04:00 → 03:00)
the hour 03:00 comes twice, as two separate buckets with the same label.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.stats.ports import Group
from app.core.timezone import KYIV

HOURS = 48
HOUR = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class Hour:
    """A bucket of the chart: ``start`` in Kyiv time, ``count`` registrations in that hour."""

    start: datetime
    count: int

    @property
    def label(self) -> str:
        return f"{self.start:%H:%M}"


@dataclass(frozen=True, slots=True)
class Level:
    """A level by its name for people (docs/quiz.md) and the participants of it."""

    name: str
    count: int


@dataclass(frozen=True, slots=True)
class StatsView:
    """``unspecified`` — no level, or a value the quiz gives no name to (a code is never shown)."""

    total: int
    telegram: int
    hours: tuple[Hour, ...]
    levels: tuple[Level, ...]
    unspecified: int


def current_hour(now: datetime) -> datetime:
    """The start of the hour ``now`` is in, as an aware UTC datetime."""
    return now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def window_start(now: datetime) -> datetime:
    """The start of the first bucket: ``HOURS - 1`` hours before the current one."""
    return current_hour(now) - (HOURS - 1) * HOUR


def build_view(groups: Iterable[Group], now: datetime, level_names: Mapping[str, str]) -> StatsView:
    """``level_names`` maps the value in the database to its name, in the order to show."""
    first = window_start(now)
    starts = [first + number * HOUR for number in range(HOURS)]
    per_hour = dict.fromkeys(starts, 0)
    per_level = dict.fromkeys(level_names, 0)
    total = telegram = unspecified = 0
    for item in groups:
        total += item.count
        if item.telegram_linked:
            telegram += item.count
        if item.level in per_level:
            per_level[item.level] += item.count
        else:
            unspecified += item.count
        if item.hour is not None:
            hour = item.hour.astimezone(UTC)
            if hour in per_hour:
                per_hour[hour] += item.count
    return StatsView(
        total=total,
        telegram=telegram,
        hours=tuple(Hour(start.astimezone(KYIV), per_hour[start]) for start in starts),
        levels=tuple(Level(level_names[code], per_level[code]) for code in level_names),
        unspecified=unspecified,
    )
