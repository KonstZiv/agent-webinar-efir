"""``GET /``: service page of the template: the application runs, and which commit it runs."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.adapters.web.dependencies import ContainerDep
from app.adapters.web.headers import SERVICE

router = APIRouter()

TITLE = "Застосунок працює"


@router.get("/", response_class=HTMLResponse)
def home(request: Request, container: ContainerDep) -> HTMLResponse:
    return container.templates.TemplateResponse(
        request,
        "home.html",
        {"title": TITLE, "commit_short": container.settings.commit_short, "noindex": True},
        headers=SERVICE,
    )
