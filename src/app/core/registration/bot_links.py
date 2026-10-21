"""Personal links to the bot (docs/requirements.md, section 7): this slice issues the tokens.

A token is random, 43 characters of ``A-Z a-z 0-9 _ -`` (Telegram's ``start`` takes up to 64),
valid for seven days. ``screen`` tokens go to every success screen, ``email`` tokens to the
invitation; the slice «бот» decides what a use of each means. Without a bot
(``TELEGRAM_BOT_USERNAME`` empty, the bot settings go together) no token is issued: there is no
link to put it in, and the screen and the letter show their text without the button.
"""

import secrets
from datetime import timedelta

from app.core.entities import LinkSource, LinkToken
from app.core.ports import Clock, LinkTokenStore

TOKEN_TERM = timedelta(days=7)
TOKEN_BYTES = 32  # token_urlsafe: 43 characters of A-Z a-z 0-9 _ -


def new_token() -> str:
    """A fresh random token.

    >>> import re
    >>> bool(re.fullmatch(r"[A-Za-z0-9_-]{43}", new_token()))
    True
    """
    return secrets.token_urlsafe(TOKEN_BYTES)


def bot_link(bot_username: str, token: str) -> str:
    """``https://t.me/<bot>?start=<token>``.

    >>> bot_link("webinar_bot", "abc")
    'https://t.me/webinar_bot?start=abc'
    """
    return f"https://t.me/{bot_username}?start={token}"


class BotLinks:
    """Issues links to the bot; storage errors reach the caller."""

    def __init__(self, *, tokens: LinkTokenStore, clock: Clock, bot_username: str) -> None:
        self._tokens = tokens
        self._clock = clock
        self._bot = bot_username

    @property
    def enabled(self) -> bool:
        """Whether a bot is set up."""
        return bool(self._bot)

    def link(self, token: str) -> str:
        return bot_link(self._bot, token)

    def issue(self, participant_id: int, source: LinkSource) -> str | None:
        """A new token of ``source`` for the participant, as a link; ``None`` without a bot."""
        if not self._bot:
            return None
        now = self._clock.now()
        token = new_token()
        self._tokens.add(LinkToken(token, participant_id, source, now, now + TOKEN_TERM))
        return self.link(token)
