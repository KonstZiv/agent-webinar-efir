"""The real entry point (uvicorn factory) refuses to start with unusable settings or texts.

The redirect stub starts with nothing but ``DATABASE_URL`` and ``REDIRECT_BASE_URL``.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.content.legal import ContentError
from app.main import create_app
from tests.conftest import ALL_SETTING_NAMES, SENTINEL_VALUES, SettingsFactory
from tests.fakes import FakeDatabaseProbe


def run_uvicorn(
    overrides: dict[str, str | None], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = {name: value for name, value in os.environ.items() if name not in ALL_SETTING_NAMES}
    env.update(SENTINEL_VALUES)
    for name, value in overrides.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
        ],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def assert_no_values_leak(output: str) -> None:
    for name, value in SENTINEL_VALUES.items():
        assert value not in output, f"value of {name} leaked into the startup error"


def test_uvicorn_does_not_start_without_database_url() -> None:
    result = run_uvicorn({"DATABASE_URL": None})

    assert result.returncode != 0
    assert "DATABASE_URL" in result.stdout + result.stderr
    assert_no_values_leak(result.stdout + result.stderr)


@pytest.mark.parametrize(
    ("overrides", "named"),
    [
        ({"PUBLIC_BASE_URL": None}, "PUBLIC_BASE_URL"),
        ({"ADMIN_TOKEN": None}, "ADMIN_TOKEN"),
        ({"SITE_MODE": "replay"}, "RECORDING_YOUTUBE_ID"),
        ({"SITE_MODE": "course"}, "SITE_MODE"),
    ],
    ids=["no-public-base-url", "no-admin-token", "replay-without-recording", "unknown-mode"],
)
def test_uvicorn_does_not_start_without_what_the_mode_needs(
    overrides: dict[str, str | None], named: str
) -> None:
    """Without a required setting there is no app, so /healthz never answers 200 for it."""
    result = run_uvicorn(overrides)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert named in output
    assert_no_values_leak(output)


def test_uvicorn_does_not_start_with_invalid_redirect_base_url() -> None:
    raw = "https://new.example.com?x=1"

    result = run_uvicorn({"REDIRECT_BASE_URL": raw})

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "REDIRECT_BASE_URL" in output
    assert raw not in output
    assert_no_values_leak(output)


def test_uvicorn_does_not_start_without_legal_texts(tmp_path: Path) -> None:
    result = run_uvicorn({}, cwd=tmp_path)

    assert result.returncode != 0
    assert "privacy.md" in result.stdout + result.stderr
    assert_no_values_leak(result.stdout + result.stderr)


def test_create_app_needs_legal_texts(make_settings: SettingsFactory, tmp_path: Path) -> None:
    with pytest.raises(ContentError, match="privacy.md"):
        create_app(make_settings(), db_probe=FakeDatabaseProbe(), docs_dir=tmp_path)


def test_redirect_stub_starts_with_two_variables(
    clean_env: pytest.MonkeyPatch, test_db_url: str
) -> None:
    """Railway's stub service: only DATABASE_URL and REDIRECT_BASE_URL are set."""
    clean_env.setenv("DATABASE_URL", test_db_url)
    clean_env.setenv("REDIRECT_BASE_URL", "https://new.example.com")

    with TestClient(create_app(), follow_redirects=False) as client:
        health = client.get("/healthz")
        page = client.get("/")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert page.status_code == 307
    assert page.headers["location"] == "https://new.example.com/"
