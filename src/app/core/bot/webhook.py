"""Registering the webhook: a few attempts, so that a temporary failure of Telegram passes.

Only a failure that may pass is tried again: a timeout, the network, a 5xx (``MessengerDown``)
and a 429 that says how long to wait (``retry_after``; the pause is then at least that long). A
refusal fails the same way every time (a wrong token, a wrong address) and ends the attempts at
once, as does a 429 without ``retry_after`` or one asking for more than ``RETRY_AFTER_LIMIT``
seconds. The log says the webhook is not registered once, after the last attempt; it names
exceptions by class, never the address or the secret.

>>> from app.core.bot.ports import MessengerDown
>>> class Telegram:
...     def __init__(self, *errors: Exception) -> None:
...         self.errors = list(errors)
...     def set_webhook(self, url: str, secret: str, allowed_updates: Sequence[str]) -> None:
...         if self.errors:
...             raise self.errors.pop(0)
>>> class Pause:
...     def __init__(self) -> None:
...         self.waited: list[float] = []
...     def wait(self, seconds: float) -> bool:
...         self.waited.append(seconds)
...         return True
...     def stop(self) -> None: ...
>>> pause = Pause()
>>> register_webhook(Telegram(MessengerDown(), MessengerDown()), pause, "url", "secret", ())
True
>>> pause.waited
[2.0, 10.0]
"""

import logging
from collections.abc import Sequence

from app.core.bot.ports import MessengerDown, MessengerRateLimited, Pause
from app.core.ports import Messenger, MessengerUnavailable

logger = logging.getLogger(__name__)

PAUSES = (2.0, 10.0, 30.0)  # seconds after the first, the second, the third failed attempt
ATTEMPTS = len(PAUSES) + 1
RETRY_AFTER_LIMIT = 60  # seconds; a 429 asking for longer ends the attempts


def register_webhook(
    messenger: Messenger, pause: Pause, url: str, secret: str, allowed_updates: Sequence[str]
) -> bool:
    """Set the webhook within ``ATTEMPTS`` attempts; ``True`` once it is registered."""
    attempt = 0
    while True:
        attempt += 1
        try:
            messenger.set_webhook(url, secret, allowed_updates)
        except MessengerUnavailable as error:
            seconds = _pause_after(error, attempt)
            if seconds is None:
                _log_not_registered(error, attempt)
                return False
            logger.warning(
                "Telegram webhook attempt %d of %d failed: %s; next in %g s",
                attempt,
                ATTEMPTS,
                type(error).__name__,
                seconds,
            )
            if not pause.wait(seconds):
                logger.info("Telegram webhook not registered: the application stops")
                return False
        else:
            logger.info("Telegram webhook registered")
            return True


def _pause_after(error: MessengerUnavailable, attempt: int) -> float | None:
    """Seconds to wait before the next attempt; ``None``: there is no next attempt."""
    if attempt >= ATTEMPTS:
        return None
    planned = PAUSES[attempt - 1]
    if isinstance(error, MessengerDown):
        return planned
    if isinstance(error, MessengerRateLimited) and error.retry_after is not None:
        if error.retry_after > RETRY_AFTER_LIMIT:
            return None
        return max(planned, float(error.retry_after))
    return None


def _log_not_registered(error: MessengerUnavailable, attempt: int) -> None:
    failure = type(error).__name__
    if attempt >= ATTEMPTS:
        logger.error("Telegram webhook not registered after %d attempts: %s", attempt, failure)
    elif isinstance(error, MessengerRateLimited) and error.retry_after is not None:
        logger.error(
            "Telegram webhook not registered: Telegram asks to wait %d s", error.retry_after
        )
    else:
        logger.error("Telegram webhook not registered: %s (not retried)", failure)
