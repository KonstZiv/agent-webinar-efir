"""Links from emails: ``/go/*`` and the calendar files (docs/requirements.md, section 6).

``/go/stream``, ``/go/lesson`` and ``/go/course`` redirect with 302: the target is a setting and
may change, so no browser keeps it. Until ``STREAM_URL`` or ``LESSON_URL`` is set, the page
«the link will appear» answers instead (docs/copy.md, 6.1 and 6.2), never indexed; the date of
the webinar on it comes from ``EVENT_START`` and ``EVENT_END`` (``event``). Old emails of v1 link
to ``/go/stream`` and ``/calendar.ics`` (docs/contract.md, section 3).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.adapters.registration.ics import CalendarEvent, build_calendar, lesson_event, webinar_event
from app.adapters.registration.settings import required
from app.adapters.web.dependencies import Container, ContainerDep, service
from app.adapters.web.headers import SERVICE
from app.core.event_values import event_values
from app.core.ports import Clock
from app.services import CLOCK

router = APIRouter()

PENDING_PAGE = "registration/link_pending.html"
CALENDAR_TYPE = "text/calendar; charset=utf-8"

ClockDep = Annotated[Clock, Depends(service(CLOCK))]


def _go(
    request: Request, container: Container, target: str, kind: Literal["stream", "lesson"]
) -> Response:
    if target:
        return RedirectResponse(target, status_code=302, headers=SERVICE)
    settings = container.settings
    event = event_values(
        required(settings.event_start, "EVENT_START"), required(settings.event_end, "EVENT_END")
    )
    return container.templates.TemplateResponse(
        request, PENDING_PAGE, {"kind": kind, "noindex": True, "event": event}, headers=SERVICE
    )


@router.get("/go/stream", response_class=HTMLResponse, response_model=None)
def go_stream(request: Request, container: ContainerDep) -> Response:
    return _go(request, container, container.settings.stream_url, "stream")


@router.get("/go/lesson", response_class=HTMLResponse, response_model=None)
def go_lesson(request: Request, container: ContainerDep) -> Response:
    return _go(request, container, container.settings.lesson_url, "lesson")


@router.get("/go/course")
def go_course(container: ContainerDep) -> RedirectResponse:
    return RedirectResponse(container.settings.course_url, status_code=302, headers=SERVICE)


def _calendar(event: CalendarEvent, clock: Clock) -> Response:
    return Response(build_calendar(event, now=clock.now()), media_type=CALENDAR_TYPE)


@router.get("/calendar.ics")
def webinar_calendar(container: ContainerDep, clock: ClockDep) -> Response:
    settings = container.settings
    event = webinar_event(
        start=required(settings.event_start, "EVENT_START"),
        end=required(settings.event_end, "EVENT_END"),
        public_base_url=settings.public_base_url,
    )
    return _calendar(event, clock)


@router.get("/calendar/lesson.ics")
def lesson_calendar(container: ContainerDep, clock: ClockDep) -> Response:
    settings = container.settings
    event = lesson_event(
        start=required(settings.lesson_start, "LESSON_START"),
        end=required(settings.lesson_end, "LESSON_END"),
        public_base_url=settings.public_base_url,
    )
    return _calendar(event, clock)
