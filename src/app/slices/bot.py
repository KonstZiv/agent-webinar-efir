"""The slice «бот»: Telegram linked to a registration, the channel checked, the materials given.

Without the bot settings (the four ``TELEGRAM_*`` go together, ``Settings`` checks it) the slice
adds nothing: the webhook answers 404 and the site works. Otherwise ``install`` provides the
shared port ``MESSENGER`` (Telegram Bot API), the dialog and the bot's threads by key
(``app.adapters.bot.keys``), all built on first use: creating the application builds no client
and reaches no network. The client and the threads are closed when the application stops.

The webhook is registered at start-up only from an ``https://`` site: a local run with the keys
of staging must not take staging's webhook. Telegram may send as many updates at once as the
bot has threads (``max_connections``): the rest wait in Telegram rather than in the process,
where a slow Telegram would hold them long enough to get them sent again. The registration is
not critical and runs on a thread of its own (``WebhookThread``): the site starts without
waiting for Telegram. A temporary failure is tried again after a pause (``bot.pause``), and the
log says the webhook is not registered only after the last attempt (``app.core.bot.webhook``);
when the application stops, the pause ends at once. The messenger and the pause are built by
the start-up action, before the thread starts. Without ``MATERIALS_SLUG`` the bot still links
and checks, but has no materials link to give: the log says so at start.
"""

import logging
from functools import partial

from app.adapters.bot import telegram
from app.adapters.bot.keys import DIALOG, LLM_RESPONDER, PAUSE, WORKERS
from app.adapters.bot.webhook import STOP_WAIT, StoppablePause, WebhookThread
from app.adapters.bot.workers import BOT_AT_ONCE, BotWorkers
from app.adapters.web.routers.bot import PATH
from app.core.bot.dialog import BotDialog
from app.core.bot.replies import Replies
from app.core.bot.webhook import register_webhook
from app.core.ports import Messenger
from app.services import CLOCK, LINK_TOKENS, MESSENGER, PARTICIPANTS
from app.slices import SliceSetup

logger = logging.getLogger(__name__)

ALLOWED_UPDATES = ("message", "callback_query")  # chat_member comes with S2, after the webinar
MATERIALS_PREFIX = "/m/"


def install(setup: SliceSetup) -> None:
    settings = setup.settings
    services = setup.services
    token, secret = settings.telegram_bot_token, settings.telegram_webhook_secret
    if token is None or secret is None:  # no bot group: nothing to install
        return
    site_url = settings.public_base_url
    materials_url = None
    if settings.materials_slug:
        materials_url = site_url + MATERIALS_PREFIX + settings.materials_slug
    else:
        logger.error("MATERIALS_SLUG is not set: the bot cannot give the materials link")

    def messenger() -> Messenger:
        client = telegram.make_http_client()
        setup.close_on_shutdown(client.close)
        return telegram.TelegramMessenger(token, client, max_connections=BOT_AT_ONCE)

    def workers() -> BotWorkers:
        threads = BotWorkers(BOT_AT_ONCE)
        setup.close_on_shutdown(threads.close)
        return threads

    setup.provide(MESSENGER, messenger)
    setup.provide(WORKERS, workers)
    setup.provide(
        DIALOG,
        lambda: BotDialog(
            participants=services.get(PARTICIPANTS),
            tokens=services.get(LINK_TOKENS),
            messenger=services.get(MESSENGER),
            clock=services.get(CLOCK),
            replies=Replies(
                site_url=site_url, materials_url=materials_url, channel=settings.telegram_channel
            ),
            channel=settings.telegram_channel,
            free_text=services.find(LLM_RESPONDER),  # only on staging with LLM_ENABLED
        ),
    )

    if not site_url.startswith("https://"):
        logger.info("Telegram webhook not registered: PUBLIC_BASE_URL is not https")
        return

    setup.provide(PAUSE, StoppablePause)
    registration = WebhookThread()

    def start_webhook_registration() -> None:
        # Built here, on the main thread, not by the registration's thread.
        messenger, pause = services.get(MESSENGER), services.get(PAUSE)
        url, value = site_url + PATH, secret.get_secret_value()
        registration.start(partial(register_webhook, messenger, pause, url, value, ALLOWED_UPDATES))

    def stop_webhook_registration() -> None:
        services.get(PAUSE).stop()
        registration.join(STOP_WAIT)

    setup.on_startup(start_webhook_registration)
    setup.on_shutdown(stop_webhook_registration)
