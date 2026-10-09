"""Code boundaries from CLAUDE.md: ``core`` does not depend on frameworks or adapters."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
CORE = SRC / "app" / "core"
FORBIDDEN = (
    "fastapi",
    "starlette",
    "sqlalchemy",
    "alembic",
    "psycopg",
    "httpx",
    "jinja2",
    "uvicorn",
    "app.adapters",
)


def imported_modules(source: str, module: str, *, is_package: bool = False) -> set[str]:
    """Absolute names of everything ``source`` (the code of ``module``) imports.

    ``from X import y`` yields both ``X`` and ``X.y``: ``y`` may be a submodule.
    """
    package = module if is_package else module.rpartition(".")[0]
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - (node.level - 1)])
                origin = f"{base}.{node.module}" if node.module else base
            else:
                origin = node.module or ""
            names.add(origin)
            names.update(f"{origin}.{alias.name}" for alias in node.names)
    return names


def is_forbidden(name: str) -> bool:
    return any(name == root or name.startswith(f"{root}.") for root in FORBIDDEN)


def module_name(path: Path) -> str:
    parts = list(path.relative_to(SRC).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def core_files() -> list[Path]:
    return sorted(CORE.rglob("*.py"))


@pytest.mark.parametrize(
    ("source", "module", "is_package", "expected"),
    [
        ("import app.adapters.db", "app.core.x", False, "app.adapters.db"),
        ("from app import adapters", "app.core.x", False, "app.adapters"),
        ("from .. import adapters", "app.core.x", False, "app.adapters"),
        ("from ..adapters.db import models", "app.core.x", False, "app.adapters.db"),
        ("from ... import adapters", "app.core.sub.x", False, "app.adapters"),
        ("from .. import adapters", "app.core", True, "app.adapters"),
        ("from sqlalchemy.orm import Session", "app.core.x", False, "sqlalchemy.orm"),
    ],
)
def test_detector_sees_every_import_form(
    source: str, module: str, is_package: bool, expected: str
) -> None:
    names = imported_modules(source, module, is_package=is_package)

    assert expected in names
    assert any(is_forbidden(name) for name in names)


def test_detector_allows_core_and_stdlib() -> None:
    names = imported_modules("from typing import Protocol\nfrom . import ports", "app.core.x")

    assert not any(is_forbidden(name) for name in names)


def test_core_has_modules() -> None:
    assert core_files()


@pytest.mark.parametrize("path", core_files(), ids=lambda path: path.name)
def test_core_does_not_import_frameworks_or_adapters(path: Path) -> None:
    names = imported_modules(
        path.read_text(encoding="utf-8"), module_name(path), is_package=path.name == "__init__.py"
    )

    assert not [name for name in names if is_forbidden(name)]


def builds_own_engine(node: ast.AST) -> bool:
    if isinstance(node, ast.ImportFrom):
        return any(alias.name == "create_engine" for alias in node.names)
    return isinstance(node, ast.Attribute) and node.attr == "create_engine"


def test_tests_use_the_production_engine_factory() -> None:
    """Tests build engines with ``make_engine``, as the application does."""
    offenders = [
        path.name
        for path in sorted((ROOT / "tests").rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if builds_own_engine(node)
    ]

    assert offenders == []
