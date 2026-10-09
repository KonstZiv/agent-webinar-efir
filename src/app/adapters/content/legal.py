"""Legal texts from ``docs/legal``, rendered once at startup.

``privacy.md`` is shown whole; ``consent.md`` gives the section «Текст позначки»;
``cookie-banner.md`` gives the banner title, text, buttons and the footer link name.
A missing file or section stops the application.
"""

import re
from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.rules_core import StateCore
from markdown_it.token import Token
from markdown_it.utils import OptionsDict
from markupsafe import Markup

PRIVACY_FILE = "privacy.md"
CONSENT_FILE = "consent.md"
BANNER_FILE = "cookie-banner.md"
CONSENT_SECTION = "Текст позначки"
BANNER_SECTION = "Текст банера"
BANNER_TITLE = "Заголовок:"
BANNER_TEXT = "Текст:"
BANNER_BUTTONS = "Кнопки:"
BANNER_SETTINGS_LINK = "Посилання внизу кожної сторінки:"

_BARE_LINK = re.compile(r"https?://[^\s<>\"']+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_TRAILING_PUNCTUATION = ".,;:!?»)…"


class ContentError(Exception):
    """A legal text is missing or does not have the expected structure."""


@dataclass(frozen=True, slots=True)
class CookieBannerTexts:
    title: str
    text_html: Markup
    allow: str
    reject: str
    settings_link: str


@dataclass(frozen=True, slots=True)
class LegalTexts:
    privacy_title: str
    privacy_html: Markup
    consent_html: Markup
    banner: CookieBannerTexts


def _link_tokens(md: MarkdownIt, text: Token) -> list[Token]:
    """Split a text token into text and link tokens around bare URLs and email addresses."""
    tokens: list[Token] = []
    position = 0
    for match in _BARE_LINK.finditer(text.content):
        address = match.group(0).rstrip(_TRAILING_PUNCTUATION)
        if not address:
            continue
        start, end = match.start(), match.start() + len(address)
        href = address if address.startswith("http") else f"mailto:{address}"
        if start > position:
            tokens.append(Token("text", "", 0, content=text.content[position:start]))
        tokens.append(Token("link_open", "a", 1, attrs={"href": md.normalizeLink(href)}))
        tokens.append(Token("text", "", 0, content=address))
        tokens.append(Token("link_close", "a", -1))
        position = end
    if position < len(text.content):
        tokens.append(Token("text", "", 0, content=text.content[position:]))
    return tokens


def _bare_links(state: StateCore) -> None:
    """Core rule: bare URLs and email addresses become links (no linkify package needed)."""
    for block in state.tokens:
        if block.type != "inline" or not block.children:
            continue
        children: list[Token] = []
        inside_link = 0
        for token in block.children:
            inside_link += {"link_open": 1, "link_close": -1}.get(token.type, 0)
            if token.type == "text" and not inside_link:
                children.extend(_link_tokens(state.md, token))
            else:
                children.append(token)
        block.children = children


def _table_open(
    self: RendererHTML,
    tokens: Sequence[Token],
    idx: int,
    options: OptionsDict,
    env: MutableMapping[str, object],
) -> str:
    # Wide tables scroll inside their own box instead of widening the page.
    return '<div class="table-scroll">' + self.renderToken(tokens, idx, options, env)


def _table_close(
    self: RendererHTML,
    tokens: Sequence[Token],
    idx: int,
    options: OptionsDict,
    env: MutableMapping[str, object],
) -> str:
    return "</table></div>\n"


def _markdown() -> MarkdownIt:
    # Raw HTML in the documents is escaped, never passed through.
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    md.core.ruler.push("bare_links", _bare_links)
    md.add_render_rule("table_open", _table_open)
    md.add_render_rule("table_close", _table_close)
    return md


def _renderer(md: MarkdownIt) -> RendererHTML:
    assert isinstance(md.renderer, RendererHTML)
    return md.renderer


def _render_inline(md: MarkdownIt, children: list[Token]) -> str:
    return _renderer(md).renderInline(children, md.options, {})


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")  # a byte order mark is not content
    except FileNotFoundError:
        raise ContentError(
            f"Legal text not found: {path} (docs/ is read from the working directory)"
        ) from None
    except (OSError, UnicodeDecodeError) as error:
        raise ContentError(f"Legal text cannot be read: {path} ({type(error).__name__})") from None


