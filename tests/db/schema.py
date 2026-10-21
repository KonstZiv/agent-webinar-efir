"""The schema as PostgreSQL holds it, and the schema as the documents describe it.

``read_schema`` takes a snapshot from the system catalogs: columns, constraints and indexes
with the definitions PostgreSQL itself prints. ``document_tables`` reads the column tables of
``docs/legacy-schema.md`` and ``docs/requirements.md`` (section 10), so tests compare the
database with the documents rather than with a copy kept in the tests.
"""

import re
from dataclasses import dataclass

from sqlalchemy import Connection, text

# Types as the documents spell them → as ``format_type`` prints them.
_DOCUMENT_TYPES = {
    "bigint": "bigint",
    "integer": "integer",
    "uuid": "uuid",
    "boolean": "boolean",
    "jsonb": "jsonb",
    "timestamptz": "timestamp with time zone",
}
_VARCHAR = re.compile(r"varchar\((\d+)\)")
_CODE = re.compile(r"`([^`]+)`")
# A table cell boundary: a pipe not escaped as ``\|``.
_CELL_BOUNDARY = re.compile(r"(?<!\\)\|")


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    type: str
    nullable: bool
    default: str | None = None
    identity: bool = False


@dataclass(frozen=True, slots=True)
class Constraint:
    table: str
    kind: str  # p: primary key, u: unique, c: check, f: foreign key
    definition: str


@dataclass(frozen=True, slots=True)
class Index:
    table: str
    definition: str


@dataclass(frozen=True, slots=True)
class Schema:
    columns: dict[str, tuple[Column, ...]]  # table → columns in their order
    constraints: dict[str, Constraint]  # by name
    indexes: dict[str, Index]  # by name


@dataclass(frozen=True, slots=True)
class DocumentColumn:
    name: str
    type: str  # as format_type prints it
    nullable: bool
    identity: bool
    notes: str  # the last cells of the row, raw Markdown


# --- the database --------------------------------------------------------------------------

_COLUMNS = text(
    """
    SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull,
           pg_get_expr(d.adbin, d.adrelid), a.attidentity <> ''
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
    WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname <> 'alembic_version'
      AND a.attnum > 0 AND NOT a.attisdropped
    ORDER BY c.relname, a.attnum
    """
)
_CONSTRAINTS = text(
    """
    SELECT con.conname, c.relname, con.contype, pg_get_constraintdef(con.oid)
    FROM pg_constraint con
    JOIN pg_class c ON c.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relname <> 'alembic_version' AND con.contype <> 'n'
    """
)
_INDEXES = text(
    """
    SELECT i.relname, t.relname, pg_get_indexdef(i.oid)
    FROM pg_index x
    JOIN pg_class i ON i.oid = x.indexrelid
    JOIN pg_class t ON t.oid = x.indrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname = 'public' AND t.relname <> 'alembic_version'
    """
)


def read_schema(connection: Connection) -> Schema:
    """Snapshot of the public schema, without Alembic's own table."""
    columns: dict[str, list[Column]] = {}
    for table, name, type_, nullable, default, identity in connection.execute(_COLUMNS):
        columns.setdefault(table, []).append(Column(name, type_, nullable, default, identity))
    return Schema(
        columns={table: tuple(items) for table, items in columns.items()},
        constraints={
            name: Constraint(table, kind, definition)
            for name, table, kind, definition in connection.execute(_CONSTRAINTS)
        },
        indexes={
            name: Index(table, definition)
            for name, table, definition in connection.execute(_INDEXES)
        },
    )


def revision_of(connection: Connection) -> str | None:
    """The revision recorded by Alembic, or ``None`` before the first migration."""
    exists = connection.execute(text("SELECT to_regclass('public.alembic_version')")).scalar()
    if exists is None:
        return None
    return connection.execute(text("SELECT version_num FROM alembic_version")).scalar()


def index_columns(definition: str) -> tuple[str, ...]:
    """Columns of an index from its ``pg_get_indexdef`` text.

    >>> index_columns("CREATE UNIQUE INDEX x ON public.t USING btree (a, b) WHERE (a > 0)")
    ('a', 'b')
    """
    match = re.search(r"USING \w+ \(([^)]*)\)", definition)
    if match is None:
        raise ValueError(f"not an index definition: {definition!r}")
    return tuple(column.strip() for column in match.group(1).split(","))


def check_definition(
    connection: Connection, columns: tuple[DocumentColumn, ...], expression: str
) -> str:
    """How PostgreSQL prints ``CHECK (expression)`` on a table with these columns.

    The probe table lives in a savepoint that is rolled back, so nothing remains.
    """
    with connection.begin_nested() as savepoint:
        names = ", ".join(f"{column.name} {column.type}" for column in columns)
        connection.execute(
            text(f"CREATE TEMP TABLE check_probe ({names}, CONSTRAINT probe CHECK ({expression}))")
        )
        definition = connection.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'probe'")
        ).scalar_one()
        savepoint.rollback()
    return str(definition)


# --- the documents -------------------------------------------------------------------------


def section(markdown: str, heading: str) -> str:
    """Text under the heading line that starts with ``heading`` up to the next heading
    of the same or a higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    pattern = rf"^{re.escape(heading)}[^\n]*\n(.*?)(?=^#{{1,{level}}} |\Z)"
    match = re.search(pattern, markdown, re.MULTILINE | re.DOTALL)
    if match is None:
        raise LookupError(f"no section «{heading}»")
    return match.group(1)


def cells(line: str) -> list[str]:
    r"""Raw cells of a Markdown table row; ``\|`` inside a cell is a literal pipe.

    >>> cells(r"| `a` | `x \| y` |")
    ['`a`', '`x | y`']
    """
    inner = line.strip().removeprefix("|").removesuffix("|")
    return [cell.strip().replace("\\|", "|") for cell in _CELL_BOUNDARY.split(inner)]


def document_type(cell: str) -> str:
    """``format_type`` spelling of a type cell such as ```varchar(254)``` or ```bigint`, identity``.

    >>> document_type("`varchar(254)`")
    'character varying(254)'
    """
    spelled = _CODE.findall(cell)[0]
    if match := _VARCHAR.fullmatch(spelled):
        return f"character varying({match.group(1)})"
    return _DOCUMENT_TYPES[spelled]


def document_tables(markdown: str) -> dict[str, tuple[DocumentColumn, ...]]:
    """Column tables under ``### `table` …`` headings: name, type, empty or not, notes.

    A first cell may name several columns of the same type (``utm_source``, ``utm_medium``…).
    """
    tables: dict[str, tuple[DocumentColumn, ...]] = {}
    for match in re.finditer(r"^### `(\w+)`[^\n]*\n(.*?)(?=^#{1,3} |\Z)", markdown, re.M | re.S):
        rows = [line for line in match.group(2).splitlines() if line.startswith("|")][2:]
        columns: list[DocumentColumn] = []
        for row in rows:
            name_cell, type_cell, empty_cell, *rest = cells(row)
            if empty_cell not in ("так", "ні"):
                raise ValueError(f"empty or not must be «так» or «ні»: {empty_cell!r}")
            columns.extend(
                DocumentColumn(
                    name=name,
                    type=document_type(type_cell),
                    nullable=empty_cell == "так",
                    identity="identity" in type_cell,
                    notes=" | ".join(rest),
                )
                for name in _CODE.findall(name_cell)
            )
        tables[match.group(1)] = tuple(columns)
    if not tables:
        raise LookupError("no column tables found")
    return tables
