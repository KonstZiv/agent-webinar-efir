"""``GET /privacy``: docs/legal/privacy.md as is."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.adapters.web.dependencies import ContainerDep

router = APIRouter()


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request, container: ContainerDep) -> HTMLResponse:
    return container.templates.TemplateResponse(request, "privacy.html", {})
