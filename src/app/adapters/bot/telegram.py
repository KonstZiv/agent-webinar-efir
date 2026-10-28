"""Telegram Bot API over HTTP (``Messenger`` port; docs/requirements.md, section 7).

https://core.telegram.org/bots/api

Every call is ``POST https://api.telegram.org/bot<token>/<method>`` with a JSON body. The token
is a part of the address, so no address leaves this module: a failure becomes
``MessengerUnavailable`` raised ``from None`` (no traceback shows the request), and the log
names the method, the HTTP status and Telegram's error code. httpx itself logs every request
with its address at INFO: ``MaskBotToken`` on its logger replaces the token with ``***``, as the
foundation masks tokens in the access log.

A 429 fails at once as ``MessengerRateLimited`` with Telegram's ``retry_after``: the handler of
an update never waits it out. Only a 429 on ``sendMessage`` makes the webhook answer 503, so that
Telegram delivers the update again later; on ``getChatMember`` the dialog tells the person the
check failed (200), on ``answerCallbackQuery`` it is only logged. Timeouts bound each phase of a
request, as for Turnstile.

A failure that may pass a few seconds later (a timeout, the network, a 5xx) is ``MessengerDown``;
any other is a plain ``MessengerUnavailable``: a refusal (a wrong token or address, an answer of
an unexpected shape) fails the same way every time. Only the registration of the webhook tells
them apart (``app.core.bot.webhook``): it tries again ``MessengerDown`` and a 429 with
``retry_after``.

``setWebhook`` takes ``max_connections``, the number of updates Telegram sends at once: the bot
sets it to the size of its pool, so the updates its threads cannot take yet wait in Telegram.
"""

import logging
import re
from collections.abc import Sequence

import httpx
from pydantic import SecretStr

from app.core.bot.ports import MessengerDown, MessengerRateLimited
from app.core.entities import Button, ChatMember
from app.core.ports import MessengerUnavailable

logger = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = httpx.Timeout(5.0, connect=3.0)
TOO_MANY_REQUESTS = 429
SERVER_ERROR = 500  # this status and above: Telegram failed, not the request
# Failures of the connection that may pass; a token httpx rejects (InvalidURL) never does.
_TEMPORARY = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
# Telegram's descriptions are fixed English phrases; one with digits may name a chat or a user.
_DESCRIPTION = re.compile(r"[A-Za-z :'_.,()-]{1,200}")

HTTPX_LOGGER = "httpx"
_TOKEN_IN_ADDRESS = re.compile(r"/bot[^/\s]+/")
MASKED = "/bot***/"

type Json = dict[str, object]


class MaskBotToken(logging.Filter):
    """httpx logs every request with its address at INFO; the token in it becomes ``***``."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        masked = _TOKEN_IN_ADDRESS.sub(MASKED, message)
        if masked != message:
            record.msg, record.args = masked, None
        return True


def install_token_mask() -> None:
    """Give httpx's logger exactly one ``MaskBotToken``."""
    httpx_logger = logging.getLogger(HTTPX_LOGGER)
    if not any(isinstance(item, MaskBotToken) for item in httpx_logger.filters):
        httpx_logger.addFilter(MaskBotToken())


def make_http_client() -> httpx.Client:
    """HTTP client for the Bot API; the caller closes it (``close_on_shutdown``)."""
    return httpx.Client(timeout=TIMEOUT)


def _button(button: Button) -> Json:
    if button.url is not None:
        return {"text": button.text, "url": button.url}
    return {"text": button.text, "callback_data": button.callback_data}


def _body(response: httpx.Response) -> Json | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _retry_after(body: Json | None) -> int | None:
    parameters = body.get("parameters") if body is not None else None
    seconds = parameters.get("retry_after") if isinstance(parameters, dict) else None
    return seconds if type(seconds) is int else None


def _details(response: httpx.Response, body: Json | None) -> str:
    """``HTTP 400, error 400 (Bad Request: …)``: nothing but known shapes."""
    found = f"HTTP {response.status_code}"
    if body is not None:
        code = body.get("error_code")
        if type(code) is int:
            found += f", error {code}"
        description = body.get("description")
        if isinstance(description, str) and _DESCRIPTION.fullmatch(description):
            found += f" ({description})"
    return found


class TelegramMessenger:
    """The Bot API calls the bot needs; every failure is ``MessengerUnavailable``.

    ``max_connections`` goes to ``setWebhook``: at most that many updates at once.
    """

    def __init__(self, token: SecretStr, client: httpx.Client, *, max_connections: int) -> None:
        install_token_mask()
        self._token = token
        self._client = client
        self._max_connections = max_connections

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        buttons: Sequence[Sequence[Button]] = (),
        *,
        html: bool = False,
        preview: bool = True,
    ) -> None:
        payload: Json = {"chat_id": chat_id, "text": text}
        if html:
            payload["parse_mode"] = "HTML"
        if not preview:
            payload["link_preview_options"] = {"is_disabled": True}
        rows = [[_button(button) for button in row] for row in buttons]
        if rows:
            payload["reply_markup"] = {"inline_keyboard": rows}
        self._call("sendMessage", payload)

    def answer_callback(
        self, callback_id: str, text: str | None = None, show_alert: bool = False
    ) -> None:
        payload: Json = {"callback_query_id": callback_id}
        if text is not None:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = True
        self._call("answerCallbackQuery", payload)

    def channel_member(self, channel: str, user_id: int) -> ChatMember:
        result = self._call("getChatMember", {"chat_id": channel, "user_id": user_id})
        status = result.get("status") if isinstance(result, dict) else None
        if not isinstance(status, str) or not isinstance(result, dict):
            logger.warning("Telegram getChatMember answered without a status")
            raise MessengerUnavailable
        is_member = result.get("is_member")
        return ChatMember(status, is_member if isinstance(is_member, bool) else None)

    def set_webhook(self, url: str, secret: str, allowed_updates: Sequence[str]) -> None:
        payload: Json = {
            "url": url,
            "secret_token": secret,
            "allowed_updates": list(allowed_updates),
            "max_connections": self._max_connections,
        }
        self._call("setWebhook", payload)

    def _call(self, method: str, payload: Json) -> object:
        """The ``result`` of a successful call."""
        url = API_URL.format(token=self._token.get_secret_value(), method=method)
        try:
            response = self._client.post(url, json=payload)
        except (httpx.HTTPError, httpx.InvalidURL) as error:  # InvalidURL: a token httpx rejects
            logger.warning("Telegram %s failed: %s", method, type(error).__name__)
            failure = MessengerDown if isinstance(error, _TEMPORARY) else MessengerUnavailable
            raise failure from None
        body = _body(response)
        if response.status_code == TOO_MANY_REQUESTS:
            retry_after = _retry_after(body)
            shown = "?" if retry_after is None else retry_after
            logger.warning("Telegram %s: HTTP 429, retry after %s s", method, shown)
            raise MessengerRateLimited(retry_after)
        if not response.is_success or body is None or body.get("ok") is not True:
            logger.warning("Telegram %s failed: %s", method, _details(response, body))
            if response.status_code >= SERVER_ERROR:
                raise MessengerDown
            raise MessengerUnavailable
        return body.get("result")
