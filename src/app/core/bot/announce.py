"""The post of a check-in in the channel: one code for the bot's command and the admin API.

The slice «бот» provides it under the key ``bot.checkin_post``; the slice «відмітка присутності»
finds it by that name and never imports this module. The post names the group and has one
button that opens the chat with the bot: a student sends the code there. Nothing is raised for
Telegram: a refusal is ``False`` and the log gets the class of the failure only.
"""

import logging
from datetime import date

from app.core.bot import attendance_replies as texts
from app.core.ports import Messenger, MessengerUnavailable

logger = logging.getLogger(__name__)


class CheckinPost:
    """Publishes the post of an open check-in in ``channel``."""

    def __init__(self, messenger: Messenger, channel: str, bot_username: str) -> None:
        self._messenger = messenger
        self._channel = channel
        self._bot_username = bot_username

    def announce(
        self, checkin_id: int, code: str, group: str | None, lesson_date: date, minutes: int
    ) -> bool:
        """Publish the post; ``False`` when Telegram refuses it.

        The post holds neither the code nor the id: the code goes only to the teacher's screen.
        """
        text = texts.POST.format(group=group or texts.NO_GROUP, window=minutes)
        try:
            self._messenger.send_message(
                self._channel,
                text,
                texts.post_buttons(self._bot_username),
                preview=False,
            )
        except MessengerUnavailable as error:
            logger.warning("Check-in post not published: %s", type(error).__name__)
            return False
        return True
