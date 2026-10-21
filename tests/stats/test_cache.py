"""The page is read at most once per 30 seconds, as the counters are read once per 15.

A failed read is remembered for as long, so a database that is down does not hold every
request; the page keeps the last known numbers, and none before the first good read. While one
call reads, the others answer at once.
"""

import threading
from datetime import datetime, timedelta

from app.core.stats.cache import CACHE_TTL, CachedStats
from app.core.stats.ports import Group
from app.core.stats.view import StatsView
from tests.fakes import FixedClock
from tests.stats.helpers import LEVELS_FOR_TESTS, RecordingSource, failing, unavailable


def cached(source: RecordingSource, clock: FixedClock) -> CachedStats:
    return CachedStats(source, clock, LEVELS_FOR_TESTS)


def total(view: StatsView | None) -> int | None:
    return None if view is None else view.total


def some(count: int) -> list[Group]:
    return [Group(level=None, telegram_linked=False, hour=None, count=count)]


def test_the_ttl_is_30_seconds() -> None:
    assert CACHE_TTL.total_seconds() == 30.0


def test_within_30_seconds_the_numbers_come_from_memory() -> None:
    source, clock = RecordingSource(answer=some(3)), FixedClock()
    stats = cached(source, clock)

    assert total(stats.current()) == 3
    source.answer = some(4)
    clock.advance(timedelta(seconds=29, microseconds=999_999))
    assert total(stats.current()) == 3
    assert len(source.calls) == 1


def test_after_30_seconds_the_source_is_read_again() -> None:
    source, clock = RecordingSource(answer=some(3)), FixedClock()
    stats = cached(source, clock)
    stats.current()
    source.answer = some(4)

    clock.advance(timedelta(seconds=30))

    assert total(stats.current()) == 4
    assert len(source.calls) == 2


def test_a_failed_first_read_gives_nothing_and_is_not_repeated_within_30_seconds() -> None:
    source, clock = unavailable(), FixedClock()
    stats = cached(source, clock)

    assert stats.current() is None
    source.error = None
    clock.advance(timedelta(seconds=29))
    assert stats.current() is None
    clock.advance(timedelta(seconds=1))
    assert stats.current() is not None
    assert len(source.calls) == 2


def test_a_failure_keeps_the_last_known_numbers() -> None:
    source, clock = RecordingSource(answer=some(3)), FixedClock()
    stats = cached(source, clock)
    stats.current()
    source.error = unavailable().error
    clock.advance(timedelta(seconds=30))

    assert total(stats.current()) == 3
    clock.advance(timedelta(seconds=10))
    assert total(stats.current()) == 3
    assert len(source.calls) == 2  # the failure is remembered for 30 seconds too


def test_any_storage_error_is_kept_off_the_page() -> None:
    assert cached(failing(), FixedClock()).current() is None


def test_a_clock_moved_back_reads_again() -> None:
    source, clock = RecordingSource(), FixedClock()
    stats = cached(source, clock)
    stats.current()

    clock.advance(timedelta(hours=-1))
    stats.current()

    assert len(source.calls) == 2


def test_a_call_that_comes_during_a_read_answers_at_once() -> None:
    reading, release = threading.Event(), threading.Event()

    class Slow(RecordingSource):
        def groups(self, since: datetime) -> list[Group]:
            reading.set()
            release.wait(10)
            return super().groups(since)

    stats = cached(Slow(), FixedClock())
    reader = threading.Thread(target=stats.current)
    reader.start()
    assert reading.wait(10)
    answers: list[StatsView | None] = []
    other = threading.Thread(target=lambda: answers.append(stats.current()), daemon=True)
    other.start()
    other.join(1.0)
    release.set()
    reader.join()

    assert answers == [None]
