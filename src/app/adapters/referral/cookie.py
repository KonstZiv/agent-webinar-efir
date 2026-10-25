"""Cookie ``ref``: the code of the link a visitor came by (docs/requirements.md, section 4).

Set on ``GET /?ref=<code>`` for a code of the right form, for 30 days: host-only, ``Secure``,
``HttpOnly``, ``SameSite=Lax`` (docs/legal/privacy.md, section 7). Whether the code belongs to
anyone is decided by the registration, which ignores an unknown one. A pure ASGI middleware,
as for ``src``: it adds a header to the start of the response and leaves the body alone.
"""

from http.cookies import SimpleCookie

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.referral.code import is_valid_code

REFERRAL_COOKIE = "ref"
QUERY_FIELD = "ref"
MAX_AGE_SECONDS = 30 * 24 * 60 * 60


def referral_cookie(code: str) -> str:
    """The ``Set-Cookie`` value of ``ref`` for a valid ``code``."""
    cookie: SimpleCookie = SimpleCookie()
    cookie[REFERRAL_COOKIE] = code
    morsel = cookie[REFERRAL_COOKIE]
    morsel["max-age"] = MAX_AGE_SECONDS
    morsel["path"] = "/"
    morsel["secure"] = True
    morsel["httponly"] = True
    morsel["samesite"] = "lax"
    return morsel.OutputString()


class ReferralCookie:
    """ASGI middleware: the page ``/`` opened by a personal link remembers the code."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "GET" or scope["path"] != "/":
            await self.app(scope, receive, send)
            return
        code = Request(scope).query_params.get(QUERY_FIELD)
        if not is_valid_code(code):
            await self.app(scope, receive, send)
            return

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] == 200:
                MutableHeaders(scope=message).append("set-cookie", referral_cookie(str(code)))
            await send(message)

        await self.app(scope, receive, send_with_cookie)
