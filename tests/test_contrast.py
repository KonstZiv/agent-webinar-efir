"""Text colours in site.css meet WCAG AA (4.5:1) on the backgrounds they sit on."""

import re
from collections.abc import Callable

import pytest

from tests.conftest import REPO_ROOT

CSS = (REPO_ROOT / "src" / "app" / "adapters" / "web" / "static" / "css" / "site.css").read_text(
    encoding="utf-8"
)
AA = 4.5


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
