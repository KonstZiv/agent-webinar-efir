"""Per-application dependency container, injected into routes via ``Depends``."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates

from app.adapters.content.legal import LegalTexts
from app.adapters.web.token_paths import carries_token
from app.core.ports import DatabaseProbe
from app.settings import Settings

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


@dataclass(frozen=True, slots=True)
class Container:
    """Everything routes need; built by ``create_app`` and stored in ``app.state``."""

    settings: Settings
    db_probe: DatabaseProbe
    legal: LegalTexts = field(repr=False)
    templates: Jinja2Templates = field(repr=False)


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


def make_templates() -> Jinja2Templates:
    return Jinja2Templates(directory=TEMPLATES_DIR, context_processors=[_site_context])


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]
