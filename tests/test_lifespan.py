"""Resources the application opens are closed on shutdown, all of them, in order."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main
from app.main import closing, create_app
from tests.conftest import SettingsFactory


def test_closing_calls_every_closer_on_shutdown() -> None:
    closed: list[str] = []
    app = FastAPI(lifespan=closing([lambda: closed.append("a"), lambda: closed.append("b")]))

    with TestClient(app):
        assert closed == []

    assert closed == ["a", "b"]


class SpyEngine:
    """Stands in for the SQLAlchemy engine: records ``dispose``; queries are not expected."""

    def __init__(self) -> None:
        self.disposed = 0

    def dispose(self) -> None:
        self.disposed += 1


def test_engine_is_registered_and_disposed(
    make_settings: SettingsFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = SpyEngine()
    monkeypatch.setattr(main, "make_engine", lambda url: engine)

    with TestClient(create_app(make_settings())):
        assert engine.disposed == 0

    assert engine.disposed == 1
