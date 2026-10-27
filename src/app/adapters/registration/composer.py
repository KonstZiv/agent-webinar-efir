"""The invitation to the nearest lesson (``InvitationComposer`` port): docs/copy.md, section 3.

The texts are verbatim in ``templates/lesson_invitation.html`` and ``.txt``;
tests/registration/test_letter.py compares them with copy.md. Every address in the letter and
the one-click unsubscribe headers are built from ``PUBLIC_BASE_URL``: v2 serves its own address,
so there is no separate service address as in v1 (docs/contract.md, «Адреси»). The sender's name
comes from copy.md, not from a setting.
"""

from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.adapters.content.copy import lesson_values
from app.core.entities import OutgoingEmail

TEMPLATES_DIR = Path(__file__).parent / "templates"
SENDER_NAME = "Костянтин Зівенко"
SUBJECT = "Запрошення на заняття курсу — {lesson_day_month}, {lesson_start} за Києвом"
PREHEADER = "Перехід на заняття, подія для календаря та інструкція «Зроби сам»."
COURSE_PAGE_URL = "https://edu.cbsystematics.com/ua/courses/ai-agent"


class JinjaInvitationComposer:
    """Renders the HTML and text versions of the invitation to the nearest lesson.

    ``lesson_start`` and ``lesson_end`` are ``LESSON_START`` and ``LESSON_END``: the date and
    the times in the subject and the text come from them (docs/copy.md, section 11).
    """

    def __init__(
        self,
        *,
        public_base_url: str,
        sender_email: str,
        lesson_start: datetime,
        lesson_end: datetime,
    ) -> None:
        self._public = public_base_url
        self._sender = f"{SENDER_NAME} <{sender_email}>"
        self._lesson = lesson_values(lesson_start, lesson_end)
        self._subject = SUBJECT.format(**self._lesson)
        self._env = Environment(
            loader=FileSystemLoader(TEMPLATES_DIR),
            autoescape=select_autoescape(["html"]),
            undefined=StrictUndefined,
        )

    def invitation(
        self, recipient: str, unsubscribe_token: str, bot_url: str | None
    ) -> OutgoingEmail:
        unsubscribe_url = f"{self._public}/unsubscribe/{unsubscribe_token}"
        context = {
            **self._lesson,
            "subject": self._subject,
            "preheader": PREHEADER,
            "course_page_url": COURSE_PAGE_URL,
            "lesson_url": f"{self._public}/go/lesson",
            "lesson_calendar_url": f"{self._public}/calendar/lesson.ics",
            "bot_url": bot_url,
            "site_url": self._public,
            "site_host": urlsplit(self._public).hostname,
            "unsubscribe_url": unsubscribe_url,
            "privacy_url": f"{self._public}/privacy",
        }
        return OutgoingEmail(
            sender=self._sender,
            to=recipient,
            subject=self._subject,
            html=self._env.get_template("lesson_invitation.html").render(context),
            text=self._env.get_template("lesson_invitation.txt").render(context),
            headers={
                "List-Unsubscribe": f"<{unsubscribe_url}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
        )
