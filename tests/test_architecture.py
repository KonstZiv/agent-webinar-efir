"""Code boundaries from CLAUDE.md: ``core`` does not depend on frameworks or adapters."""

import ast
import doctest
import sys
from collections.abc import Collection
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


# --- slices: they add their own modules and never import each other ------------------------
#
# Code of the slice <s> (CLAUDE.md, «Зрізи»): app/slices/<s>.py, app/core/<s>/, app/adapters/<s>/,
# app/adapters/web/routers/<s>.py or <s>_*.py, tests/<s>/; and the files of SLICE_FILES. A
# slice exists once it has app/slices/<s>.py. What slices share comes from the foundation only.

TESTS = ROOT / "tests"
SLICES = SRC / "app" / "slices"
ROUTERS = SRC / "app" / "adapters" / "web" / "routers"
FOUNDATION_CORE = frozenset({"entities", "ports", "masking", "timezone", "event_values"})
FOUNDATION_ADAPTERS = frozenset({"clock", "content", "db", "ratelimit", "turnstile", "web"})
FOUNDATION_ROUTERS = frozenset({"favicon", "health", "home", "materials", "privacy"})
FOUNDATION_TESTS = frozenset({"adapters", "core", "db", "js", "sample_slice", "web"})
# Modules of a slice outside its own paths, each a single file: the token module that
# docs/contract.md (section 4) names app.core.unsubscribe belongs to «реєстрація і лист».
SLICE_FILES = {"app.core.unsubscribe": "registration"}


def slice_names() -> frozenset[str]:
    return frozenset(path.stem for path in SLICES.glob("*.py") if path.stem != "__init__")


def slice_of(module: str, slices: Collection[str]) -> str | None:
    """The slice a module belongs to, by the paths above; ``None`` for the foundation.

    The exact name wins, then the longest one whose ``<name>_`` starts the module's part.

    >>> slice_of("app.adapters.web.routers.bot_webhook", frozenset({"bot"}))
    'bot'
    >>> slice_of("app.core.bot_llm.draft", ["bot", "bot_llm"])
    'bot_llm'
    >>> slice_of("app.core.bot.linking", ["bot_llm", "bot"])
    'bot'
    """
    for file, owner in SLICE_FILES.items():
        if owner in slices and (module == file or module.startswith(f"{file}.")):
            return owner
    parts = module.split(".")
    candidates: list[str] = []
    if parts[:2] in (["app", "slices"], ["app", "core"], ["app", "adapters"]) and len(parts) > 2:
        candidates.append(parts[2])
    if parts[:4] == ["app", "adapters", "web", "routers"] and len(parts) > 4:
        candidates.append(parts[4])
    if parts[0] == "tests" and len(parts) > 1:
        candidates.append(parts[1])
    longest_first = sorted(slices, key=len, reverse=True)
    for candidate in candidates:
        if candidate in slices:
            return candidate
        for name in longest_first:
            if candidate.startswith(f"{name}_"):
                return name
    return None


def unknown_packages(
    slices: frozenset[str], *, app_dir: Path = SRC / "app", tests_dir: Path = TESTS
) -> list[str]:
    """Packages and route modules that belong neither to the foundation nor to a slice."""

    def names(directory: Path) -> set[str]:
        return {
            path.stem
            for path in directory.iterdir()
            if path.name != "__init__.py"
            and (path.suffix == ".py" or (path.is_dir() and path.name != "__pycache__"))
        }

    core = app_dir / "core"
    found = [
        f"app/core/{name}"
        for name in names(core) - FOUNDATION_CORE
        if name not in slices
        and not (
            SLICE_FILES.get(f"app.core.{name}") in slices
            and (core / f"{name}.py").is_file()
            and not (core / name).exists()
        )
    ]
    found += [
        f"app/adapters/{name}"
        for name in names(app_dir / "adapters") - FOUNDATION_ADAPTERS
        if name not in slices
    ]
    found += [
        f"routers/{name}.py"
        for name in names(app_dir / "adapters" / "web" / "routers") - FOUNDATION_ROUTERS
        if slice_of(f"app.adapters.web.routers.{name}", slices) is None
    ]
    found += [
        f"tests/{name}"
        for name in {path.name for path in tests_dir.iterdir() if path.is_dir()} - FOUNDATION_TESTS
        if name not in slices and name != "__pycache__"
    ]
    return sorted(found)


def cross_slice_imports(sources: dict[str, str], slices: frozenset[str]) -> list[str]:
    """``module → imported`` pairs where a module of one slice imports another slice."""
    found = []
    for module, source in sorted(sources.items()):
        own = slice_of(module, slices)
        if own is None:
            continue
        for name in sorted(imported_modules(source, module)):
            other = slice_of(name, slices)
            if other is not None and other != own:
                found.append(f"{module} → {name}")
    return found


