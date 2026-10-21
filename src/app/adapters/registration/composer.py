"""The invitation to the first lesson (``InvitationComposer`` port): docs/copy.md, section 3.

The texts are verbatim in ``templates/lesson_invitation.html`` and ``.txt``;
tests/registration/test_letter.py compares them with copy.md. Every address in the letter and
the one-click unsubscribe headers are built from ``PUBLIC_BASE_URL``: v2 serves its own address,
so there is no separate service address as in v1 (docs/contract.md, «Адреси»). The sender's name
comes from copy.md, not from a setting.
"""

from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.entities import OutgoingEmail

TEMPLATES_DIR = Path(__file__).parent / "templates"
SENDER_NAME = "Костянтин Зівенко"
SUBJECT = "Запрошення на перше заняття курсу — 26 жовтня, 19:00 за Києвом"
PREHEADER = "Перехід на заняття, подія для календаря та інструкція «Зроби сам»."


class JinjaInvitationComposer:
    """Renders the HTML and text versions of the invitation."""

    def __init__(self, *, public_base_url: str, sender_email: str) -> None:
        self._public = public_base_url
        self._sender = f"{SENDER_NAME} <{sender_email}>"
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
            "subject": SUBJECT,
            "preheader": PREHEADER,
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
            subject=SUBJECT,
            html=self._env.get_template("lesson_invitation.html").render(context),
            text=self._env.get_template("lesson_invitation.txt").render(context),
            headers={
                "List-Unsubscribe": f"<{unsubscribe_url}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
        )
