from datetime import UTC, datetime, timedelta

from app.adapters.clock import SystemClock


def test_system_clock_gives_current_utc_time() -> None:
    before = datetime.now(UTC)
    now = SystemClock().now()
    after = datetime.now(UTC)

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
    assert before <= now <= after
