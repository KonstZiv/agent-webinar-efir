"""``GET /course``: the page of the course for advertising traffic (docs/copy.md, section 13).

The registration, the invitation, the source (``utm``) and the analytics events are those of
``/``: the page includes the same form, which posts to ``/register``. The context:

- ``page`` — the texts of section 13, ready (``CourseTexts``);
- ``form_texts`` — the title and the intro of the form, 13.2;
- ``page_meta`` — the service tags of 13.7: no event markup, the canonical address is ``/course``;
- ``site_mode`` — the current mode, for the form and the success screen.

``blocks`` (1.6, 1.7) are added by the foundation. The texts are read by the slice ``course``
and given by the key ``COURSE_TEXTS``.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.adapters.content.copy import CourseTexts
from app.adapters.web.dependencies import ContainerDep, service
from app.adapters.web.page_meta import CANONICAL_URL, OG_IMAGE_PATH, PageMeta, script_json
from app.services import Key

router = APIRouter()

COURSE_TEXTS = Key[CourseTexts]("course.texts")
PATH = "/course"
TEMPLATE = "course.html"


@router.get(PATH, response_class=HTMLResponse)
def course(
    request: Request,
    container: ContainerDep,
    texts: CourseTexts = Depends(service(COURSE_TEXTS)),  # noqa: B008
) -> HTMLResponse:
    page_texts = container.page_texts
    url = f"{CANONICAL_URL.rstrip('/')}{PATH}"
    page_meta = PageMeta(
        title=texts.service.title,
        description=texts.service.description,
        og_title=texts.service.og_title,
        og_description=texts.service.og_description,
        og_site_name=page_texts.site_name,
        og_image=f"{container.settings.public_base_url}{OG_IMAGE_PATH}",
        og_image_alt=page_texts.image_alt,
        json_ld=script_json(
            {
                "@context": "https://schema.org",
                "@type": "WebPage",
                "name": texts.service.title,
                "description": texts.service.description,
                "url": url,
            }
        ),
        canonical=url,
        og_url=url,
    )
    return container.templates.TemplateResponse(
        request,
        TEMPLATE,
        {
            "page": texts,
            "form_texts": {"title": texts.form_title, "intro": texts.form_intro},
            "page_meta": page_meta,
            "site_mode": container.settings.site_mode,
        },
    )
