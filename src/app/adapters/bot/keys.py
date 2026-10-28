"""Services of the slice «бот» by key (``app.services``), named ``bot.*``.

The keys live here, not in ``app.slices.bot``: the route imports them, and a route module must
import without the slice package (the foundation's tests swap ``app.slices`` for a sample).
Without the bot settings nobody provides them, and the webhook answers 404.
"""

from app.adapters.bot.workers import BotWorkers
from app.core.bot.announce import CheckinPost
from app.core.bot.dialog import BotDialog
from app.core.bot.ports import ATTENDANCE_KEY, AttendanceViaTelegram, Pause
from app.services import Key

DIALOG = Key[BotDialog]("bot.dialog")
# Provided by the slice «відмітка присутності»; the bot only finds it, without that slice's code.
ATTENDANCE = Key[AttendanceViaTelegram](ATTENDANCE_KEY)
WORKERS = Key[BotWorkers]("bot.workers")
# The post of a check-in in the channel; the slice «відмітка присутності» finds it by this name.
CHECKIN_POST = Key[CheckinPost]("bot.checkin_post")
PAUSE = Key[Pause]("bot.pause")  # between the attempts to register the webhook
