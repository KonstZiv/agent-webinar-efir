"""Per-application dependency container, injected into routes via ``Depends``.

Routes of the slices get their services by key: ``Annotated[Clock, Depends(service(CLOCK))]``
(``app.services``); this module never names a slice.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates

from app.adapters.content.copy import PageTexts
from app.adapters.content.legal import LegalTexts
from app.adapters.web.page_meta import PageMeta
from app.adapters.web.token_paths import carries_token
from app.core.ports import DatabaseProbe
from app.core.timezone import KYIV
from app.services import CLOCK, Key, Services
from app.settings import Settings

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
BASE_STYLESHEET = "site.css"


@dataclass(frozen=True, slots=True)
class Container:
    """Everything routes need; built by ``create_app`` and stored in ``app.state``."""

    settings: Settings
    db_probe: DatabaseProbe
    legal: LegalTexts = field(repr=False)
    templates: Jinja2Templates = field(repr=False)
    page_texts: PageTexts = field(repr=False)
    page_meta: PageMeta | None = field(default=None, repr=False)  # none in the redirect stub
    services: Services = field(default_factory=Services, repr=False)


def _site_context(request: Request) -> dict[str, object]:
    """Values every page template needs: footer, cookie banner, analytics id, asset version.

    Pages whose address carries a token get no analytics id: Google would receive the token.
    """
    container: Container = request.app.state.container
    analytics = not carries_token(request.url.path)
    return {
        "legal": container.legal,
        "ga4_id": container.settings.ga4_measurement_id if analytics else "",
        "asset_version": container.settings.commit_short,
        "indexing_enabled": container.settings.indexing_enabled,
    }


def _landing_context(request: Request) -> dict[str, object]:
    """``blocks`` — blocks 1.2–1.7 of ``/`` for the mode and today's date in Kyiv (CLAUDE.md).

    Every render gets them, so the page of ``/`` has them whoever renders it: the route or a
    slice's answer without htmx. All of them come under one name, so the keys of a route's own
    context stay as they are.
    """
    container: Container = request.app.state.container
    today = container.services.get(CLOCK).now().astimezone(KYIV).date()
    return {"blocks": container.page_texts.landing[container.settings.site_mode].for_day(today)}


def stylesheets(css_dir: Path) -> tuple[str, ...]:
    """Files ``base.html`` links: ``site.css`` first, then every other ``.css`` by name.

    Each slice and the layout add their own file (requirements, section 12) instead of editing
    a shared one.
    """
    names = sorted(path.name for path in css_dir.glob("*.css"))
    if BASE_STYLESHEET not in names:
        raise FileNotFoundError(f"{BASE_STYLESHEET} is missing in {css_dir}")
    return (BASE_STYLESHEET, *(name for name in names if name != BASE_STYLESHEET))


def make_templates() -> Jinja2Templates:
    templates = Jinja2Templates(
        directory=TEMPLATES_DIR, context_processors=[_site_context, _landing_context]
    )
    templates.env.globals["stylesheets"] = stylesheets(STATIC_DIR / "css")
    return templates


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def service[T](key: Key[T]) -> Callable[[Request], T]:
    """A route dependency that gets the service ``key`` of the application."""

    def dependency(request: Request) -> T:
        return get_container(request).services.get(key)

    return dependency
