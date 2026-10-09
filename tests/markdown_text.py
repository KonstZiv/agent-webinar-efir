"""Visible text of a Markdown document, read independently of the app's renderer.

Tests compare it with the text of pages rendered from ``docs/legal`` (Markdown markup
removed, whitespace collapsed).
"""

import re
from pathlib import Path

LEGAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "legal"

_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def plain(markdown: str) -> str:
    """Remove inline Markdown (links, bold, italic, code) and collapse whitespace.

    >>> plain("**Bold** text with [a link](/privacy) and `code`")
    'Bold text with a link and code'
    """
    text = _LINK.sub(r"\1", markdown)
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", text)
    return " ".join(text.split())


def list_items(text: str) -> list[str]:
    """Bullet and numbered list items (plain text)."""
    return [
        plain(m.group(1))
        for line in text.splitlines()
        if (m := re.match(r"^(?:- |\d+\. )(.+)$", line))
    ]


def table_rows(text: str) -> list[list[str]]:
    """Body rows of the first Markdown table in ``text`` (plain cells)."""
    rows = [line for line in text.splitlines() if line.startswith("|")]
    return [[plain(cell) for cell in row.strip("|").split("|")] for row in rows[2:]]


def document_texts(markdown: str) -> list[str]:
    """Every visible text unit of a Markdown document: headings, paragraphs, list items, cells."""
    texts: list[str] = []
    for block in re.split(r"\n\s*\n", markdown):
        lines = [line for line in block.strip().splitlines() if line.strip()]
        if not lines:
            continue
        if lines[0].startswith("|"):
            texts.extend(cell for row in table_rows(block) for cell in row if cell)
            texts.extend(plain(cell) for cell in lines[0].strip("|").split("|"))
        elif re.match(r"^(- |\d+\. )", lines[0]):
            texts.extend(list_items(block))
        else:
            texts.append(plain(re.sub(r"^#+ ", "", " ".join(lines))))
    return texts


def labelled(markdown: str, label: str) -> str:
    """Plain text after ``**label**`` up to the end of its line.

    >>> labelled("**Заголовок:** Файли cookie", "Заголовок:")
    'Файли cookie'
    """
    return plain(markdown.split(f"**{label}**", 1)[1].splitlines()[0])
