"""The network guard of tests/conftest.py: no test reaches a host outside this machine.

Requirement 16: tests run without external services. A slice may talk to Telegram, Resend or
Claude with a sync or an async client, or open a socket some other way; a forgotten override
must fail the test instead of reaching the service. Local sockets stay open (in-process
servers); the test database is reached through libpq, outside Python's sockets.
"""

import asyncio
import doctest
import socket

import httpx
import pytest

from tests import conftest

STOPPED = "must not reach the network"
# Documentation addresses (RFC 5737, RFC 3849): never a real host.
REMOTE = [("192.0.2.1", 443), ("2001:db8::1", 443)]


def test_the_sync_http_client_is_stopped() -> None:
    with httpx.Client() as client, pytest.raises(RuntimeError, match=STOPPED):
        client.get("https://api.telegram.org/")


def test_the_async_http_client_is_stopped() -> None:
    async def fetch() -> None:
        async with httpx.AsyncClient() as client:
            await client.get("https://api.telegram.org/")

    with pytest.raises(RuntimeError, match=STOPPED):
        asyncio.run(fetch())


@pytest.mark.parametrize("address", REMOTE, ids=["ipv4", "ipv6"])
def test_a_socket_to_another_host_is_stopped(address: tuple[str, int]) -> None:
    with pytest.raises(RuntimeError, match=STOPPED):
        socket.create_connection(address, timeout=0.5)


def test_an_asyncio_connection_to_another_host_is_stopped() -> None:
    async def connect() -> None:
        await asyncio.wait_for(asyncio.open_connection(*REMOTE[0]), timeout=0.5)

    with pytest.raises(RuntimeError, match=STOPPED):
        asyncio.run(connect())


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_a_local_socket_still_connects(host: str) -> None:
    with socket.create_server(("127.0.0.1", 0)) as server:
        port = server.getsockname()[1]
        with socket.create_connection((host, port), timeout=1) as connection:
            assert connection.getpeername()[1] == port


def test_the_examples_of_the_guard() -> None:
    result = doctest.testmod(conftest)

    assert (result.failed, result.attempted > 0) == (0, True)
