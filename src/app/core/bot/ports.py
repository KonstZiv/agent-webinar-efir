"""What the bot adds to the shared ``Messenger`` port (``app.core.ports``)."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Literal, Protocol

from app.core.ports import MessengerUnavailable

# Key of the attendance scenarios for Telegram: the slice «відмітка присутності» provides them,
# the bot only looks them up by this name and never imports that slice.
ATTENDANCE_KEY = "checkin.telegram"


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


# --- the attendance, as the bot asks for it -----------------------------------------------------
#
# The slice «відмітка присутності» implements ``AttendanceViaTelegram``; the bot cannot import
# its result types, so every answer is a Protocol of read-only fields that the other side meets
# with a dataclass of its own. ``status`` tells the cases apart; the other fields mean something
# only for the statuses that need them. Expected cases are statuses, never exceptions: ``failed``
# is a storage failure.


class Opened(Protocol):
    @property
    def status(self) -> Literal["opened", "open_exists", "failed"]: ...

    # ``open_exists``: the open check-in that stands in the way.
    @property
    def id(self) -> int: ...

    @property
    def code(self) -> str: ...

    @property
    def group(self) -> str: ...

    @property
    def closes_at(self) -> datetime: ...


class Closed(Protocol):
    @property
    def status(self) -> Literal["closed", "none", "failed"]: ...

    @property
    def id(self) -> int: ...

    @property
    def group(self) -> str | None: ...

    @property
    def closed_at(self) -> datetime: ...

    @property
    def attended(self) -> int: ...


class ReportSummary(Protocol):
    """A check-in with its counts and questions; no addresses."""

    @property
    def status(self) -> Literal["found", "none", "failed"]: ...

    @property
    def id(self) -> int: ...

    @property
    def lesson_date(self) -> date: ...

    @property
    def group(self) -> str | None: ...

    @property
    def attended(self) -> int: ...

    @property
    def site(self) -> int: ...

    @property
    def telegram(self) -> int: ...

    @property
    def ratings(self) -> Mapping[int, int]: ...

    @property
    def average(self) -> float | None: ...

    @property
    def questions(self) -> Sequence[str]: ...


class Pressed(Protocol):
    """The answer to a code, to a rating and to a question."""

    @property
    def status(
        self,
    ) -> Literal[
        "marked",
        "already",
        "not_linked",
        "closed",
        "rated",
        "too_late",
        "not_marked",
        "saved",
        "too_long",
        "failed",
    ]: ...

    @property
    def lesson_date(self) -> date: ...

    # The check-in the answer is about (a code that fits); ``group`` is ``None`` for one without.
    @property
    def checkin_id(self) -> int: ...

    @property
    def group(self) -> str | None: ...


class AttendanceViaTelegram(Protocol):
    """What the bot needs of the attendance; none of the methods raises for an expected case."""

    def known_groups(self, limit: int) -> Sequence[str] | None:
        """Group codes to pick from, the freshest first; ``None`` — the storage failed."""
        ...

    def open(self, lesson_date: date, group: str, window_minutes: int) -> Opened:
        """Open a check-in of ``group``, unless it has an open one (``open_exists``)."""
        ...

    def close(self, group: str | None) -> Closed:
        """Close the open check-in of ``group`` (the latest open of any group if ``None``)."""
        ...

    def report(self, group: str | None) -> ReportSummary:
        """The report of the latest check-in of ``group`` (of any group if ``None``)."""
        ...

    def mark_code(self, code: str, tg_user_id: int) -> Pressed:
        """Mark the participant with this Telegram on the open check-in with ``code``:
        ``marked``, ``already``, ``not_linked``, ``closed`` (no open check-in has the code),
        or ``failed``."""
        ...

    def rate(self, checkin_id: int, tg_user_id: int, rating: int) -> Pressed:
        """``rated``, ``too_late``, ``not_marked`` or ``failed``."""
        ...

    def ask(self, tg_user_id: int, text: str) -> Pressed:
        """``saved``, ``too_long`` (nothing added), ``not_marked`` (ignored) or ``failed``."""
        ...
