"""Cloudflare Turnstile server-side check, against a mocked transport (no network in tests)."""

import contextlib
import json
import logging
from collections.abc import Callable
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from app.adapters.turnstile.cloudflare import (
    MAX_TOKEN_LENGTH,
    SITEVERIFY_URL,
    CloudflareTurnstile,
)
from app.core.entities import HumanCheckResult
from app.core.ports import HumanCheckUnavailable

SECRET = "sentinel-turnstile-secret-value"
TOKEN = "sentinel-token-0123456789"

type Handler = Callable[[httpx.Request], httpx.Response]


def turnstile(handler: Handler) -> tuple[CloudflareTurnstile, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(record))
    return CloudflareTurnstile(SecretStr(SECRET), client), seen


def answer(body: object, status: int = 200) -> Handler:
    return lambda _: httpx.Response(status, content=json.dumps(body).encode())


def test_posts_secret_and_token_to_siteverify() -> None:
    check, seen = turnstile(answer({"success": True, "hostname": "site.example.com"}))

    result = check.verify(TOKEN)

    assert result == HumanCheckResult(success=True, hostname="site.example.com")
    [request] = seen
    assert request.method == "POST"
    assert str(request.url) == SITEVERIFY_URL
    assert parse_qs(request.content.decode()) == {"secret": [SECRET], "response": [TOKEN]}


@pytest.mark.parametrize(
    "codes", [["invalid-input-response"], ["timeout-or-duplicate"], ["bad-request"], []]
)
def test_rejected_token(codes: list[str]) -> None:
    check, _ = turnstile(answer({"success": False, "error-codes": codes}))

    assert check.verify(TOKEN) == HumanCheckResult(success=False, hostname=None)


@pytest.mark.parametrize("token", ["", "x" * (MAX_TOKEN_LENGTH + 1)])
def test_empty_or_oversized_token_is_rejected_without_a_request(token: str) -> None:
    check, seen = turnstile(answer({"success": True}))

    assert check.verify(token).success is False
    assert seen == []


@pytest.mark.parametrize(
    "handler",
    [
        answer({"success": False, "error-codes": ["internal-error"]}),
        answer({"success": False, "error-codes": ["invalid-input-secret"]}),
        answer({"success": False, "error-codes": ["missing-input-secret"]}),
        answer({"success": True}, status=500),
        lambda _: httpx.Response(200, content=b"<html>not json</html>"),
        answer(["not", "an", "object"]),
    ],
    ids=["internal", "bad-secret", "no-secret", "http-500", "not-json", "not-object"],
)
def test_unusable_answers_mean_unavailable(handler: Handler) -> None:
    check, _ = turnstile(handler)

    with pytest.raises(HumanCheckUnavailable):
        check.verify(TOKEN)


@pytest.mark.parametrize("error", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError])
def test_network_failure_means_unavailable(error: type[httpx.TransportError]) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise error("boom", request=request)

    check, _ = turnstile(fail)

    with pytest.raises(HumanCheckUnavailable):
        check.verify(TOKEN)


def test_success_must_be_exactly_true() -> None:
    check, _ = turnstile(answer({"success": "true", "hostname": "site.example.com"}))

    assert check.verify(TOKEN).success is False


def test_logs_carry_neither_token_nor_secret(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    for handler in (
        answer({"success": False, "error-codes": ["timeout-or-duplicate"]}),
        answer({"success": False, "error-codes": ["invalid-input-secret"]}),
        answer({}, status=503),
    ):
        check, _ = turnstile(handler)
        with contextlib.suppress(HumanCheckUnavailable):
            check.verify(TOKEN)

    assert caplog.records
    assert TOKEN not in caplog.text
    assert SECRET not in caplog.text
    assert "timeout-or-duplicate" in caplog.text


def test_secret_is_not_in_the_repr() -> None:
    check, _ = turnstile(answer({"success": True}))

    assert SECRET not in repr(check)