def python_sources() -> dict[str, str]:
    sources = {module_name(path): path.read_text(encoding="utf-8") for path in SRC.rglob("*.py")}
    for path in TESTS.rglob("*.py"):
        parts = list(path.relative_to(ROOT).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        sources[".".join(parts)] = path.read_text(encoding="utf-8")
    return sources


def test_every_package_belongs_to_the_foundation_or_a_slice() -> None:
    """A new slice starts with app/slices/<slice>.py; other names are a mistake."""
    assert unknown_packages(slice_names()) == []


def test_slices_do_not_import_each_other() -> None:
    assert cross_slice_imports(python_sources(), slice_names()) == []


def test_the_slice_check_finds_imports_between_slices() -> None:
    slices = frozenset({"registration", "bot", "extras"})
    sources = {
        "app.core.bot.linking": "from app.core.registration.tokens import issue\n",
        "app.adapters.bot.telegram": "from app.core.ports import Messenger\n",
        "app.adapters.web.routers.bot_webhook": "from app.slices.extras import COUNTERS\n",
        "app.slices.extras": "from app.services import PARTICIPANTS\n",
        "tests.extras.test_counters": "from tests.registration.helpers import register\n",
        "app.main": "from app.slices import discover_slices\n",
    }

    assert cross_slice_imports(sources, slices) == [
        "app.adapters.web.routers.bot_webhook → app.slices.extras",
        "app.adapters.web.routers.bot_webhook → app.slices.extras.COUNTERS",
        "app.core.bot.linking → app.core.registration.tokens",
        "app.core.bot.linking → app.core.registration.tokens.issue",
        "tests.extras.test_counters → tests.registration.helpers",
        "tests.extras.test_counters → tests.registration.helpers.register",
    ]


def test_the_slice_of_a_module() -> None:
    slices = frozenset({"registration", "bot"})

    assert slice_of("app.core.registration.scenario", slices) == "registration"
    assert slice_of("app.adapters.bot.telegram", slices) == "bot"
    assert slice_of("app.adapters.web.routers.registration", slices) == "registration"
    assert slice_of("app.slices.bot", slices) == "bot"
    assert slice_of("tests.bot.test_webhook", slices) == "bot"
    assert slice_of("app.core.ports", slices) is None
    assert slice_of("app.adapters.web.routers.health", slices) is None
    assert slice_of("app.services", slices) is None


@pytest.mark.parametrize("order", [["bot", "bot_llm"], ["bot_llm", "bot"]])
def test_the_longest_slice_name_wins_in_any_order(order: list[str]) -> None:
    """``bot_llm`` is not a part of ``bot``, whatever order the names come in."""
    assert slice_of("app.core.bot_llm.draft", order) == "bot_llm"
    assert slice_of("app.adapters.web.routers.bot_llm_webhook", order) == "bot_llm"
    assert slice_of("app.core.bot.linking", order) == "bot"
    assert slice_of("app.adapters.web.routers.bot_webhook", order) == "bot"


def test_the_examples_of_this_module() -> None:
    """Doctests outside src/ are not collected by themselves."""
    result = doctest.testmod(sys.modules[__name__])

    assert (result.failed, result.attempted > 0) == (0, True)


# --- the token module of the contract belongs to «реєстрація і лист» ------------------------
#
# docs/contract.md, section 4, names it app.core.unsubscribe: one file of the slice
# «реєстрація і лист» outside its own package, nothing more.


def test_the_token_module_belongs_to_registration() -> None:
    assert slice_of("app.core.unsubscribe", {"registration"}) == "registration"
    assert slice_of("app.core.unsubscribe.make_token", {"registration"}) == "registration"
    assert slice_of("app.core.unsubscribe", {"bot"}) is None


def test_another_slice_may_not_import_the_token_module() -> None:
    sources = {"app.core.bot.linking": "from app.core.unsubscribe import read_token\n"}

    assert cross_slice_imports(sources, frozenset({"registration", "bot"})) == [
        "app.core.bot.linking → app.core.unsubscribe",
        "app.core.bot.linking → app.core.unsubscribe.read_token",
    ]


def make_tree(root: Path, *files: str) -> Path:
    """A skeleton of src/app and tests with the given extra files; returns ``root``."""
    for directory in ("app/core", "app/adapters/web/routers", "tests"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return root


@pytest.mark.parametrize(
    ("files", "slices", "unknown"),
    [
        (["app/core/unsubscribe.py"], {"registration"}, []),
        (["app/core/unsubscribe.py"], set(), ["app/core/unsubscribe"]),
        (["app/core/unsubscribe.py"], {"bot"}, ["app/core/unsubscribe"]),
        (["app/core/unsubscribe/__init__.py"], {"registration"}, ["app/core/unsubscribe"]),
    ],
)
def test_only_the_token_file_of_registration_is_allowed_in_core(
    tmp_path: Path, files: list[str], slices: set[str], unknown: list[str]
) -> None:
    root = make_tree(tmp_path, *files)

    assert unknown_packages(frozenset(slices), app_dir=root / "app", tests_dir=root / "tests") == (
        unknown
    )
