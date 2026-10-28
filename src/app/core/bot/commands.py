"""What a person asks the bot, read from a Telegram update (``app.adapters.bot.updates``).

Commands come from private chats; in them the chat id is the user's id, but the core keeps
both, as Telegram sends them.
"""

from dataclasses import dataclass

from app.core.entities import TelegramAccount


@dataclass(frozen=True, slots=True)
class Start:
    """``/start``; ``payload`` is the text after it (the token of a link), ``None`` if empty."""

    chat_id: int
    account: TelegramAccount
    payload: str | None = None


@dataclass(frozen=True, slots=True)
class Recheck:
    """The button «Перевірити ще раз» under a message of the bot."""

    chat_id: int
    account: TelegramAccount
    callback_id: str


@dataclass(frozen=True, slots=True)
class TeacherCommand:
    """``/checkin``, ``/checkin_close`` or ``/checkin_report`` with the text after it."""

    chat_id: int
    user_id: int
    name: str  # without the slash and the bot's name
    arguments: str


@dataclass(frozen=True, slots=True)
class PickGroup:
    """The button of a group under «Оберіть групу»: open its check-in."""

    chat_id: int
    user_id: int
    callback_id: str
    group: str


@dataclass(frozen=True, slots=True)
class Code:
    """A private message that is a check-in code: 4 characters of its alphabet, in upper case."""

    chat_id: int
    user_id: int
    code: str


@dataclass(frozen=True, slots=True)
class Rate:
    """A rating button of the private message sent after the mark."""

    chat_id: int
    user_id: int
    callback_id: str
    checkin_id: int
    rating: int


@dataclass(frozen=True, slots=True)
class Question:
    """A text in a private chat that is not a command: a question to the trainer, maybe."""

    chat_id: int
    user_id: int
    text: str


type AttendanceCommand = TeacherCommand | PickGroup | Code | Rate | Question
type Command = Start | Recheck | AttendanceCommand
# The classes of ``AttendanceCommand`` for ``isinstance``, which cannot take the alias.
ATTENDANCE_COMMANDS = (TeacherCommand, PickGroup, Code, Rate, Question)
