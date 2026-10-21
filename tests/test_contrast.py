"""Text colours meet WCAG AA (4.5:1) on the backgrounds they sit on, in every file of static/css.

The named pairs check the template's tokens in site.css; the general check takes every rule of
every file that sets both a text colour and a background, so a slice's own file is checked too.
Colours that are not plain hex values (gradients, ``rgba``) cannot be checked statically.
"""

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT

CSS_DIR = REPO_ROOT / "src" / "app" / "adapters" / "web" / "static" / "css"
CSS = (CSS_DIR / "site.css").read_text(encoding="utf-8")
# Every file, site.css first as base.html links them: a later token definition wins.
ALL_CSS = [CSS_DIR / "site.css", *sorted(p for p in CSS_DIR.glob("*.css") if p.name != "site.css")]
AA = 4.5
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def token(name: str) -> str:
    match = re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", CSS)
    assert match is not None, name
    return match.group(1)


def rule_value(selector: str, prop: str) -> str:
    block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert block is not None, selector
    value = re.search(rf"(?<![-\w]){prop}:\s*([^;]+);", block.group(1))
    assert value is not None, f"{selector} {prop}"
    color = value.group(1).strip()
    var = re.fullmatch(r"var\(--([\w-]+)\)", color)
    return token(var.group(1)) if var else color


def luminance(color: str) -> float:
    channels = [int(color.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(foreground: str, background: str) -> float:
    high, low = sorted([luminance(foreground), luminance(background)], reverse=True)
    return (high + 0.05) / (low + 0.05)


PAIRS: list[tuple[str, Callable[[], str], Callable[[], str]]] = [
    ("body text on white", lambda: token("ink"), lambda: token("bg")),
    ("secondary text on white", lambda: token("ink-2"), lambda: token("bg")),
    ("secondary text on the soft background", lambda: token("ink-2"), lambda: token("bg-soft")),
    ("links on white", lambda: token("accent"), lambda: token("bg")),
    ("links on the soft background", lambda: token("accent"), lambda: token("bg-soft")),
    (
        "footer text on the footer",
        lambda: rule_value(".site-footer", "color"),
        lambda: rule_value(".site-footer", "background"),
    ),
    (
        "banner text on the banner",
        lambda: rule_value(".cookie-banner", "color"),
        lambda: rule_value(".cookie-banner", "background"),
    ),
    (
        "banner buttons",
        lambda: rule_value(".cookie-banner__button", "color"),
        lambda: rule_value(".cookie-banner__button", "background"),
    ),
    (
        "banner buttons on hover",
        lambda: rule_value(".cookie-banner__button", "color"),
        lambda: rule_value(".cookie-banner__button:hover", "background"),
    ),
]


@pytest.mark.parametrize(("what", "foreground", "background"), PAIRS, ids=[p[0] for p in PAIRS])
def test_text_contrast_is_aa(
    what: str, foreground: Callable[[], str], background: Callable[[], str]
) -> None:
    assert contrast(foreground(), background()) >= AA, what


def tokens(files: list[Path]) -> dict[str, str]:
    found: dict[str, str] = {}
    for path in files:
        found.update(
            re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", path.read_text(encoding="utf-8"))
        )
    return found


def resolved(value: str, known: dict[str, str]) -> str | None:
    """A plain hex colour, directly or through ``var(--token)``; ``None`` otherwise."""
    value = value.strip()
    var = re.fullmatch(r"var\(--([\w-]+)\)", value)
    if var:
        return known.get(var.group(1))
    return value if _HEX.fullmatch(value) else None


def coloured_rules() -> list[tuple[str, str, str]]:
    """``(file and selector, text colour, background)`` of every rule that sets both."""
    known = tokens(ALL_CSS)
    found = []
    for path in ALL_CSS:
        text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
        for selector, body in _RULE.findall(text):
            color = re.search(r"(?<![-\w])color:\s*([^;]+);", body)
            background = re.search(r"(?<![-\w])background(?:-color)?:\s*([^;]+);", body)
            if not (color and background):
                continue
            fg, bg = resolved(color.group(1), known), resolved(background.group(1), known)
            if fg and bg:
                found.append((f"{path.name} {' '.join(selector.split())}", fg, bg))
    return found


def test_rules_with_text_and_background_are_found() -> None:
    assert len(coloured_rules()) >= 4


@pytest.mark.parametrize(("rule", "foreground", "background"), coloured_rules(), ids=lambda v: v)
def test_every_rule_with_text_and_background_is_aa(
    rule: str, foreground: str, background: str
) -> None:
    assert contrast(foreground, background) >= AA, rule
