"""Addresses in the slice's tests are ``example.com`` only (CLAUDE.md, «Секрети і дані»).

A real mail domain in a test may one day receive a letter, and an unreserved one may belong to
someone. The only other addresses are the ones the site's texts carry and the pages show — the
contacts and the identifiers of the calendar events (docs/copy.md, docs/legal/,
docs/contract.md): the tests check the pages against them.
"""

import re
from pathlib import Path

from tests.conftest import REPO_ROOT

SLICE_TESTS = REPO_ROOT / "tests" / "registration"
SITE_TEXTS = [
    REPO_ROOT / "docs" / "copy.md",
    REPO_ROOT / "docs" / "contract.md",
    *sorted((REPO_ROOT / "docs" / "legal").glob("*.md")),
]
# Anything shaped like an address with a top-level domain of letters (Unicode included).
ADDRESS = re.compile(r"[\w.+%*-]+@((?:[\w-]+\.)+[^\W\d_]{2,})")
RESERVED = re.compile(r"(?:.+\.)?example\.com", re.IGNORECASE)


def addresses(text: str) -> set[tuple[str, str]]:
    """Every address in ``text`` with its domain.

    >>> sorted(addresses("Ivan@Gmail.com, v***@example.com, name@example"))
    [('Ivan@Gmail.com', 'Gmail.com'), ('v***@example.com', 'example.com')]
    """
    return {(found.group(0), found.group(1)) for found in ADDRESS.finditer(text)}


def test_the_detector_finds_what_the_review_found() -> None:
    found = addresses('"  Ivan@Gmail.com ", "name@sub.example-domain.com", "a@приклад.укр"')

    assert {domain for _, domain in found} == {"Gmail.com", "sub.example-domain.com", "приклад.укр"}


def test_addresses_in_the_slice_tests_are_at_example_com() -> None:
    shown = {address for path in SITE_TEXTS for address, _ in addresses(path.read_text("utf-8"))}
    files = sorted(SLICE_TESTS.rglob("*.py")) + sorted(SLICE_TESTS.rglob("*.cjs"))
    files.remove(Path(__file__))  # the detector's own examples

    found = {
        f"{path.relative_to(REPO_ROOT)}: {address}"
        for path in files
        for address, domain in addresses(path.read_text("utf-8"))
        if not RESERVED.fullmatch(domain) and address not in shown
    }

    assert sorted(found) == []
