"""The webhook registered on a thread of its own: the application does not wait for Telegram.

Railway takes the service as ready by ``/healthz``. The registration (``app.core.bot.webhook``)
may take a minute of attempts and pauses, so the start-up action only starts its thread. When
the application stops, ``StoppablePause`` ends the wait at once, and the thread has
``STOP_WAIT`` seconds to finish an attempt before the HTTP client is closed.
"""

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

STOP_WAIT = 2.0
THREAD_NAME = "bot-webhook"


class StoppablePause:
    """``Pause`` on a ``threading.Event``: ``stop`` ends the current wait and every next one."""

    def __init__(self) -> None:
        self._stopping = threading.Event()

    def wait(self, seconds: float) -> bool:
        return not self._stopping.wait(seconds)

    def stop(self) -> None:
        self._stopping.set()


class WebhookThread:
    """Runs the registration once, on a daemon thread of its own."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None

    def start(self, register: Callable[[], object]) -> None:
        self._thread = threading.Thread(
            target=_run, args=(register,), name=THREAD_NAME, daemon=True
        )
        self._thread.start()

    def join(self, timeout: float) -> None:
        """Wait at most ``timeout`` seconds for the registration to end, if it has started."""
        if self._thread is not None:
            self._thread.join(timeout)


def _run(register: Callable[[], object]) -> None:
    try:
        register()
    except Exception as error:  # a closed client at shut-down, a bug: the thread ends quietly
        # The message may hold a secret (a bot token in a URL): the class only.
        logger.error("Telegram webhook not registered: %s", type(error).__name__)
