"""A sample slice, for tests only: how a slice plugs in without changing shared files.

tests/test_slices.py loads it as ``app.slices.sample`` (its route as
``app.adapters.web.routers.sample``). It picks its adapter by a setting, adds a middleware,
start-up and shut-down actions, a closer and a template global. ``EVENTS`` records what
happened, in order.
"""

from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx
from fastapi import Request, Response

from app.services import Key
from app.slices import SliceSetup

EVENTS: list[str] = []


class Greeter(Protocol):
    def greet(self) -> str: ...


GREETER = Key[Greeter]("sample.greeter")


class HttpGreeter:
    """The «real» adapter: it holds a client and asks the network for every greeting."""

    def __init__(self) -> None:
        EVENTS.append("built http greeter")
        self._client = httpx.Client()

    def greet(self) -> str:
        return self._client.get("https://greeter.example.com").text


class ReplayGreeter:
    def greet(self) -> str:
        return "replay"


async def mark_response(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    response.headers["X-Sample-Slice"] = "1"
    return response


async def start_async() -> None:
    EVENTS.append("startup async")


def install(setup: SliceSetup) -> None:
    if setup.settings.site_mode == "replay":
        setup.provide(GREETER, ReplayGreeter)
    else:
        setup.provide(GREETER, HttpGreeter)
    setup.http_middleware(mark_response)
    setup.on_startup(lambda: EVENTS.append("startup sync"))
    setup.on_startup(start_async)
    setup.on_shutdown(lambda: EVENTS.append("shutdown first registered"))
    setup.on_shutdown(lambda: EVENTS.append("shutdown last registered"))
    setup.close_on_shutdown(lambda: EVENTS.append("closed"))
    setup.template_global("sample_motto", "slices only add files")
