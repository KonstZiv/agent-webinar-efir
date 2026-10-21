"""``GET /m/{slug}``: the materials page from docs/materials.md (docs/contract.md, section 13).

The address is set by ``MATERIALS_SLUG`` and given only by the bot: without the setting or with
another slug the answer is the same 404 as for any unknown path; the slug is compared in
constant time. The page is not indexed or cached and, under the token prefix ``/m/``, loads no
analytics and is masked in the access log.
"""

import hmac

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.adapters.web.dependencies import ContainerDep
from app.adapters.web.headers import SERVICE

router = APIRouter()


@router.get("/m/{slug}", response_class=HTMLResponse)
def materials(request: Request, slug: str, container: ContainerDep) -> HTMLResponse:
    expected = container.settings.materials_slug
    if not expected or not hmac.compare_digest(slug.encode(), expected.encode()):
        raise HTTPException(status_code=404)
    texts = container.page_texts
    return container.templates.TemplateResponse(
        request,
        "materials.html",
        {"title": texts.materials_title, "html": texts.materials_html, "noindex": True},
        headers=SERVICE,
    )
