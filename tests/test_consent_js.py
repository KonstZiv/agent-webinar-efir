"""Runs the JavaScript unit tests of the cookie banner with Node's built-in test runner."""

import os
import shutil
import subprocess

import pytest

from tests.conftest import REPO_ROOT

JS_TESTS = sorted((REPO_ROOT / "tests" / "js").glob("*.test.cjs"))


def test_consent_js_unit_tests() -> None:
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
