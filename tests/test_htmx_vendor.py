"""The htmx file in static/ is the version named in CLAUDE.md (vendored, not loaded from a CDN)."""

import re

from tests.conftest import REPO_ROOT

HTMX = REPO_ROOT / "src" / "app" / "adapters" / "web" / "static" / "js" / "htmx.min.js"


def test_vendored_htmx_matches_the_stack() -> None:
    vendored = re.search(r'version:"([\d.]+)"', HTMX.read_text(encoding="utf-8"))
    stack = re.search(r"HTMX ([\d.]+)", (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8"))

    assert vendored is not None and stack is not None
    assert vendored.group(1) == stack.group(1) == "2.0.11"
