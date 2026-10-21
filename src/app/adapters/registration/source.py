"""Cookie ``src``: where the visitor came from (requirements, section 5; contract, section 10).

Set on the first HTML page a browser opens and never overwritten while it lives; the
registration reads it, so the source reaches the participant even after a walk through the
site. Name and format are v1's (``webinar.adapters.web.source``): host-only, ``HttpOnly``,
30 days, base64url of compact JSON, so the value carries no character cookies forbid. Pages
with a token in the path never set it: their address would carry the token into the row.

A pure ASGI middleware: it adds a header to the start of the response and leaves the body and
the background tasks (the invitation) alone.
"""

import base64
import json
from collections.abc import Mapping
from dataclasses import asdict, fields
from http.cookies import SimpleCookie

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.adapters.web.token_paths import carries_token
from app.core.entities import SOURCE_VALUE_LENGTH, TrafficSource

SOURCE_COOKIE = "src"
MAX_AGE_SECONDS = 30 * 24 * 60 * 60
# Browsers drop cookies over 4096 bytes (name, value and attributes together).
MAX_COOKIE_LENGTH = 3800
SOURCE_FIELDS = tuple(item.name for item in fields(TrafficSource))
QUERY_FIELDS = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "gbraid",
    "wbraid",
)


def make_source(values: Mapping[str, object]) -> TrafficSource:
    """A source from the known string values; ``TrafficSource`` makes them storable."""
    return TrafficSource(
        **{name: value for name in SOURCE_FIELDS if isinstance(value := values.get(name), str)}
    )


def capture_source(request: Request) -> TrafficSource:
    """Source values of this request: click parameters, the page address, the referrer."""
    values: dict[str, object] = {name: request.query_params.get(name) for name in QUERY_FIELDS}
    values["landing_url"] = str(request.url)
    values["referrer"] = request.headers.get("referer")
    return make_source(values)


def _encode(payload: dict[str, str]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def encode_source(source: TrafficSource) -> str:
    """Cookie value: base64url (no padding) of compact JSON with the non-empty fields.

    A source too long for a cookie keeps every field, each cut shorter step by step: without
    the cookie the next page would pass for the first one and the UTM tags would be lost.

    >>> decode_source(encode_source(TrafficSource(utm_source="telegram"))).utm_source
    'telegram'
    """
    values = {name: value for name, value in asdict(source).items() if value}
    limit = SOURCE_VALUE_LENGTH
    while True:
        encoded = _encode({name: value[:limit] for name, value in values.items() if limit})
        if len(encoded) <= MAX_COOKIE_LENGTH:
            return encoded
        limit //= 2


def decode_source(value: str | None) -> TrafficSource:
    """The source from a cookie value; anything damaged or foreign gives an empty source."""
    if not value:
        return TrafficSource()
    try:
        data = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        payload = json.loads(data.decode())
    except ValueError:  # binascii.Error, UnicodeDecodeError and JSONDecodeError included
        return TrafficSource()
    return make_source(payload) if isinstance(payload, dict) else TrafficSource()


def source_cookie(value: str) -> str:
    """The ``Set-Cookie`` value of ``src``: host-only, secure, ``HttpOnly``, 30 days."""
    cookie: SimpleCookie = SimpleCookie()
    cookie[SOURCE_COOKIE] = value
    morsel = cookie[SOURCE_COOKIE]
    morsel["max-age"] = MAX_AGE_SECONDS
    morsel["path"] = "/"
    morsel["secure"] = True
    morsel["httponly"] = True
    morsel["samesite"] = "lax"
    return morsel.OutputString()


class SourceCookie:
    """ASGI middleware: the first HTML page of a browser gets the ``src`` cookie."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "GET" or carries_token(scope["path"]):
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        if SOURCE_COOKIE in request.cookies:
            await self.app(scope, receive, send)
            return

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] == 200:
                headers = MutableHeaders(scope=message)
                if headers.get("content-type", "").startswith("text/html"):
                    headers.append(
                        "set-cookie", source_cookie(encode_source(capture_source(request)))
                    )
            await send(message)

        await self.app(scope, receive, send_with_cookie)
