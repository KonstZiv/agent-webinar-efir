"""Paths that carry a secret token: one definition for every protection of the token.

A route such as ``/unsubscribe/{token}`` puts a permission into its address. Under each prefix
listed here the access log masks the next path segment, Google Analytics is not loaded (it
would receive the address), and responses carry ``Referrer-Policy: no-referrer``: a click to
another page of the site would otherwise send the full address in ``Referer``, and analytics
there would report it as the referring page. A route with a token goes under one of these
prefixes.

``/unsubscribe/`` comes before its route (docs/contract.md, section 10): masking works from the
first deploy. ``/m/`` is the materials page: its address is not a permission, but only the bot
gives it out (docs/contract.md, section 13).
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

TOKEN_PATH_PREFIXES: tuple[str, ...] = ("/unsubscribe/", "/m/")


def carries_token(path: str, prefixes: tuple[str, ...] | None = None) -> bool:
    """Whether ``path`` lies under one of ``prefixes`` (by default ``TOKEN_PATH_PREFIXES``).

    >>> carries_token("/t/abc", ("/t/",)), carries_token("/privacy", ("/t/",))
    (True, False)
    """
    chosen = TOKEN_PATH_PREFIXES if prefixes is None else prefixes
    return any(path.startswith(prefix) for prefix in chosen)


class NoReferrerOnTokenPaths:
    """ASGI middleware: every response under a token prefix forbids the ``Referer`` header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not carries_token(scope["path"]):
            await self.app(scope, receive, send)
            return

        async def send_without_referrer(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Referrer-Policy"] = "no-referrer"
            await send(message)

        await self.app(scope, receive, send_without_referrer)
