"""Redirect mode: with ``REDIRECT_BASE_URL`` set, every request but the health check gets a 307.

The same path and query go to the new address unchanged. 307 keeps the method and body, and
``Cache-Control: no-store`` keeps browsers and caches from remembering the answer: another
site will serve this address later, so a permanent redirect (301, 308) is never used.
"""

from collections.abc import Mapping
from urllib.parse import quote

from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.adapters.web.routers.health import HEALTH_PATH

STATUS = 307


def redirect_location(base_url: str, raw_path: bytes, query_string: bytes) -> str:
    """``base_url`` plus the request path and query exactly as the client sent them.

    ``base_url`` is a site root without a trailing slash (``Settings`` makes sure). A path
    that does not start with ``/`` gets one, so the location always stays on that host.

    >>> redirect_location("https://new.example.com", b"/a%20b", b"x=1&y=%2F")
    'https://new.example.com/a%20b?x=1&y=%2F'
    >>> redirect_location("https://new.example.com", b"http://evil.example.org/", b"")
    'https://new.example.com/http://evil.example.org/'
    """
    path = raw_path.decode("latin-1")
    if not path.startswith("/"):
        path = f"/{path}"
    query = query_string.decode("latin-1")
    return f"{base_url}{path}?{query}" if query else f"{base_url}{path}"


def _raw_path(scope: Scope) -> bytes:
    """The path as sent; servers that leave out ``raw_path`` get the decoded path re-encoded."""
    raw_path = scope.get("raw_path")
    if isinstance(raw_path, bytes):
        return raw_path
    return quote(scope["path"], safe="/").encode("ascii")


class RedirectEverything:
    """ASGI middleware that answers every HTTP request but the health check with a 307.

    ``extra_headers`` go with every redirect, e.g. ``X-Robots-Tag`` while indexing is off:
    this middleware wraps the others, so they never see its answers.
    """

    def __init__(
        self, app: ASGIApp, *, base_url: str, extra_headers: Mapping[str, str] | None = None
    ) -> None:
        self.app = app
        self.base_url = base_url
        self.extra_headers = dict(extra_headers or {})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == HEALTH_PATH:
            await self.app(scope, receive, send)
            return
        location = redirect_location(self.base_url, _raw_path(scope), scope["query_string"])
        headers = {**self.extra_headers, "location": location, "cache-control": "no-store"}
        response = Response(status_code=STATUS, headers=headers)
        await response(scope, receive, send)
