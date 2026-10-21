"""Slow mail during a mass registration leaves the pages answering (requirements, sections 5, 6).

Right after an announcement Resend is the most likely to answer 429, and one letter may then take
up to 15 s. Letters go out on two threads of their own, as many at once as Resend allows by
default; the shared threads that serve the pages stay free. The test shrinks the application's
shared thread pool (AnyIO's, Starlette's runner of plain functions) to four threads, so a handful
of registrations shows what forty letters would do on the real one.
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import anyio.to_thread

from app.core.entities import DeliveryResult, OutgoingEmail
from tests.fakes import FakeEmailSender
from tests.registration.conftest import SiteFactory
from tests.registration.helpers import VALID

SHARED_THREADS = 4
REGISTRATIONS = SHARED_THREADS + 2
MAIL_AT_ONCE = 2


class StalledSender(FakeEmailSender):
    """Resend that answers only once ``released``; counts the letters in flight."""

    def __init__(self) -> None:
        super().__init__()
        self.released = threading.Event()
        self.started = threading.Semaphore(0)
        self._lock = threading.Lock()
        self._in_flight = 0
        self.most_in_flight = 0

    def send(self, message: OutgoingEmail, idempotency_key: uuid.UUID) -> DeliveryResult:
        with self._lock:
            self._in_flight += 1
            self.most_in_flight = max(self.most_in_flight, self._in_flight)
        self.started.release()
        self.released.wait(timeout=30)
        with self._lock:
            self._in_flight -= 1
        return super().send(message, idempotency_key)


def shrink_the_shared_pool() -> None:
    anyio.to_thread.current_default_thread_limiter().total_tokens = SHARED_THREADS


def test_pages_answer_while_slow_mail_queues_up(site_factory: SiteFactory) -> None:
    sender = StalledSender()
    site = site_factory(email_sender=sender)
    assert site.client.portal is not None
    site.client.portal.call(shrink_the_shared_pool)
    visitors = ThreadPoolExecutor(max_workers=REGISTRATIONS + 1)
    try:
        registrations = [
            visitors.submit(site.register, {**VALID, "email": f"visitor{number}@example.com"})
            for number in range(REGISTRATIONS)
        ]
        for _ in range(MAIL_AT_ONCE):
            assert sender.started.acquire(timeout=10)  # letters are on their way, and stuck

        home = visitors.submit(site.client.get, "/")

        assert home.result(timeout=5).status_code == 200
        assert sender.most_in_flight == MAIL_AT_ONCE
    finally:
        sender.released.set()
        visitors.shutdown(wait=True)
    assert [future.result().status_code for future in registrations] == [200] * REGISTRATIONS
    assert sender.most_in_flight == MAIL_AT_ONCE
    assert len(sender.sent) == REGISTRATIONS
