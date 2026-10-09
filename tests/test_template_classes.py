"""Every class the page templates use is styled in site.css (no dead class names)."""

import re
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT

WEB = REPO_ROOT / "src" / "app" / "adapters" / "web"
CSS = (WEB / "static" / "css" / "site.css").read_text(encoding="utf-8")
TEMPLATES = sorted((WEB / "templates").rglob("*.html"))


def classes(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return {name for value in re.findall(r'class="([^"{]+)"', text) for name in value.split()}


def test_templates_exist() -> None:
    assert TEMPLATES


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda path: path.name)
def test_template_classes_are_defined(template: Path) -> None:
    missing = {
        name for name in classes(template) if not re.search(rf"\.{re.escape(name)}(?![\w-])", CSS)
    }

    assert missing == set()
