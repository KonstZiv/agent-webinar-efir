"""``GET /stats``: the live statistics, aggregates only (docs/requirements.md, section 4).

Total registrations, the last 48 hours by hour in Kyiv time as an inline SVG, the share of
participants with Telegram, and the levels by name. The numbers come from memory, read at most
once per 30 seconds (``CachedStats``). While the database fails the page keeps the last known
numbers, or says the statistics are unavailable; it never answers with an error. Never cached by
proxies or indexed: the numbers change every minute.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.adapters.stats.chart import build_chart
from app.adapters.stats.keys import STATS, TEXTS
from app.adapters.stats.texts import StatsTexts
from app.adapters.web.dependencies import ContainerDep, service
from app.adapters.web.headers import SERVICE
from app.core.stats.cache import CachedStats

router = APIRouter()

StatsDep = Annotated[CachedStats, Depends(service(STATS))]
TextsDep = Annotated[StatsTexts, Depends(service(TEXTS))]


@router.get("/stats", response_class=HTMLResponse)
def stats(
    request: Request, container: ContainerDep, cached: StatsDep, texts: TextsDep
) -> HTMLResponse:
    view = cached.current()
    context: dict[str, object] = {"texts": texts, "view": view, "noindex": True}
    if view is not None:
        context["chart"] = build_chart(view.hours)
        context["share_percent"] = round(100 * view.telegram / view.total) if view.total else 0
        context["share_caption"] = texts.caption_of_share(view.telegram, view.total)
    return container.templates.TemplateResponse(request, "stats.html", context, headers=SERVICE)
