"""``/unsubscribe/{token}`` (docs/contract.md, sections 3 and 4; texts: docs/copy.md, 7.1–7.3).

GET only shows a page: mail scanners follow links on their own, and deleting is final. POST from
the page's form deletes and shows 7.2; the one-click POST of a mail client
(``List-Unsubscribe=One-Click``, RFC 8058) gets an empty 200. Any storage failure is 503, as
in v1: the page of 7.3 names the address for a manual request. The token never leaves the site:
the path lies under a token prefix (no analytics, no ``Referer``, masked in the access log).
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response

from app.adapters.registration.keys import UNSUBSCRIPTION
from app.adapters.web.dependencies import Container, ContainerDep, service
from app.adapters.web.headers import SERVICE
from app.core.ports import StorageError, StorageUnavailable
from app.core.registration.unsubscription import InvalidToken, Subscribed, Unsubscription

logger = logging.getLogger(__name__)

router = APIRouter()

PREFIX = "/unsubscribe/"
ONE_CLICK = "One-Click"
PAGE = "registration/unsubscribe.html"

UnsubscriptionDep = Annotated[Unsubscription, Depends(service(UNSUBSCRIPTION))]


def _log_failure(error: StorageError) -> None:
    """Log the class of ``error`` only: no token, no address.

    An outage is a warning; any other storage failure is a bug here (nothing to conflict with on
    a delete), so an error.
    """
    level = logging.WARNING if isinstance(error, StorageUnavailable) else logging.ERROR
    logger.log(level, "Unsubscribe failed: %s", type(error).__name__)


def _page(
    request: Request, container: Container, state: str, status_code: int = 200, **context: object
) -> HTMLResponse:
    return container.templates.TemplateResponse(
        request,
        PAGE,
        {"state": state, "noindex": True, **context},
        status_code=status_code,
        headers=SERVICE,
    )


@router.get(PREFIX + "{token}", response_class=HTMLResponse)
def unsubscribe_page(
    request: Request, token: str, container: ContainerDep, unsubscription: UnsubscriptionDep
) -> HTMLResponse:
    try:
        found = unsubscription.preview(token)
    except StorageError as error:
        _log_failure(error)
        return _page(request, container, "failed", 503)
    if isinstance(found, InvalidToken):
        return _page(request, container, "failed", 400)
    if isinstance(found, Subscribed):
        return _page(request, container, "confirm", email=found.email, action=PREFIX + token)
    return _page(request, container, "done")


@router.post(PREFIX + "{token}", response_class=HTMLResponse, response_model=None)
def unsubscribe(
    request: Request,
    token: str,
    container: ContainerDep,
    unsubscription: UnsubscriptionDep,
    one_click: Annotated[str, Form(alias="List-Unsubscribe")] = "",
) -> Response:
    try:
        outcome = unsubscription.confirm(token)
    except StorageError as error:
        _log_failure(error)
        status = 503
    else:
        status = 400 if isinstance(outcome, InvalidToken) else 200
    if one_click == ONE_CLICK:
        return Response(status_code=status, headers=SERVICE)
    return _page(request, container, "done" if status == 200 else "failed", status)
