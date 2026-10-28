"""``POST /telegram/webhook``: updates of the bot (docs/requirements.md, section 7).

The secret of ``X-Telegram-Bot-Api-Secret-Token`` is compared in constant time before the body is
read and before any service of the bot is built: a wrong one gets 403 and nothing else. Without
the bot settings there is no secret and nobody provides the dialog: the route answers 404 as if
it did not exist; the site works on.

Every update Telegram sent and the bot does not handle gets 200, so that Telegram does not send
it again; so does a body that does not parse. A command runs on the bot's own threads
(``BotWorkers``), never on the shared ones of the pages. A database outage and a 429 of Telegram
on ``sendMessage`` get 503: Telegram delivers the update again, and the rules give the same link
the second time. A 429 on ``getChatMember`` is «the check failed» for the person and 200, one on
``answerCallbackQuery`` is only logged (``app.core.bot.dialog``). Any other storage failure is a
bug a retry would repeat: 200 and an error in the log. The attendance (``app.core.bot.attendance``)
never fails an update: its answers and failures are statuses, and a message Telegram does not take
is only logged, so that a retry cannot add a question twice. The log names the kind of update and
its result, never its body, ids, tokens, codes or questions.
"""

import hmac
import logging

from fastapi import APIRouter, HTTPException, Request, Response

from app.adapters.bot.keys import DIALOG, WORKERS
from app.adapters.bot.updates import parse_update
from app.adapters.web.dependencies import get_container
from app.core.bot.commands import (
    Command,
    PickGroup,
    Press,
    Question,
    Rate,
    Recheck,
    Start,
    TeacherCommand,
)
from app.core.bot.ports import MessengerRateLimited
from app.core.ports import StorageError, StorageUnavailable

logger = logging.getLogger(__name__)

router = APIRouter()

PATH = "/telegram/webhook"
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


def _kind(command: Command) -> str:
    """The kind of an update for the log: never its text, ids or tokens."""
    match command:
        case Start():
            return "start" if command.payload is None else "start_token"
        case Recheck():
            return "recheck"
        case TeacherCommand():
            return command.name
        case PickGroup():
            return "pick_group"
        case Press():
            return "press"
        case Rate():
            return "rate"
        case Question():
            return "question"


@router.post(PATH)
async def telegram_webhook(request: Request) -> Response:
    # The services come straight from the container, not from ``Depends(service(KEY))``: that
    # dependency is a plain function FastAPI runs on a shared thread, and without the bot group
    # it raises ``LookupError`` (500) where the route answers 404.
    container = get_container(request)
    secret = container.settings.telegram_webhook_secret
    if secret is None:
        raise HTTPException(status_code=404)
    given = request.headers.get(SECRET_HEADER, "")
    if not hmac.compare_digest(given.encode(), secret.get_secret_value().encode()):
        return Response(status_code=403)
    # Built on first use: only for a request with the secret.
    dialog = container.services.find(DIALOG)
    workers = container.services.find(WORKERS)
    if dialog is None or workers is None:
        raise HTTPException(status_code=404)
    command = parse_update(await request.body())
    if command is None:
        logger.info("Telegram update ignored")
        return Response(status_code=200)
    kind = _kind(command)
    try:
        outcome = await workers.run(dialog.handle, command)
    except (StorageUnavailable, MessengerRateLimited) as error:
        logger.warning("Telegram update %s postponed: %s", kind, type(error).__name__)
        return Response(status_code=503)
    except StorageError as error:
        logger.error("Telegram update %s failed: %s", kind, type(error).__name__)
        return Response(status_code=200)
    logger.info("Telegram update %s: %s", kind, outcome)
    return Response(status_code=200)
