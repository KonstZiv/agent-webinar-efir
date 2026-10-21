"""The invitation to the first lesson (docs/copy.md, section 3; requirements, section 6).

The oracle reads the letter from copy.md itself: the HTML version shows exactly its text, the
text version shows its lines with links as «текст — адреса». Addresses in the letter and the
one-click unsubscribe headers are built from ``PUBLIC_BASE_URL`` (copy.md writes them for the
main address); without a bot the paragraph «Інструкція «Зроби сам»» has its own variant.
"""

import re

import pytest

from app.adapters.registration.composer import JinjaInvitationComposer
from app.core.entities import OutgoingEmail
from tests import copy_oracle as copy
from tests.html_tree import Node, parse
from tests.registration.helpers import quotes

PUBLIC = "https://public-sentinel.example.com"
SENDER = "sender-sentinel@example.com"
TOKEN = "0123456789abcdef0123456789abcdef.kX_fckLtX_yJu1UX9FsTzHwSZ_NflbFFdeL5yZnoC8g"
BOT_URL = "https://t.me/sentinel_webinar_bot?start=Bot_Token-0123456789abcdefghijklmnopqrstuv"
RECIPIENT = "visitor@example.com"

LETTER = copy.section("3")
BODY, NO_BOT, FOOTER = quotes(LETTER)
BOT_PARAGRAPH = "**Інструкція «Зроби сам»**"
MAIN_SITE = "https://agent.pythoncourse.me"
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def body(with_bot: bool) -> list[str]:
    """The letter's lines: without a bot its own paragraph replaces the bot's."""
    if with_bot:
        return BODY
    [replacement] = [line for line in NO_BOT if line.strip()]
    return [replacement if line.startswith(BOT_PARAGRAPH) else line for line in BODY]


def substitute(line: str, public: str = PUBLIC) -> str:
    """The values the site fills in (copy.md, section 11) and its own address."""
    host = public.split("://", 1)[1]
    return (
        line.replace("{lesson_url}", f"{public}/go/lesson")
        .replace("{lesson_calendar_url}", f"{public}/calendar/lesson.ics")
        .replace("{bot_url}", BOT_URL)
        .replace("{unsubscribe_url}", f"{public}/unsubscribe/{TOKEN}")
        .replace(MAIN_SITE, public)
        .replace("agent.pythoncourse.me", host)
    )


def compose(*, with_bot: bool = True, public: str = PUBLIC) -> OutgoingEmail:
    composer = JinjaInvitationComposer(public_base_url=public, sender_email=SENDER)
    return composer.invitation(RECIPIENT, TOKEN, BOT_URL if with_bot else None)


@pytest.fixture(scope="module", params=[True, False], ids=["bot", "no-bot"])
def with_bot(request: pytest.FixtureRequest) -> bool:
    value: bool = request.param
    return value


@pytest.fixture(scope="module")
def message(with_bot: bool) -> OutgoingEmail:
    return compose(with_bot=with_bot)


@pytest.fixture(scope="module")
def html(message: OutgoingEmail) -> Node:
    return parse(message.html)


def test_the_copy_has_the_three_quotes() -> None:
    assert [len(block) > 0 for block in (BODY, NO_BOT, FOOTER)] == [True, True, True]
    assert any(line.startswith(BOT_PARAGRAPH) for line in BODY)


def test_sender_subject_and_recipient(message: OutgoingEmail) -> None:
    assert message.sender == copy.one(LETTER, "Відправник").replace("{sender_email}", SENDER)
    assert message.sender == f"Костянтин Зівенко <{SENDER}>"
    assert message.subject == copy.one(LETTER, "Тема")
    assert message.to == RECIPIENT


def test_one_click_unsubscribe_headers_use_the_public_address(message: OutgoingEmail) -> None:
    assert dict(message.headers) == {
        "List-Unsubscribe": f"<{PUBLIC}/unsubscribe/{TOKEN}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def test_html_text_is_the_copy_and_nothing_else(html: Node, with_bot: bool) -> None:
    lines = [copy.one(LETTER, "Прехедер")]
    lines += [copy.plain(substitute(line)) for line in body(with_bot) + FOOTER if line.strip()]

    assert html.text() == " ".join(lines)


def test_preheader_is_hidden_and_comes_first(html: Node) -> None:
    content = html.find("body")
    first = next(node for node in content.children if not isinstance(node, str))
    style = (first.attrs.get("style") or "").replace(" ", "")

    assert first.text() == copy.one(LETTER, "Прехедер")
    assert "display:none" in style


def test_html_links(html: Node, with_bot: bool) -> None:
    found = {a.text(): a.attrs.get("href") for a in html.find_all("a")}
    bot = (
        {"Отримати в Telegram": BOT_URL}
        if with_bot
        else {"https://t.me/agentic_engineers": "https://t.me/agentic_engineers"}
    )

    assert found == {
        f"{PUBLIC}/go/lesson": f"{PUBLIC}/go/lesson",
        "Додати заняття в календар": f"{PUBLIC}/calendar/lesson.ics",
        **bot,
        PUBLIC: PUBLIC,
        "Відписатися": f"{PUBLIC}/unsubscribe/{TOKEN}",
        "Політика приватності": f"{PUBLIC}/privacy",
    }


def test_html_is_ukrainian_utf8_without_images_or_scripts(
    message: OutgoingEmail, html: Node
) -> None:
    assert html.find("html").attrs["lang"] == "uk"
    assert html.find("meta", charset="utf-8")
    assert html.find_all("img") == []
    assert "<script" not in message.html


def text_version_lines(with_bot: bool, public: str = PUBLIC) -> list[str]:
    """The text version: «текст — адреса» for links, one footer link per line."""

    def convert(line: str) -> list[str]:
        line = substitute(line, public).replace("**", "")
        parts = line.split(" · ") if " · " in line else [line]
        return [_MD_LINK.sub(r"\1 — \2", part) for part in parts]

    lines = [converted for line in body(with_bot) for converted in convert(line)]
    footer = [converted for line in FOOTER for converted in convert(line)]
    return [*lines, "", *footer]


def test_text_version_is_the_copy_with_visible_links(
    message: OutgoingEmail, with_bot: bool
) -> None:
    assert message.text.strip("\n").split("\n") == text_version_lines(with_bot)
    assert copy.one(LETTER, "Прехедер") not in message.text


@pytest.mark.parametrize("with_bot", [True, False], ids=["bot", "no-bot"])
def test_every_site_link_starts_with_the_public_address(with_bot: bool) -> None:
    public = "https://agent-next.pythoncourse.me"
    message = compose(with_bot=with_bot, public=public)
    hrefs = [a.attrs["href"] or "" for a in parse(message.html).find_all("a")]
    urls = [url.rstrip(".:,") for url in re.findall(r"https?://[^\s<>\"]+", message.text)]

    for url in [*hrefs, *urls]:
        assert url == public or url.startswith((f"{public}/", "https://t.me/")), url
    assert "agent.pythoncourse.me" not in message.html.replace("agent-next.pythoncourse.me", "")
    assert "agent.pythoncourse.me" not in message.text.replace("agent-next.pythoncourse.me", "")
    assert "на сайті agent-next.pythoncourse.me." in message.text
