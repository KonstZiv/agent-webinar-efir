"""Alembic is ready but empty: no revisions, no tables; the first revision lands in versions/."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect

from app.adapters.db.engine import make_engine
from app.adapters.db.models import NAMING_CONVENTION, Base
from tests.db.conftest import ALEMBIC_INI, run_alembic

MIGRATIONS = Path(__file__).resolve().parents[2] / "src" / "app" / "adapters" / "db" / "migrations"


def test_there_are_no_revisions_yet() -> None:
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))

    assert list(script.walk_revisions()) == []
    assert script.get_heads() == []


def test_versions_directory_holds_no_migration() -> None:
    assert sorted(path.name for path in (MIGRATIONS / "versions").iterdir()) == [".gitkeep"]


def test_metadata_has_no_tables_and_a_naming_convention() -> None:
    assert Base.metadata.tables == {}
    assert Base.metadata.naming_convention == NAMING_CONVENTION


def test_upgrade_head_creates_only_the_version_table(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        assert set(inspect(connection).get_table_names()) <= {"alembic_version"}
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_downgrade_base_leaves_no_tables(test_db_url: str) -> None:
    engine = make_engine(test_db_url)
    try:
        with engine.begin() as connection:
            run_alembic(connection, command.upgrade, "head")
            run_alembic(connection, command.downgrade, "base")
            assert set(inspect(connection).get_table_names()) <= {"alembic_version"}
    finally:
        engine.dispose()


def test_new_revision_follows_the_file_template(tmp_path: Path) -> None:
    """``alembic revision`` names files ``<rev>_<slug>.py`` in versions/ (alembic.ini)."""
    config = Config(str(ALEMBIC_INI))
    scripts = tmp_path / "migrations"
    (scripts / "versions").mkdir(parents=True)
    (scripts / "script.py.mako").write_bytes((MIGRATIONS / "script.py.mako").read_bytes())
    config.set_main_option("script_location", str(scripts))

    command.revision(config, message="Create items", rev_id="0001")

    assert [path.name for path in (scripts / "versions").glob("*.py")] == ["0001_create_items.py"]
