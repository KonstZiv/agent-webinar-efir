"""``GET /``: the landing page once the live slice adds ``landing.html``; the fallback until then.

Both get the same context (CLAUDE.md, «Маршрут /»):

- ``hero`` — the first screen of the current mode, ready (docs/copy.md, 1.1): the page has no
  mode logic (docs/requirements.md, section 3);
- ``page_meta`` — the service tags, rendered by ``base.html`` (requirements, section 13);
- ``site_mode`` — for the partials of slices (``_form.html``, ``_counters.html``), whose texts
  differ by mode.

``blocks`` — blocks 1.2–1.7 of the mode and the day — the foundation adds to every render
(``dependencies.py``), so a slice's answer that renders this page has them too.

The fallback page (``home.html``) shows every block and includes the partials by name,
skipping the missing ones, so ``/`` works at every stage of the slices' transfer.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from jinja2 import TemplateNotFound

from app.adapters.web.dependencies import ContainerDep

router = APIRouter()

LANDING = "landing.html"
FALLBACK = "home.html"


def has_template(templates: Jinja2Templates, name: str) -> bool:
    try:
        templates.env.get_template(name)
    except TemplateNotFound:
        return False
    return True


@router.get("/", response_class=HTMLResponse)
def home(request: Request, container: ContainerDep) -> HTMLResponse:
    mode = container.settings.site_mode
    template = LANDING if has_template(container.templates, LANDING) else FALLBACK
    return container.templates.TemplateResponse(
        request,
        template,
        {
            "hero": container.page_texts.first_screen[mode],
            "page_meta": container.page_meta,
            "site_mode": mode,
        },
    )
