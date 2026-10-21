"""Service tags of ``/`` (docs/requirements.md, section 13): the same for the fallback and landing.

``base.html`` renders them in its ``meta`` block when the route passes ``page_meta``; service
pages pass nothing and carry none. The canonical address is the main site in every
environment; the image is absolute from ``PUBLIC_BASE_URL``; event times carry the offset of
the ``Europe/Kyiv`` zone on their date, never a constant.
"""

import json
from dataclasses import dataclass

from markupsafe import Markup

from app.adapters.content.copy import PageTexts
from app.core.timezone import in_kyiv
from app.settings import Settings

CANONICAL_URL = "https://agent.pythoncourse.me/"
OG_IMAGE_PATH = "/static/og-image.png"
OG_TYPE = "website"
OG_LOCALE = "uk_UA"
TWITTER_CARD = "summary_large_image"


@dataclass(frozen=True, slots=True)
class PageMeta:
    title: str
    description: str
    og_title: str
    og_description: str
    og_site_name: str
    og_image: str
    og_image_alt: str
    json_ld: Markup
    canonical: str = CANONICAL_URL
    og_url: str = CANONICAL_URL
    og_type: str = OG_TYPE
    og_locale: str = OG_LOCALE
    twitter_card: str = TWITTER_CARD


def script_json(data: object) -> Markup:
    """JSON for a ``<script>`` element: ``<``, ``>`` and ``&`` escaped, so text cannot close it.

    >>> str(script_json({"name": "</script>"}))
    '{"name": "\\\\u003c/script\\\\u003e"}'
    """
    text = json.dumps(data, ensure_ascii=False)
    for char, escape in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026")):
        text = text.replace(char, escape)
    return Markup(text)


def build_page_meta(texts: PageTexts, settings: Settings) -> PageMeta:
    """Tags of ``/`` for the current mode; needs the settings of normal operation."""
    if settings.event_start is None or settings.event_end is None:
        raise ValueError("EVENT_START and EVENT_END are required for the event markup")
    service = texts.service[settings.site_mode]
    event = {
        "@context": "https://schema.org",
        "@type": "Event",
        "name": texts.event.name,
        "description": texts.event.description,
        "startDate": in_kyiv(settings.event_start).isoformat(timespec="minutes"),
        "endDate": in_kyiv(settings.event_end).isoformat(timespec="minutes"),
        "eventAttendanceMode": "https://schema.org/OnlineEventAttendanceMode",
        "eventStatus": "https://schema.org/EventScheduled",
        "location": {"@type": "VirtualLocation", "url": CANONICAL_URL},
        "organizer": {"@type": "Person", "name": texts.event.organizer},
        "isAccessibleForFree": True,
        "inLanguage": texts.event.in_language,
    }
    return PageMeta(
        title=service.title,
        description=service.description,
        og_title=service.og_title,
        og_description=service.og_description,
        og_site_name=texts.site_name,
        og_image=f"{settings.public_base_url}{OG_IMAGE_PATH}",
        og_image_alt=texts.image_alt,
        json_ld=script_json(event),
    )
