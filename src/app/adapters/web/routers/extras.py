"""``GET /counters``: the fragment with the two numbers (docs/requirements.md, sections 8 and 12).

The answer is ``_counters.html`` with the numbers; htmx swaps it for the partial on the page and
keeps polling. A database failure is 204: the htmx config of ``base.html`` swaps nothing on 204,
so the page keeps what it shows and polls on (a 503 would be swapped in and end the polling;
the partial itself swaps in a 200 only, against a 503 or 429 of a proxy). The numbers come from
memory, read at most once per 15 seconds, and no poll waits for another's read
(``CachedCounters``). Never cached or indexed: a fragment, not a page; no access log line.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.adapters.extras.keys import COUNTERS
from app.adapters.extras.view import COUNTERS_PATH
from app.adapters.web.dependencies import ContainerDep, service
from app.adapters.web.headers import SERVICE
from app.core.extras.counters import CachedCounters

router = APIRouter()

CountersDep = Annotated[CachedCounters, Depends(service(COUNTERS))]


@router.get(COUNTERS_PATH)
def counters(request: Request, container: ContainerDep, cached: CountersDep) -> Response:
    numbers = cached.current()
    if numbers is None:
        return Response(status_code=204, headers=SERVICE)
    return container.templates.TemplateResponse(
        request, "_counters.html", {"counters_state": numbers}, headers=SERVICE
    )
