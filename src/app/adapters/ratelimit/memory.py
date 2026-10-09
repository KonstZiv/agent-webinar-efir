"""In-process rate limiter: one service instance, counters live in memory."""

import threading
from collections import deque
from datetime import datetime, timedelta

from app.core.ports import Clock


class InMemoryRateLimiter:
    """``RateLimiter``: at most ``limit`` attempts per key within a sliding ``window``.

    Refused attempts are not recorded, so a blocked client is let in again one window after
    its last allowed attempt. Sync routes run in a thread pool, hence the lock.
    """

    def __init__(self, *, limit: int, window: timedelta, clock: Clock) -> None:
        self._limit = limit
        self._window = window
        self._clock = clock
        self._attempts: dict[str, deque[datetime]] = {}
        self._lock = threading.Lock()
        self._last_sweep = clock.now()

    def allow(self, key: str) -> bool:
        now = self._clock.now()
        start = now - self._window
        with self._lock:
            if now - self._last_sweep >= self._window:
                self._sweep(start)
                self._last_sweep = now
            attempts = self._attempts.setdefault(key, deque())
            while attempts and attempts[0] <= start:
                attempts.popleft()
            if len(attempts) >= self._limit:
                return False
            attempts.append(now)
            return True

    def refund(self, key: str) -> None:
        with self._lock:
            attempts = self._attempts.get(key)
            if attempts:
                attempts.pop()

    @property
    def tracked_keys(self) -> int:
        """Number of keys currently held in memory."""
        with self._lock:
            return len(self._attempts)

    def _sweep(self, start: datetime) -> None:
        """Forget keys without attempts inside the window (bounded memory)."""
        idle = [
            key for key, attempts in self._attempts.items() if not attempts or attempts[-1] <= start
        ]
        for key in idle:
            del self._attempts[key]
