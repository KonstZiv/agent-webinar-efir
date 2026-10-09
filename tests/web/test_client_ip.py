"""Client address for rate limiting: ``X-Real-IP`` from Railway's proxy, else the connection."""

import pytest
from starlette.requests import Request

from app.adapters.web.client_ip import client_ip


def request(headers: list[tuple[str, str]], client: tuple[str, int] | None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(name.lower().encode(), value.encode()) for name, value in headers],
            "client": client,
        }
    )


CONNECTION = ("203.0.113.7", 5000)


def test_real_ip_header_wins_over_the_connection() -> None:
    assert client_ip(request([("X-Real-IP", "192.0.2.10")], CONNECTION)) == "192.0.2.10"


def test_last_real_ip_value_is_the_proxys_own() -> None:
    headers = [("X-Real-IP", "198.51.100.1"), ("X-Real-IP", " 192.0.2.10 ")]

    assert client_ip(request(headers, CONNECTION)) == "192.0.2.10"


def test_ipv6_is_normalised() -> None:
    assert client_ip(request([("X-Real-IP", "2001:DB8::0001")], CONNECTION)) == "2001:db8::1"


@pytest.mark.parametrize("value", ["not-an-ip", "", "192.0.2.10, 198.51.100.1"])
def test_invalid_real_ip_falls_back_to_the_connection(value: str) -> None:
    assert client_ip(request([("X-Real-IP", value)], CONNECTION)) == "203.0.113.7"


def test_forwarded_for_is_ignored() -> None:
    headers = [("X-Forwarded-For", "198.51.100.1")]

    assert client_ip(request(headers, CONNECTION)) == "203.0.113.7"


def test_no_header_and_no_connection() -> None:
    assert client_ip(request([], None)) == "unknown"