def _section(tokens: list[Token], title: str, source: str) -> list[Token]:
    """Tokens between the ``## title`` heading and the next heading of level 1 or 2."""
    starts = [
        index + 3  # heading_open, inline, heading_close
        for index, token in enumerate(tokens)
        if token.type == "heading_open"
        and token.tag == "h2"
        and tokens[index + 1].content.strip() == title
    ]
    if not starts:
        raise ContentError(f"{source}: section «{title}» not found")
    start = starts[0]
    end = next(
        (
            index
            for index in range(start, len(tokens))
            if tokens[index].type == "heading_open" and tokens[index].tag in {"h1", "h2"}
        ),
        len(tokens),
    )
    return tokens[start:end]


def _paragraphs(tokens: list[Token]) -> list[Token]:
    """Inline tokens of top-level paragraphs."""
    return [
        tokens[index + 1]
        for index, token in enumerate(tokens)
        if token.type == "paragraph_open" and token.level == 0
    ]


def _plain(children: list[Token]) -> str:
    text = "".join(
        token.content if token.type in {"text", "code_inline"} else " "
        for token in children
        if token.type in {"text", "code_inline", "softbreak", "hardbreak"}
    )
    return " ".join(text.split())


def _labelled(paragraphs: list[Token], label: str, source: str) -> list[Token]:
    """Children after a leading ``**label**`` in the paragraph that starts with it."""
    for inline in paragraphs:
        children = [t for t in inline.children or [] if not (t.type == "text" and not t.content)]
        if (
            len(children) >= 3
            and children[0].type == "strong_open"
            and children[1].content.strip() == label
            and children[2].type == "strong_close"
        ):
            rest = children[3:]
            if rest and rest[0].type == "text":
                first = rest[0].copy()
                first.content = first.content.lstrip()
                rest = [first, *rest[1:]]
            return rest
    raise ContentError(f"{source}: «{label}» not found in section «{BANNER_SECTION}»")


def _privacy(md: MarkdownIt, text: str) -> tuple[str, Markup]:
    tokens = md.parse(text)
    # The visible text, without Markdown: it goes to <title> and the footer link.
    title = next(
        (
            _plain(tokens[index + 1].children or [])
            for index, token in enumerate(tokens)
            if token.type == "heading_open" and token.tag == "h1"
        ),
        None,
    )
    if not title:
        raise ContentError(f"{PRIVACY_FILE}: top heading «# …» not found")
    return title, Markup(_renderer(md).render(tokens, md.options, {}))


def _consent(md: MarkdownIt, text: str) -> Markup:
    paragraphs = _paragraphs(_section(md.parse(text), CONSENT_SECTION, CONSENT_FILE))
    if not paragraphs:
        raise ContentError(f"{CONSENT_FILE}: section «{CONSENT_SECTION}» is empty")
    html = " ".join(_render_inline(md, inline.children or []) for inline in paragraphs)
    return Markup(html)


def _banner(md: MarkdownIt, text: str) -> CookieBannerTexts:
    paragraphs = _paragraphs(_section(md.parse(text), BANNER_SECTION, BANNER_FILE))
    title = _plain(_labelled(paragraphs, BANNER_TITLE, BANNER_FILE))
    if not title:
        raise ContentError(f"{BANNER_FILE}: «{BANNER_TITLE}» is empty")
    text_tokens = _labelled(paragraphs, BANNER_TEXT, BANNER_FILE)
    if not _plain(text_tokens):
        raise ContentError(f"{BANNER_FILE}: «{BANNER_TEXT}» is empty")
    text_html = Markup(_render_inline(md, text_tokens).strip())
    buttons = [
        part.strip().strip("«»")
        for part in _plain(_labelled(paragraphs, BANNER_BUTTONS, BANNER_FILE)).split(" · ")
    ]
    if len(buttons) != 2 or not all(buttons):
        raise ContentError(f"{BANNER_FILE}: «{BANNER_BUTTONS}» must name two buttons")
    link = re.search(r"«(.+?)»", _plain(_labelled(paragraphs, BANNER_SETTINGS_LINK, BANNER_FILE)))
    if link is None:
        raise ContentError(f"{BANNER_FILE}: «{BANNER_SETTINGS_LINK}» has no name in «»")
    return CookieBannerTexts(
        title=title,
        text_html=text_html,
        allow=buttons[0],
        reject=buttons[1],
        settings_link=link.group(1),
    )


def load_legal_texts(docs_dir: Path) -> LegalTexts:
    """Read and render the legal texts from ``docs_dir / "legal"``."""
    legal_dir = docs_dir / "legal"
    md = _markdown()
    privacy_title, privacy_html = _privacy(md, _read(legal_dir / PRIVACY_FILE))
    return LegalTexts(
        privacy_title=privacy_title,
        privacy_html=privacy_html,
        consent_html=_consent(md, _read(legal_dir / CONSENT_FILE)),
        banner=_banner(md, _read(legal_dir / BANNER_FILE)),
    )
