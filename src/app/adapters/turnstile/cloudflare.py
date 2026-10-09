"""Cloudflare Turnstile server-side validation (``HumanCheck`` port).

https://developers.cloudflare.com/turnstile/get-started/server-side-validation/
"""

import logging
import re

import httpx
from pydantic import SecretStr

from app.core.entities import HumanCheckResult
from app.core.ports import HumanCheckUnavailable

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
MAX_TOKEN_LENGTH = 2048  # longer tokens are invalid by Cloudflare's documentation
TIMEOUT = httpx.Timeout(5.0, connect=3.0)
# No verdict about the visitor: Cloudflare failed, or our secret is wrong.
_UNAVAILABLE_CODES = frozenset({"internal-error", "missing-input-secret", "invalid-input-secret"})
_ERROR_CODE = re.compile(r"[a-z0-9-]{1,64}")


def make_http_client() -> httpx.Client:
    """HTTP client for siteverify.

    The caller closes it (register ``client.close`` in ``create_app``'s closers).
    """
    return httpx.Client(timeout=TIMEOUT)


def _error_codes(body: dict[str, object]) -> list[str]:
    """Error codes safe to log: known shape only, nothing that could forge a log line."""
    codes = body.get("error-codes")
    if not isinstance(codes, list):
        return []
    return [code for code in codes if isinstance(code, str) and _ERROR_CODE.fullmatch(code)]


class CloudflareTurnstile:
    """Validates widget tokens with Cloudflare. The visitor's IP address is not sent."""

    def __init__(self, secret: SecretStr, client: httpx.Client) -> None:
        self._secret = secret
        self._client = client

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def verify(self, token: str) -> HumanCheckResult:
        if not token or len(token) > MAX_TOKEN_LENGTH:
            return HumanCheckResult(success=False)
        try:
            response = self._client.post(
                SITEVERIFY_URL,
                data={"secret": self._secret.get_secret_value(), "response": token},
            )
        except httpx.HTTPError as error:
            logger.warning("Turnstile siteverify failed: %s", type(error).__name__)
            raise HumanCheckUnavailable from None
        if response.status_code != httpx.codes.OK:
            logger.warning("Turnstile siteverify answered HTTP %s", response.status_code)
            raise HumanCheckUnavailable
        try:
            body = response.json()
        except ValueError:
            logger.warning("Turnstile siteverify answered with something other than JSON")
            raise HumanCheckUnavailable from None
        if not isinstance(body, dict):
            logger.warning("Turnstile siteverify answered with unexpected JSON")
            raise HumanCheckUnavailable

        success = body.get("success") is True
        codes = _error_codes(body)
        if not success and _UNAVAILABLE_CODES.intersection(codes):
            logger.error("Turnstile siteverify cannot check tokens: %s", ", ".join(codes))
            raise HumanCheckUnavailable
        if not success:
            logger.info("Turnstile rejected the token: %s", ", ".join(codes) or "no error code")
        hostname = body.get("hostname")
        return HumanCheckResult(
            success=success, hostname=hostname if isinstance(hostname, str) else None
        )
