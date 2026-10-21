"""Services of the slice «бот» by key (``app.services``), named ``bot.*``.

The keys live here, not in ``app.slices.bot``: the route imports them, and a route module must
import without the slice package (the foundation's tests swap ``app.slices`` for a sample).
Without the bot settings nobody provides them, and the webhook answers 404.
"""

from app.adapters.bot.workers import BotWorkers
from app.core.bot.dialog import BotDialog
from app.core.bot.ports import Pause
from app.services import Key

DIALOG = Key[BotDialog]("bot.dialog")
WORKERS = Key[BotWorkers]("bot.workers")
PAUSE = Key[Pause]("bot.pause")  # between the attempts to register the webhook
