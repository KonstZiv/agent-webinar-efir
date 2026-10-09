import importlib
import pkgutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.web import routers
from app.adapters.web.routing import discover_routers
from app.main import create_app
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe


def test_every_router_module_is_discovered() -> None:
    module_names = [module.name for module in pkgutil.iter_modules(routers.__path__)]

    assert module_names
    assert len(discover_routers(routers)) == len(module_names)


@pytest.mark.parametrize("path", ["/", "/healthz", "/privacy", "/favicon.ico"])
def test_app_serves_discovered_routes(make_settings: SettingsFactory, path: str) -> None:
    app = create_app(make_settings(), db_probe=FakeDatabaseProbe())

    with TestClient(app) as client:
        assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_are_disabled(make_settings: SettingsFactory, path: str) -> None:
    app = create_app(make_settings(), db_probe=FakeDatabaseProbe())

    with TestClient(app) as client:
        assert client.get(path).status_code == 404


def test_module_without_router_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "routers_without_router"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "broken.py").write_text("value = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(TypeError, match="broken"):
        discover_routers(importlib.import_module("routers_without_router"))
