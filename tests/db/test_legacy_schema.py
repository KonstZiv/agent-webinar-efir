"""Revision 0001 is v1's first migration: after it the schema is exactly docs/legacy-schema.md.

The expected schema is read from the document (section «Таблиці v1»), not from a copy in the
tests: columns with types, NULL and defaults; the names of all constraints; check expressions;
indexes — only those PostgreSQL builds for primary keys and UNIQUE constraints. A v1 database
already at 0001 is then the same database for v2, and later revisions find constraints by name.
"""

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine

from tests.database import ALEMBIC_INI, migrate
from tests.db.schema import (
    Column,
    Constraint,
    DocumentColumn,
    check_definition,
    document_tables,
    index_columns,
    read_schema,
    section,
)

ROOT = Path(__file__).resolve().parents[2]
LEGACY_SCHEMA = ROOT / "docs" / "legacy-schema.md"
VERSIONS = ROOT / "src" / "app" / "adapters" / "db" / "migrations" / "versions"
REVISION_0001 = VERSIONS / "0001_initial.py"
# sha256 of v1's ``0001_initial.py`` after its docstring (agent-webinar-v1, commit fee3439):
# requirements, section 10 — a verbatim copy, only the docstring may differ.
V1_REVISION_CODE_SHA256 = "57855b87ccda57e781c83f2ef6d9fbffb357f41d622645288ed26b3d8c50534f"

_CODE = re.compile(r"`([^`]+)`")
_NAME = re.compile(r"`((?:pk|uq|ck|fk)_\w+)`")
_DEFAULT = re.compile(r"за замовчуванням `([^`]+)`")
_FOREIGN_KEY = re.compile(r"`(fk_\w+)` → `(\w+)\.(\w+)`(?:, `ON DELETE (\w+(?: \w+)?)`)?")
_CHECK = re.compile(r"CHECK `(ck_\w+)`: (.*?)(?: — |;|$)")
_INDEX = re.compile(r"`(\w+)` \(([^)]*)\)")


@dataclass(frozen=True, slots=True)
class LegacyDocument:
    tables: dict[str, tuple[DocumentColumn, ...]]
    indexes: dict[str, tuple[str, ...]]  # name → columns, from «Індекси»


@cache
def legacy_document() -> LegacyDocument:
    text = section(LEGACY_SCHEMA.read_text(encoding="utf-8"), "## Таблиці v1")
    indexes = {
        name: tuple(_CODE.findall(columns))
        for name, columns in _INDEX.findall(section(text, "### Індекси"))
    }
    return LegacyDocument(tables=document_tables(text), indexes=indexes)


def table_of(name: str, document: LegacyDocument) -> str:
    """The table whose notes name the constraint or index."""
    owners = [
        table
        for table, columns in document.tables.items()
        if any(f"`{name}`" in column.notes for column in columns)
    ]
    if len(owners) != 1:
        raise LookupError(f"{name} must be named in the notes of exactly one table: {owners}")
    return owners[0]


def expected_columns(columns: tuple[DocumentColumn, ...]) -> tuple[Column, ...]:
    return tuple(
        Column(
            name=column.name,
            type=column.type,
            nullable=column.nullable,
            default=match.group(1) if (match := _DEFAULT.search(column.notes)) else None,
            identity=column.identity,
        )
        for column in columns
    )


def check_expression(column: str, described: str) -> str:
    """The CHECK expression from the notes: a code expression or a list of allowed values.

    >>> check_expression("kind", "`a`, `b`")
    "kind IN ('a', 'b')"
    >>> check_expression("email", "`email = lower(email)`")
    'email = lower(email)'
    """
    values = _CODE.findall(described)
    if len(values) == 1 and " " in values[0]:
        return values[0]
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def expected_constraints(connection: Connection, document: LegacyDocument) -> dict[str, Constraint]:
    expected: dict[str, Constraint] = {}
    for name, columns in document.indexes.items():
        kind, keyword = ("p", "PRIMARY KEY") if name.startswith("pk_") else ("u", "UNIQUE")
        definition = f"{keyword} ({', '.join(columns)})"
        expected[name] = Constraint(table_of(name, document), kind, definition)
    for table, columns in document.tables.items():
        for column in columns:
            for name, target, target_column, on_delete in _FOREIGN_KEY.findall(column.notes):
                definition = f"FOREIGN KEY ({column.name}) REFERENCES {target}({target_column})"
                if on_delete:
                    definition += f" ON DELETE {on_delete}"
                expected[name] = Constraint(table, "f", definition)
            for name, described in _CHECK.findall(column.notes):
                expression = check_expression(column.name, described)
                definition = check_definition(connection, columns, expression)
                expected[name] = Constraint(table, "c", definition)
    return expected


@pytest.fixture
def at_0001(fresh_engine: Engine) -> Iterator[Connection]:
    migrate(fresh_engine, "0001")
    with fresh_engine.connect() as connection:
        yield connection


def test_revision_0001_is_v1_code_verbatim() -> None:
    code = REVISION_0001.read_text(encoding="utf-8").split('"""', 2)[2]

    assert hashlib.sha256(code.encode("utf-8")).hexdigest() == V1_REVISION_CODE_SHA256


def test_revision_0001_is_the_first_one() -> None:
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))

    assert script.get_revision("0001").down_revision is None  # type: ignore[union-attr]


def test_the_document_is_read_whole() -> None:
    """The tables and index list this test relies on are where the test looks for them."""
    document = legacy_document()

    assert list(document.tables) == ["participants", "emails"]
    assert len(document.tables["participants"]) == 17
    assert len(document.tables["emails"]) == 12
    assert len(document.indexes) == 6


def test_columns_match_the_document(at_0001: Connection) -> None:
    schema = read_schema(at_0001)

    assert schema.columns == {
        table: expected_columns(columns) for table, columns in legacy_document().tables.items()
    }


def test_constraints_match_the_document(at_0001: Connection) -> None:
    """Names of all constraints and their definitions as PostgreSQL prints them."""
    expected = expected_constraints(at_0001, legacy_document())

    assert read_schema(at_0001).constraints == expected


def test_only_key_indexes_exist(at_0001: Connection) -> None:
    """No separate indexes: only those under primary keys and UNIQUE constraints."""
    schema = read_schema(at_0001)

    assert {
        name: index_columns(index.definition) for name, index in schema.indexes.items()
    } == legacy_document().indexes
    assert all(schema.constraints[name].kind in ("p", "u") for name in schema.indexes)
