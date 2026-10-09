"""In-memory sliding-window rate limiter."""

from datetime import UTC, datetime, timedelta

from app.adapters.ratelimit.memory import InMemoryRateLimiter
from tests.fakes import FixedClock

START = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)


def make(
    limit: int = 3, window: timedelta = timedelta(minutes=1)
) -> tuple[InMemoryRateLimiter, FixedClock]:
    clock = FixedClock(START)
    return InMemoryRateLimiter(limit=limit, window=window, clock=clock), clock


def test_allows_up_to_the_limit_within_the_window() -> None:
    limiter, _ = make()

    assert [limiter.allow("a") for _ in range(4)] == [True, True, True, False]


def test_keys_are_independent() -> None:
    limiter, _ = make(limit=1)

    assert limiter.allow("a")
    assert limiter.allow("b")
    assert not limiter.allow("a")


def test_window_slides() -> None:
    limiter, clock = make()
    limiter.allow("a")
    clock.advance(timedelta(seconds=30))
    limiter.allow("a")
    limiter.allow("a")
    assert not limiter.allow("a")

    clock.advance(timedelta(seconds=30))  # the first attempt is a minute old now
    assert limiter.allow("a")
    assert not limiter.allow("a")


def test_refused_attempts_do_not_extend_the_block() -> None:
    limiter, clock = make(limit=1)
    limiter.allow("a")
    for _ in range(10):
        clock.advance(timedelta(seconds=5))
        assert not limiter.allow("a")

    clock.advance(timedelta(seconds=10))  # a minute after the only recorded attempt
    assert limiter.allow("a")


def test_idle_keys_are_forgotten() -> None:
    limiter, clock = make()
    for key in ("a", "b", "c"):
        limiter.allow(key)
    assert limiter.tracked_keys == 3

    clock.advance(timedelta(minutes=2))
    limiter.allow("d")

    assert limiter.tracked_keys == 1


def test_refund_gives_the_attempt_back() -> None:
    limiter, _ = make(limit=2)
    limiter.allow("a")
    limiter.allow("a")
    assert not limiter.allow("a")

    limiter.refund("a")

    assert limiter.allow("a")
    assert not limiter.allow("a")


def test_refund_of_an_unknown_key_does_nothing() -> None:
    limiter, _ = make(limit=1)

    limiter.refund("never-seen")

    assert limiter.allow("never-seen")
    assert not limiter.allow("never-seen")
