"""The consent under the form is v1's text: the version ``consent-v1`` is bound to it.

v1 and v2 store ``consent-v1`` with every registration (docs/legacy-schema.md, «Згода
``consent-v1``»), so the text behind that name never changes; a new text gets a new version.
"""

import re

from tests.markdown_text import LEGAL_DIR

CONSENT = LEGAL_DIR / "consent.md"
# docs/legal/consent.md of v1 (agent-webinar-v1, commit fee3439), section «Текст позначки».
V1_CONSENT_TEXT = (
    "Я погоджуюся, що організатор вебінару Костянтин Зівенко обробляє мої дані, щоб надсилати "
    "мені листи й повідомлення про вебінар, перше заняття, матеріали і курс «Агентна розробка "
    "на Python», а також про наступні вебінари й курси ведучого, і передає мою адресу "
    "електронної пошти навчальному центру CyberBionic Systematics (CBS), який проводить курс, "
    "для зв'язку зі мною щодо навчання. Відкликати згоду можна будь-коли; докладніше — в "
    "[політиці приватності](/privacy)."
)


def consent_section(markdown: str) -> str:
    match = re.search(r"^## Текст позначки\n(.*?)(?=^## |\Z)", markdown, re.MULTILINE | re.DOTALL)
    assert match is not None, "docs/legal/consent.md has no section «Текст позначки»"
    return match.group(1).strip()


def test_consent_text_is_v1_text() -> None:
    assert consent_section(CONSENT.read_text(encoding="utf-8")) == V1_CONSENT_TEXT


def test_consent_version_is_consent_v1() -> None:
    assert "**Версія тексту: `consent-v1`" in CONSENT.read_text(encoding="utf-8")
