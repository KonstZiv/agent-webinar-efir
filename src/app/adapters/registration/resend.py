"""Resend HTTP API (``EmailSender`` port; docs/requirements.md, section 6).

https://resend.com/docs/api-reference/emails/send-email

Every attempt carries the same ``Idempotency-Key``, so a retry never sends a second email.
Only a 429 ``rate_limit_exceeded``, a 5xx answer or a network failure is retried; quota answers
and every other error fail at once. The logic is v1's (``webinar.adapters.mail.resend``).

One email, with its retries and pauses, takes at most ``SEND_BUDGET_SECONDS``, and one attempt
at most ``ATTEMPT_TIMEOUT_SECONDS``. httpx's timeouts bound each phase and each read, not a
request: an answer that drips in would outlast them. So an attempt runs in a short event loop of
its own (the mail thread has none) under ``asyncio.timeout``, which cancels it in any phase; its
fate is then unknown, as after a network failure. The client lives as long as the attempt.

The second barrier of the staging site: with a non-empty ``REGISTRATION_ALLOWLIST`` an address
off the list gets no request at all, whatever asked for the email.
"""

import asyncio
import logging
import math
import re
import time
import uuid
from collections.abc import Callable, Collection
from typing import Any

import httpx
from pydantic import SecretStr

from app.core.entities import Delivered, DeliveryResult, NotDelivered, OutgoingEmail
from app.core.masking import mask_email
from app.core.registration.addresses import is_allowed

logger = logging.getLogger(__name__)

API_URL = "https://api.resend.com/emails"
MAX_ATTEMPTS = 3
SEND_BUDGET_SECONDS = 15.0
ATTEMPT_TIMEOUT_SECONDS = 5.0
MAX_PAUSE_SECONDS = 5.0
MIN_ATTEMPT_SECONDS = 1.0  # a retry with less time left would only time out
RATE_LIMITED = "rate_limit_exceeded"
# Nothing goes out until the quota renews: the operator's retry stops on these.
QUOTAS = frozenset({"daily_quota_exceeded", "monthly_quota_exceeded"})
NOT_ALLOWED = "recipient not on the allowlist"
# Shapes safe to store and log: Resend's ``message`` is never kept, it may hold the address.
_ERROR_NAME = re.compile(r"[a-z_]{1,64}", re.ASCII)
_PROVIDER_ID = re.compile(r"[A-Za-z0-9-]{1,100}", re.ASCII)


type ClientFactory = Callable[[], httpx.AsyncClient]


def make_http_client() -> httpx.AsyncClient:
    """HTTP client for one attempt; the attempt closes it."""
    return httpx.AsyncClient(timeout=ATTEMPT_TIMEOUT_SECONDS)


def _json_field(response: httpx.Response, name: str, pattern: re.Pattern[str]) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    value = body.get(name) if isinstance(body, dict) else None
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def _pause(response: httpx.Response | None, attempt: int) -> float:
    """``Retry-After`` in seconds, capped; otherwise 1 s, then 2 s."""
    if response is not None:
        try:
            seconds = float(response.headers.get("retry-after", ""))
        except ValueError:
            seconds = math.nan
        if math.isfinite(seconds) and seconds >= 0:
            return min(seconds, MAX_PAUSE_SECONDS)
    return float(attempt)


def _is_refusal(status: int) -> bool:
    """A 4xx: Resend did not send the email. Not a 409: the key's earlier request may have."""
    return 400 <= status < 500 and status != 409


class ResendEmailSender:
    """Sends emails through Resend; transient failures are retried within the time budget."""

    def __init__(
        self,
        api_key: SecretStr,
        client: ClientFactory = make_http_client,
        *,
        allowlist: Collection[str] = (),
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._allowlist = frozenset(allowlist)
        self._sleep = sleep
        self._monotonic = monotonic

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def _post(
        self, payload: dict[str, Any], headers: dict[str, str], seconds: float
    ) -> httpx.Response:
        """One request, cancelled once ``seconds`` have passed, whatever phase it is in."""

        async def post() -> httpx.Response:
            async with asyncio.timeout(seconds), self._client() as client:
                return await client.post(API_URL, json=payload, headers=headers, timeout=seconds)

        return asyncio.run(post())

    def send(self, message: OutgoingEmail, idempotency_key: uuid.UUID) -> DeliveryResult:
        if not is_allowed(message.to, self._allowlist):
            logger.warning("Email to %s not sent: not on the allowlist", mask_email(message.to))
            return NotDelivered(error=NOT_ALLOWED, attempts=0, rejected=True)
        payload = {
            "from": message.sender,
            "to": [message.to],
            "subject": message.subject,
            "html": message.html,
            "text": message.text,
            "headers": dict(message.headers),
        }
        headers = {
            "Authorization": f"Bearer {self._api_key.get_secret_value()}",
            "Idempotency-Key": str(idempotency_key),
        }
        deadline = self._monotonic() + SEND_BUDGET_SECONDS
        error = ""
        refused_every_time = True  # no attempt so far may have sent the email
        out_of_quota = False
        attempt = 0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            timeout = min(ATTEMPT_TIMEOUT_SECONDS, deadline - self._monotonic())
            response: httpx.Response | None = None
            try:
                response = self._post(payload, headers, timeout)
            except (httpx.HTTPError, TimeoutError) as failure:
                error = f"network {type(failure).__name__}"
                refused_every_time = False
            else:
                if response.is_success:
                    provider_id = _json_field(response, "id", _PROVIDER_ID) or ""
                    return Delivered(provider_id=provider_id, attempts=attempt)
                name = _json_field(response, "name", _ERROR_NAME) or "unknown"
                error = f"HTTP {response.status_code} {name}"
                refused_every_time &= _is_refusal(response.status_code)
                out_of_quota = response.status_code == 429 and name in QUOTAS
                retryable = response.status_code >= 500 or (
                    response.status_code == 429 and name == RATE_LIMITED
                )
                if not retryable:
                    break
            if attempt == MAX_ATTEMPTS:
                break
            pause = _pause(response, attempt)
            if self._monotonic() + pause + MIN_ATTEMPT_SECONDS > deadline:
                logger.info("Resend attempt %d failed (%s); no time left to retry", attempt, error)
                break
            logger.info("Resend attempt %d failed (%s); retrying in %.1f s", attempt, error, pause)
            self._sleep(pause)
        return NotDelivered(
            error=error, attempts=attempt, rejected=refused_every_time, out_of_quota=out_of_quota
        )
