"""Revisions generated from script.py.mako (first, regular, merge) pass the project's gates."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from mypy import api as mypy_api

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "src" / "app" / "adapters" / "db" / "migrations"
TEMPLATE = MIGRATIONS / "script.py.mako"
# Where generated revisions live in the project: the per-file rules of ruff apply here.
VERSIONS_IN_PROJECT = MIGRATIONS.relative_to(ROOT) / "versions"


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """A first revision, a regular one on top of it, a second branch and their merge."""
    scripts = tmp_path_factory.mktemp("alembic") / "migrations"
    (scripts / "versions").mkdir(parents=True)
    shutil.copy(TEMPLATE, scripts / "script.py.mako")
    config = Config()
    config.set_main_option("script_location", str(scripts))
    config.set_main_option("path_separator", "os")

    command.revision(config, message="first", rev_id="aaaa")
    command.revision(config, message="regular", rev_id="bbbb")
    command.revision(config, message="other branch", rev_id="cccc", head="base", splice=True)
    command.merge(config, revisions="heads", message="merge", rev_id="dddd")

    paths = {path.name.split("_", 1)[0]: path for path in (scripts / "versions").glob("*.py")}
    assert sorted(paths) == ["aaaa", "bbbb", "cccc", "dddd"]
    return paths


def test_generated_revisions_pass_mypy(generated: dict[str, Path]) -> None:
    files = sorted(str(path) for path in generated.values())
    stdout, stderr, status = mypy_api.run(
        [*files, "--config-file", str(ROOT / "pyproject.toml"), "--no-incremental"]
    )
    assert status == 0, stdout + stderr


@pytest.mark.parametrize(
    "rev_id", ["aaaa", "bbbb", "dddd"], ids=["first", "regular", "merge"]
)
def test_generated_revision_passes_ruff(generated: dict[str, Path], rev_id: str) -> None:
    path = generated[rev_id]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(ROOT / "pyproject.toml"),
            "--stdin-filename",
            str(VERSIONS_IN_PROJECT / path.name),
            "-",
        ],
        input=path.read_text(encoding="utf-8"),
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_first_revision_has_no_trailing_whitespace(generated: dict[str, Path]) -> None:
    lines = generated["aaaa"].read_text(encoding="utf-8").splitlines()

    assert [line for line in lines if line != line.rstrip()] == []
