"""Alembic history of v2: 0001 (v1's tables) → 0002 (the whole v2 model at once).

The model and the migrated database agree; the columns of all four tables follow
docs/requirements.md, section 10 (the test reads the document). Downgrades exist for the
test database only.
"""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect

from app.adapters.db.models import NAMING_CONVENTION, Base
from tests.database import ALEMBIC_INI, downgrade, migrate
from tests.db.schema import Column, document_tables, read_schema, revision_of, section

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "src" / "app" / "adapters" / "db" / "migrations"
REQUIREMENTS = ROOT / "docs" / "requirements.md"
TABLES = ("participants", "emails", "link_tokens", "clicks")
# Revision 0003 (requirements, section 9а): its columns are checked in tests/checkin/.
CHECKIN_TABLES = ("participant_groups", "checkins", "attendance")


def test_history_is_0001_then_0002_then_0003() -> None:
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))

    assert [revision.revision for revision in script.walk_revisions()] == ["0003", "0002", "0001"]
    assert script.get_heads() == ["0003"]


def test_versions_directory_holds_the_three_revisions() -> None:
    assert sorted(path.name for path in (MIGRATIONS / "versions").glob("*.py")) == [
        "0001_initial.py",
        "0002_v2_model.py",
        "0003_checkin.py",
    ]


def test_metadata_holds_the_tables_and_the_naming_convention() -> None:
    assert sorted(Base.metadata.tables) == sorted((*TABLES, *CHECKIN_TABLES))
    assert Base.metadata.naming_convention == NAMING_CONVENTION


def test_upgrade_head_builds_the_model(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        assert set(inspect(connection).get_table_names()) == {
            *TABLES,
            *CHECKIN_TABLES,
            "alembic_version",
        }
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_columns_follow_the_requirements(migrated_engine: Engine) -> None:
    """Names, order, types, empty or not, identity: requirements, section 10."""
    markdown = REQUIREMENTS.read_text(encoding="utf-8")
    documented = document_tables(section(markdown, "## 10. Дані"))
    with migrated_engine.connect() as connection:
        columns = read_schema(connection).columns

    assert list(documented) == list(TABLES)
    assert {
        table: tuple(
            Column(column.name, column.type, column.nullable, identity=column.identity)
            for column in items
        )
        for table, items in documented.items()
    } == {
        table: tuple(
            Column(column.name, column.type, column.nullable, identity=column.identity)
            for column in items
        )
        for table, items in columns.items()
        if table in TABLES
    }


def test_downgrade_to_0001_restores_v1_schema(fresh_engine: Engine) -> None:
    migrate(fresh_engine, "0001")
    with fresh_engine.connect() as connection:
        v1_schema = read_schema(connection)

    migrate(fresh_engine, "head")
    downgrade(fresh_engine, "0001")

    with fresh_engine.connect() as connection:
        assert revision_of(connection) == "0001"
        assert read_schema(connection) == v1_schema


def test_downgrade_base_leaves_no_tables(fresh_engine: Engine) -> None:
    migrate(fresh_engine, "head")
    downgrade(fresh_engine, "base")

    with fresh_engine.connect() as connection:
        assert set(inspect(connection).get_table_names()) <= {"alembic_version"}


def test_new_revision_follows_the_file_template(tmp_path: Path) -> None:
    """``alembic revision`` names files ``<rev>_<slug>.py`` in versions/ (alembic.ini)."""
    config = Config(str(ALEMBIC_INI))
    scripts = tmp_path / "migrations"
    (scripts / "versions").mkdir(parents=True)
    (scripts / "script.py.mako").write_bytes((MIGRATIONS / "script.py.mako").read_bytes())
    config.set_main_option("script_location", str(scripts))

    command.revision(config, message="Create items", rev_id="0001")

    assert [path.name for path in (scripts / "versions").glob("*.py")] == ["0001_create_items.py"]
