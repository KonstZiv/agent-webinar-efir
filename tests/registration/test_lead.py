"""``generate_lead`` and the cookie ``webinar_lead`` in consent.js (requirements, section 9).

The JavaScript is tested by Node's built-in runner (tests/registration/js/*.test.cjs). The
cookie line of consent.js must be the contract's byte for byte (docs/contract.md, section 5),
and the success screen carries the marker the script looks for.
"""

import os
import re
import shutil
import subprocess

import pytest

from app.adapters.web.dependencies import STATIC_DIR
from tests.conftest import REPO_ROOT
from tests.test_contract import lead_cookie

JS_TESTS = sorted((REPO_ROOT / "tests" / "registration" / "js").glob("*.test.cjs"))
CONSENT_JS = (STATIC_DIR / "js" / "consent.js").read_text(encoding="utf-8")


def test_lead_js_unit_tests() -> None:
    assert JS_TESTS, "no JavaScript tests found"
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI") == "true":
            pytest.fail("node is required in CI to test static/js/consent.js")
        pytest.skip("node is not installed")

    result = subprocess.run(
        [node, "--test", *(str(path) for path in JS_TESTS)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_the_cookie_line_is_the_contracts() -> None:
    cookie, status = lead_cookie()

    assert status == "так"
    assert re.search(rf'"{re.escape(cookie)}"', CONSENT_JS)
    assert cookie == (
        "webinar_lead=1; Domain=.pythoncourse.me; Path=/; Max-Age=31536000; Secure; SameSite=Lax"
    )


def test_the_script_reports_the_lead_of_the_success_screen_and_fills_the_form() -> None:
    assert '"generate_lead"' in CONSENT_JS
    assert 'LEAD_MARKER = "[data-lead]"' in CONSENT_JS
    assert 'input[name="ga_client_id"]' in CONSENT_JS
    assert '"htmx:afterSettle"' in CONSENT_JS
