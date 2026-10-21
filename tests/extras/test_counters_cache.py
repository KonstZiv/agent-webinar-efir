"""The counters stay in memory up to 15 seconds (docs/requirements.md, section 8).

Hundreds of viewers poll every 15 seconds, so the database is read at most once per 15 seconds,
and a failed read is not repeated sooner either: a down database does not hold every request.
The 15 seconds count from the end of a read. While one call reads, the others do not wait for
it: they answer at once with the latest numbers, or none (review r6, finding 1).
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from app.core.extras.counters import CACHE_TTL, REFRESH_SECONDS, CachedCounters
from app.core.extras.ports import Counts
from app.core.ports import StorageError, StorageUnavailable
from tests.extras.helpers import HOLD_LIMIT, RecordingStore, SlowStore
from tests.fakes import FixedClock

COUNTS = Counts(registered=128, telegram_linked=45)
FRESH = Counts(registered=129, telegram_linked=46)
AT_ONCE = 1.0  # seconds: an answer that does not wait for a read comes far sooner


def counters(store: RecordingStore, clock: FixedClock) -> CachedCounters:
    return CachedCounters(store, clock)


def test_both_intervals_are_15_seconds() -> None:
    assert [CACHE_TTL.total_seconds(), float(REFRESH_SECONDS)] == [15.0, 15.0]


def test_the_first_call_reads_the_store() -> None:
    store = RecordingStore(counted=COUNTS)

    assert counters(store, FixedClock()).current() == COUNTS
    assert store.calls == ["counts"]


def test_within_15_seconds_the_numbers_come_from_memory() -> None:
    store, clock = RecordingStore(counted=COUNTS), FixedClock()
    cached = counters(store, clock)
    cached.current()
    store.counted = Counts(registered=129, telegram_linked=45)

    clock.advance(timedelta(seconds=14, microseconds=999_999))

    assert cached.current() == COUNTS
    assert store.calls == ["counts"]


def test_after_15_seconds_the_store_is_read_again() -> None:
    store, clock = RecordingStore(counted=COUNTS), FixedClock()
    cached = counters(store, clock)
    cached.current()
    fresh = Counts(registered=129, telegram_linked=46)
    store.counted = fresh

    clock.advance(timedelta(seconds=15))

    assert cached.current() == fresh
    assert store.calls == ["counts", "counts"]


def test_a_failed_read_gives_no_numbers() -> None:
    store = RecordingStore(error=StorageUnavailable("test"))

    assert counters(store, FixedClock()).current() is None


def test_any_storage_error_gives_no_numbers() -> None:
    """A broken statement must not break the page either."""
    store = RecordingStore(error=StorageError("test"))

    assert counters(store, FixedClock()).current() is None


def test_a_failed_read_is_not_repeated_within_15_seconds() -> None:
    store, clock = RecordingStore(error=StorageUnavailable("test")), FixedClock()
    cached = counters(store, clock)
    cached.current()
    store.error = None
    store.counted = COUNTS

    clock.advance(timedelta(seconds=14))
    assert cached.current() is None
    clock.advance(timedelta(seconds=1))
    assert cached.current() == COUNTS
    assert store.calls == ["counts", "counts"]


def test_numbers_are_not_kept_past_15_seconds_when_the_database_fails() -> None:
    store, clock = RecordingStore(counted=COUNTS), FixedClock()
    cached = counters(store, clock)
    cached.current()
    store.error = StorageUnavailable("test")

    clock.advance(timedelta(seconds=15))

    assert cached.current() is None


def test_a_clock_moved_back_reads_the_store_again() -> None:
    store, clock = RecordingStore(counted=COUNTS), FixedClock()
    cached = counters(store, clock)
    cached.current()

    clock.advance(timedelta(hours=-1))
    cached.current()

    assert store.calls == ["counts", "counts"]


@dataclass
class TakesTime(RecordingStore):
    """Each read takes ``took`` by ``clock``: a slow database."""

    clock: FixedClock = field(default_factory=FixedClock)
    took: timedelta = timedelta(seconds=4)

    def counts(self) -> Counts:
        self.clock.advance(self.took)
        return super().counts()


def test_the_15_seconds_count_from_the_end_of_a_read() -> None:
    clock = FixedClock()
    store = TakesTime(counted=COUNTS, clock=clock)
    cached = counters(store, clock)
    cached.current()  # reads from 0 s to 4 s
    store.counted = FRESH

    clock.advance(timedelta(seconds=14))
    assert cached.current() == COUNTS
    clock.advance(timedelta(seconds=1))
    assert cached.current() == FRESH
    assert store.calls == ["counts", "counts"]


def test_a_slow_failed_read_is_remembered_15_seconds_from_its_end() -> None:
    clock = FixedClock()
    store = TakesTime(error=StorageUnavailable("test"), clock=clock)
    cached = counters(store, clock)
    cached.current()
    store.error = None
    store.counted = COUNTS

    clock.advance(timedelta(seconds=14))
    assert cached.current() is None
    assert store.calls == ["counts"]


def answer_at_once(call: Callable[[], Counts | None]) -> Counts | None:
    """``call()`` in another thread; the test fails unless it answers within ``AT_ONCE``."""
    answers: list[Counts | None] = []
    thread = threading.Thread(target=lambda: answers.append(call()), daemon=True)
    thread.start()
    thread.join(AT_ONCE)
    assert answers, f"the call waited longer than {AT_ONCE} s"
    return answers[0]


def held_read(cached: CachedCounters, store: SlowStore) -> threading.Thread:
    """A call that reads the store and hangs in the read until ``store.done`` is set."""
    store.held = True
    reader = threading.Thread(target=cached.current)
    reader.start()
    assert store.reading.wait(HOLD_LIMIT)
    return reader


def test_while_one_call_reads_the_others_answer_at_once_with_the_latest_numbers() -> None:
    """Sync routes run in the site's thread pool: a call that waited for another's read would
    hold a thread of the site as long as the read lasts."""
    store, clock = SlowStore(counted=COUNTS), FixedClock()
    cached = counters(store, clock)
    cached.current()
    store.counted = FRESH
    clock.advance(CACHE_TTL)
    reader = held_read(cached, store)

    try:
        answers = [answer_at_once(cached.current) for _ in range(8)]
    finally:
        store.done.set()
        reader.join()

    assert answers == [COUNTS] * 8
    assert store.calls == ["counts", "counts"]
    assert cached.current() == FRESH


def test_while_the_first_read_lasts_the_others_answer_at_once_with_no_numbers() -> None:
    """No numbers yet: the page keeps «—» and asks again in 15 seconds."""
    store = SlowStore(counted=COUNTS)
    cached = counters(store, FixedClock())
    reader = held_read(cached, store)

    try:
        answers = [answer_at_once(cached.current) for _ in range(8)]
    finally:
        store.done.set()
        reader.join()

    assert answers == [None] * 8
    assert store.calls == ["counts"]
    assert cached.current() == COUNTS
