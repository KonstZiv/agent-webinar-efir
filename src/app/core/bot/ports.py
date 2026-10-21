"""What the bot adds to the shared ``Messenger`` port (``app.core.ports``)."""

from typing import Protocol

from app.core.ports import MessengerUnavailable


class MessengerDown(MessengerUnavailable):
    """Telegram did not answer in time, the network failed, or Telegram failed (5xx).

    The same request may work a few seconds later; a plain ``MessengerUnavailable`` is a
    refusal (a wrong token or address) that fails the same way every time.
    """


class MessengerRateLimited(MessengerUnavailable):
    """Telegram answered 429: the update is to be handled again later, not waited out.

    ``retry_after`` is how many seconds Telegram asks to wait, ``None`` if it did not say.
    """

    def __init__(self, retry_after: int | None = None) -> None:
        super().__init__()
        self.retry_after = retry_after


class Pause(Protocol):
    """The wait between two attempts to register the webhook."""

    def wait(self, seconds: float) -> bool:
        """Wait ``seconds``; ``False``: the application stops, and the attempts end."""
        ...

    def stop(self) -> None:
        """End every wait at once, the current one and the next ones: the application stops."""
        ...
