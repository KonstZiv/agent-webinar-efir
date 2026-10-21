"""A slice plugs in by adding files: ``app/slices/<slice>.py`` and its routes, nothing else.

The sample slice in tests/sample_slice exists only for these tests. It is loaded the way a real
one is: its module is found in the package ``app.slices``, its routes in the package of
routers. Nothing in ``main.py`` or ``dependencies.py`` names it (requirements, section 12).
"""

import importlib
import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app import slices
from app.adapters.web import routers
from app.main import create_app
from app.services import MESSENGER, Key, Services, override
from app.slices import SliceSetup, discover_slices
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe, FakeMessenger

SAMPLE = Path(__file__).parent / "sample_slice"
SAMPLE_MODULES = ("app.slices.sample", "app.adapters.web.routers.sample")


class FakeGreeter:
    def greet(self) -> str:
        return "fake"


@pytest.fixture
def sample(monkeypatch: pytest.MonkeyPatch) -> Iterator[types.ModuleType]:
    """The sample slice as the only slice; its route joins the real routers."""
    monkeypatch.setattr(slices, "__path__", [str(SAMPLE / "slices")])
    monkeypatch.setattr(routers, "__path__", [*routers.__path__, str(SAMPLE / "routers")])
    module = importlib.import_module("app.slices.sample")
    module.EVENTS.clear()
    try:
        yield module
    finally:
        for name in SAMPLE_MODULES:
            sys.modules.pop(name, None)


def test_route_uses_the_adapter_chosen_by_settings(
    sample: types.ModuleType, make_settings: SettingsFactory
) -> None:
    settings = make_settings(SITE_MODE="replay", RECORDING_YOUTUBE_ID="dQw4w9WgXcQ")

    with TestClient(create_app(settings, db_probe=FakeDatabaseProbe())) as client:
        response = client.get("/sample")

    assert response.json() == {"greeting": "replay"}


def test_an_override_replaces_the_port_and_the_real_adapter_is_never_built(
    sample: types.ModuleType, make_settings: SettingsFactory
) -> None:
    app = create_app(
        make_settings(),
        db_probe=FakeDatabaseProbe(),
        overrides=[override(sample.GREETER, FakeGreeter())],
    )

    with TestClient(app) as client:
        response = client.get("/sample")

    assert response.json() == {"greeting": "fake"}
    assert "built http greeter" not in sample.EVENTS


def test_nothing_is_built_until_a_route_needs_it(
    sample: types.ModuleType, make_settings: SettingsFactory
) -> None:
    """``create_app(settings, db_probe=…)`` alone builds no client and reaches no network."""
    with TestClient(create_app(make_settings(), db_probe=FakeDatabaseProbe())) as client:
        assert client.get("/healthz").status_code == 200

    assert "built http greeter" not in sample.EVENTS


def test_the_real_adapter_would_reach_the_network(
    sample: types.ModuleType, make_settings: SettingsFactory
) -> None:
    """The guard of tests/conftest.py stops it: tests pass fakes."""
    app = create_app(make_settings(), db_probe=FakeDatabaseProbe())

    with TestClient(app) as client, pytest.raises(RuntimeError, match="network"):
        client.get("/sample")


def test_a_slice_middleware_wraps_every_route(
    sample: types.ModuleType, make_settings: SettingsFactory
) -> None:
    with TestClient(create_app(make_settings(), db_probe=FakeDatabaseProbe())) as client:
        responses = [client.get(path) for path in ("/healthz", "/privacy")]

    assert [response.headers.get("X-Sample-Slice") for response in responses] == ["1", "1"]


def test_start_up_and_shut_down_actions_run_in_order(
    sample: types.ModuleType, make_settings: SettingsFactory
) -> None:
    app = create_app(make_settings(), db_probe=FakeDatabaseProbe())
    assert sample.EVENTS == []

    with TestClient(app):
        assert sample.EVENTS == ["startup sync", "startup async"]

    assert sample.EVENTS[2:] == [
        "shutdown last registered",
        "shutdown first registered",
        "closed",
    ]


