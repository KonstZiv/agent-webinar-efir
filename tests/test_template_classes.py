"""Every class the page templates use is styled in one of the files of static/css.

Each slice and the layout style their own partials in their own file (requirements, section 12),
so the search covers all files; no dead class names.
"""

import re
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT

WEB = REPO_ROOT / "src" / "app" / "adapters" / "web"
CSS = "\n".join(
    path.read_text(encoding="utf-8") for path in sorted((WEB / "static" / "css").glob("*.css"))
)
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
