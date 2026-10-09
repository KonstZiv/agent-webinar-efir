"""The dependency container never exposes secrets from the settings."""

from app.main import create_app
from tests.conftest import OPTIONAL_ENV, SettingsFactory
from tests.fakes import FakeDatabaseProbe


def test_container_repr_hides_secrets(make_settings: SettingsFactory) -> None:
    app = create_app(make_settings(**OPTIONAL_ENV), db_probe=FakeDatabaseProbe())

    text = repr(app.state.container)
    assert "sentinel-db-password" not in text
    assert "sentinel-turnstile-secret-key" not in text


def test_container_repr_is_short(make_settings: SettingsFactory) -> None:
    app = create_app(make_settings(), db_probe=FakeDatabaseProbe())

    text = repr(app.state.container)
    assert "Політика приватності" not in text
    assert "Jinja2Templates" not in text
    assert len(text) < 2000
