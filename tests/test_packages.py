"""Packages the slices rely on are declared by the foundation (requirements, section 12).

Slices do not add packages: forms (``python-multipart``), calendar events (``icalendar``) and
the Claude API client (``anthropic``, Issue Л) are here from the start. Telegram and Resend
are called through ``httpx``, which the template already has. The one exception, agreed by the
coordinator on 15.10.2026: ``email-validator`` for the check of the mail domain of «реєстрація
і лист» (docs/requirements.md, section 5, «Поштовий домен»).
"""

import importlib
import re
import tomllib

import pytest

from tests.conftest import REPO_ROOT

# Distribution name in pyproject.toml → module that code imports.
SLICE_PACKAGES = {
    "python-multipart": "python_multipart",
    "icalendar": "icalendar",
    "anthropic": "anthropic",
    "httpx": "httpx",
    "email-validator": "email_validator",
}


def declared() -> set[str]:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return {
        re.split(r"[<>=\[ ;]", entry, maxsplit=1)[0] for entry in project["project"]["dependencies"]
    }


@pytest.mark.parametrize(("distribution", "module"), sorted(SLICE_PACKAGES.items()))
def test_slice_package_is_declared_and_importable(distribution: str, module: str) -> None:
    assert distribution in declared()
    importlib.import_module(module)
