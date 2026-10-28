"""``GET /admin/checkin``: the teacher's page of the attendance (docs/requirements.md, 9а).

The page is a shell: no data and no authorization. The teacher pastes the admin token in the
page, and the script (``static/js/checkin-admin.js``) fetches everything from the admin API with
it. So the HTML holds no code, address or check-in, and is never cached or indexed. The texts
(docs/copy.md, 14.4) come with the page; the host of the site and the channel come from the
settings.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.adapters.checkin.keys import ADMIN_TEXTS
from app.adapters.checkin.texts import AdminTexts
from app.adapters.web.dependencies import ContainerDep, service
from app.adapters.web.headers import SERVICE
from app.core.checkin.model import (
    DEFAULT_WINDOW_MINUTES,
    GROUP_CODE_PATTERN,
    MAX_WINDOW_MINUTES,
    MIN_WINDOW_MINUTES,
)

router = APIRouter()

PAGE = "checkin_admin.html"

AdminTextsDep = Annotated[AdminTexts, Depends(service(ADMIN_TEXTS))]


@router.get("/admin/checkin", response_class=HTMLResponse)
def checkin_admin_page(
    request: Request, container: ContainerDep, texts: AdminTextsDep
) -> HTMLResponse:
    settings = container.settings
    site_host = settings.public_base_url.partition("://")[2] or settings.public_base_url
    channel = settings.telegram_channel
    shown = texts.for_site(site_host, channel)
    context: dict[str, object] = {
        "admin": shown,
        "channel": channel,
        "script_config": {
            "texts": shown.script_texts(),
            "group_pattern": GROUP_CODE_PATTERN,
            "default_minutes": DEFAULT_WINDOW_MINUTES,
            "min_minutes": MIN_WINDOW_MINUTES,
            "max_minutes": MAX_WINDOW_MINUTES,
        },
        "noindex": True,
    }
    return container.templates.TemplateResponse(request, PAGE, context, headers=SERVICE)
