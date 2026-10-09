"""A tiny HTML tree for structural assertions in tests (standard library only)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = {"meta", "link", "input", "br", "img", "hr", "source", "area", "base", "col", "wbr"}
# Elements whose boundaries separate words in the rendered page.
BLOCK = {
    "address", "article", "aside", "blockquote", "br", "dd", "details", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "label", "li", "main", "nav", "ol", "p", "section", "summary", "table",
    "tbody", "td", "th", "thead", "tr", "ul", "button",
}  # fmt: skip
INVISIBLE = {"script", "style", "head", "title"}


@dataclass
class Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list[Node | str] = field(default_factory=list)
    parent: Node | None = None

    def iter(self) -> Iterator[Node]:
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.iter()

    def find_all(self, tag: str | None = None, **attrs: str) -> list[Node]:
        return [
            node
            for node in self.iter()
            if (tag is None or node.tag == tag)
            and all(node.has(name.rstrip("_"), value) for name, value in attrs.items())
        ]

    def find(self, tag: str | None = None, **attrs: str) -> Node:
        found = self.find_all(tag, **attrs)
        assert found, f"no <{tag}> with {attrs}"
        return found[0]

    def has(self, name: str, value: str) -> bool:
        actual = self.attrs.get(name)
        if name == "class":
            return actual is not None and value in actual.split()
        return actual == value

    def ancestors(self) -> Iterator[Node]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def text(self) -> str:
        """Text as a reader sees it: block boundaries become spaces, whitespace collapsed."""
        parts: list[str] = []
        self._collect(parts)
        return " ".join("".join(parts).split())

    def text_raw(self) -> str:
        """All descendant text, including invisible elements such as ``<title>``."""
        return "".join(
            child if isinstance(child, str) else child.text_raw() for child in self.children
        )

    def _collect(self, parts: list[str]) -> None:
        if self.tag in INVISIBLE:
            return
        if self.tag in BLOCK:
            parts.append(" ")
        for child in self.children:
            if isinstance(child, Node):
                child._collect(parts)
            else:
                parts.append(child)
        if self.tag in BLOCK:
            parts.append(" ")


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.current = self.root

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, dict(attrs), parent=self.current)
        self.current.children.append(node)
        if tag not in VOID:
            self.current = node

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.current.children.append(Node(tag, dict(attrs), parent=self.current))

    def handle_endtag(self, tag: str) -> None:
        node: Node | None = self.current
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.current = node.parent

    def handle_data(self, data: str) -> None:
        self.current.children.append(data)


def parse(html: str) -> Node:
    builder = _Builder()
    builder.feed(html)
    builder.close()
    return builder.root


def normalize(text: str) -> str:
    return " ".join(text.split())
