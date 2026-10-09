"""Every doctest in ``src/app`` runs (migrations are scripts, not modules)."""

import doctest
import importlib
import pkgutil

import app

EXCLUDED_PREFIXES = ("app.adapters.db.migrations",)


def app_modules() -> list[str]:
    return sorted(
        info.name
        for info in pkgutil.walk_packages(app.__path__, prefix="app.")
        if not info.name.startswith(EXCLUDED_PREFIXES)
    )


def test_all_doctests_pass() -> None:
    attempted = 0
    for name in app_modules():
        result = doctest.testmod(importlib.import_module(name))
        assert result.failed == 0, f"doctest failed in {name}"
        attempted += result.attempted

    assert attempted > 0


def examples_in(name: str) -> int:
    tests = doctest.DocTestFinder().find(importlib.import_module(name))
    return sum(len(test.examples) for test in tests)


def test_known_doctests_are_collected() -> None:
    assert examples_in("app.core.masking") > 0
    assert examples_in("app.settings") > 0
    assert examples_in("app.adapters.web.redirect") > 0
