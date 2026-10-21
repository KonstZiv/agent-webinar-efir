"""Admin access: ``Authorization: Bearer <ADMIN_TOKEN>`` (docs/contract.md, section 8).

Admin routes of the slices take ``AdminDep``. Every refusal looks the same (401 without
details, not cached, not indexed), and neither the header nor the token is ever logged. The
logic is v1's (``webinar.adapters.web.admin_auth``); the token of v2 is its own.
"""

import hmac
import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.adapters.web.dependencies import get_container
from app.adapters.web.headers import SERVICE

logger = logging.getLogger(__name__)

SCHEME = "bearer"  # compared case-insensitively (RFC 9110)
UNAUTHORIZED_HEADERS = {**SERVICE, "WWW-Authenticate": "Bearer"}


def bearer_token(authorization: str | None) -> str | None:
    """The credentials of a ``Bearer`` header; ``None`` for anything else.

    >>> bearer_token("Bearer abc"), bearer_token("bearer abc")
    ('abc', 'abc')
    >>> bearer_token("Basic YWJj") is None, bearer_token("Bearer ") is None, bearer_token(None)
    (True, True, None)
    """
    if authorization is None:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != SCHEME or not token:
        return None
    return token


def is_admin_token(given: str, expected: str) -> bool:
    """Constant-time comparison of bytes: ``str`` would raise on non-ASCII input.

    Starlette decodes headers as latin-1, so encoding back gives the bytes that came in.

    >>> is_admin_token("secret", "secret"), is_admin_token("токен", "secret")
    (True, False)
    """
    return hmac.compare_digest(given.encode("latin-1", "replace"), expected.encode())


def require_admin(request: Request) -> None:
    """Dependency of every admin route: 401 unless the request carries the admin token."""
    secret = get_container(request).settings.admin_token
    token = bearer_token(request.headers.get("authorization"))
    if secret is None or token is None or not is_admin_token(token, secret.get_secret_value()):
        logger.warning("Admin request refused")
        raise HTTPException(status_code=401, detail="Unauthorized", headers=UNAUTHORIZED_HEADERS)


AdminDep = Annotated[None, Depends(require_admin)]