def test_a_slice_gives_templates_a_global(
    sample: types.ModuleType, make_settings: SettingsFactory
) -> None:
    app = create_app(make_settings(), db_probe=FakeDatabaseProbe())

    assert app.state.container.templates.env.globals["sample_motto"] == "slices only add files"


def test_the_redirect_stub_installs_no_slice(
    sample: types.ModuleType, make_settings: SettingsFactory
) -> None:
    """Every request but /healthz is redirected anyway; no slice starts anything."""
    app = create_app(
        make_settings(REDIRECT_BASE_URL="https://new.example.com"), db_probe=FakeDatabaseProbe()
    )

    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/sample")

    assert response.status_code == 307
    assert sample.EVENTS == []


def test_a_slice_module_without_install_is_a_mistake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "broken.py").write_text("VALUE = 1\n", encoding="utf-8")
    package = types.ModuleType("broken_slices")
    package.__path__ = [str(tmp_path)]
    monkeypatch.setitem(sys.modules, "broken_slices", package)
    monkeypatch.delitem(sys.modules, "broken_slices.broken", raising=False)

    with pytest.raises(TypeError, match="broken_slices.broken"):
        discover_slices(package)


def test_every_slice_of_the_application_can_be_installed() -> None:
    """Each module of ``app.slices`` defines ``install``; there may be none yet."""
    assert all(callable(found.install) for found in discover_slices(slices))


def test_a_slice_is_found_with_its_name(sample: types.ModuleType) -> None:
    assert [(found.name, found.install) for found in discover_slices(slices)] == [
        ("sample", sample.install)
    ]


# --- own keys of a slice: «<slice>.<name>» ------------------------------------------------
#
# Slices written in parallel cannot pick the same key: each names its own after itself. The
# shared ports of app.services keep their names.


def no_engine() -> Engine:
    raise AssertionError("the engine is not needed here")


@pytest.fixture
def setup(make_settings: SettingsFactory) -> SliceSetup:
    return SliceSetup(settings=make_settings(), services=Services(), _engine=no_engine)


def test_a_slice_provides_its_own_key_under_its_name(setup: SliceSetup) -> None:
    limiter = Key[str]("bot.rate_limiter")

    setup.for_slice("bot").provide(limiter, lambda: "memory")

    assert setup.services.get(limiter) == "memory"


@pytest.mark.parametrize(
    ("slice_name", "key"),
    [
        ("bot", "rate_limiter"),
        ("bot", "extras.cache"),
        ("bot", "botcache"),
        ("bot_llm", "bot.drafts"),
    ],
)
def test_a_key_outside_the_slice_name_is_a_mistake(
    setup: SliceSetup, slice_name: str, key: str
) -> None:
    with pytest.raises(ValueError, match=rf"{slice_name}\."):
        setup.for_slice(slice_name).provide(Key[str](key), lambda: "value")


def test_a_slice_provides_a_shared_port_by_its_shared_key(setup: SliceSetup) -> None:
    messenger = FakeMessenger()

    setup.for_slice("bot").provide(MESSENGER, lambda: messenger)

    assert setup.services.get(MESSENGER) is messenger


def test_slices_share_what_they_add(setup: SliceSetup) -> None:
    setup.for_slice("bot").on_startup(lambda: None)
    setup.for_slice("extras").template_global("counters", 0)

    assert len(setup.startup) == 1
    assert setup.template_globals == {"counters": 0}


def test_create_app_refuses_a_slice_key_without_its_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_settings: SettingsFactory
) -> None:
    (tmp_path / "extras.py").write_text(
        "from app.services import Key\n"
        "def install(setup):\n"
        "    setup.provide(Key('cache'), dict)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(slices, "__path__", [str(tmp_path)])
    monkeypatch.delitem(sys.modules, "app.slices.extras", raising=False)
    try:
        with pytest.raises(ValueError, match=r"extras\."):
            create_app(make_settings(), db_probe=FakeDatabaseProbe())
    finally:
        sys.modules.pop("app.slices.extras", None)
