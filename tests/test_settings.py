import pytest

from app.settings import (
    ConfigError,
    Settings,
    load_database_settings,
    normalize_database_url,
)
from tests.conftest import ALL_SETTING_NAMES, REQUIRED_ENV, SENTINEL_VALUES, SettingsFactory


def assert_no_values_leak(message: str) -> None:
    for name, value in SENTINEL_VALUES.items():
        assert value not in message, f"value of {name} leaked into the error message"


def test_settings_fields_match_known_variables() -> None:
    assert {name.upper() for name in Settings.model_fields} == set(ALL_SETTING_NAMES)


def test_only_database_url_is_required(make_settings: SettingsFactory) -> None:
    settings = make_settings()

    assert settings.redirect_base_url == ""
    assert settings.indexing_enabled is False
    assert settings.ga4_measurement_id == ""
    assert settings.turnstile_site_key == ""
    assert settings.turnstile_secret_key is None
    assert settings.turnstile_allowed_hostnames == ()
    assert settings.railway_git_commit_sha == ""


def test_optional_settings_are_read(make_settings: SettingsFactory) -> None:
    settings = make_settings(
        REDIRECT_BASE_URL="https://new.example.com",
        INDEXING_ENABLED="true",
        GA4_MEASUREMENT_ID="G-SENTINEL01",
        TURNSTILE_SITE_KEY="sentinel-turnstile-site-key",
        TURNSTILE_SECRET_KEY="sentinel-turnstile-secret-key",
    )

    assert settings.redirect_base_url == "https://new.example.com"
    assert settings.indexing_enabled is True
    assert settings.ga4_measurement_id == "G-SENTINEL01"
    assert settings.turnstile_site_key == "sentinel-turnstile-site-key"
    assert settings.turnstile_secret_key is not None
    assert settings.turnstile_secret_key.get_secret_value() == "sentinel-turnstile-secret-key"
    assert "sentinel-turnstile-secret-key" not in repr(settings)


def test_missing_database_url_is_named(make_settings: SettingsFactory) -> None:
    with pytest.raises(ConfigError) as error:
        make_settings(DATABASE_URL=None, GA4_MEASUREMENT_ID="G-SENTINEL01")

    message = str(error.value)
    assert "DATABASE_URL" in message
    assert_no_values_leak(message)


def test_empty_required_variable_counts_as_missing(make_settings: SettingsFactory) -> None:
    with pytest.raises(ConfigError) as error:
        make_settings(DATABASE_URL="")

    assert "DATABASE_URL" in str(error.value)


def test_all_problems_are_reported_at_once(make_settings: SettingsFactory) -> None:
    with pytest.raises(ConfigError) as error:
        make_settings(DATABASE_URL=None, REDIRECT_BASE_URL="new.example.com")

    message = str(error.value)
    assert "DATABASE_URL" in message
    assert "REDIRECT_BASE_URL" in message


def test_error_hides_original_validation_error(make_settings: SettingsFactory) -> None:
    with pytest.raises(ConfigError) as error:
        make_settings(DATABASE_URL=None)

    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


def test_indexing_is_off_by_default(make_settings: SettingsFactory) -> None:
    assert make_settings().indexing_enabled is False
    assert make_settings(INDEXING_ENABLED="true").indexing_enabled is True


@pytest.mark.parametrize(
    ("sha", "short"),
    [("0123456789abcdef0123456789abcdef01234567", "0123456"), (None, "")],
)
def test_commit_short(make_settings: SettingsFactory, sha: str | None, short: str) -> None:
    assert make_settings(RAILWAY_GIT_COMMIT_SHA=sha).commit_short == short


def test_database_settings_need_only_database_url(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", REQUIRED_ENV["DATABASE_URL"])

    assert load_database_settings().database_url.get_secret_value() == (
        "postgresql+psycopg://app:sentinel-db-password@localhost:5432/sentinel_db"
    )


def test_database_settings_without_url(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError) as error:
        load_database_settings()

    assert "DATABASE_URL" in str(error.value)


# --- Turnstile: optional, adapter variables of no route ------------------------------------


def test_allowed_hostnames_are_comma_separated(make_settings: SettingsFactory) -> None:
    settings = make_settings(TURNSTILE_ALLOWED_HOSTNAMES=" a.example.com, b.example.com ,")

    assert settings.turnstile_allowed_hostnames == ("a.example.com", "b.example.com")


def test_allowed_hostnames_are_lower_case(make_settings: SettingsFactory) -> None:
    """An operator's «Site.Example.COM» must still match Turnstile's answer."""
    settings = make_settings(TURNSTILE_ALLOWED_HOSTNAMES="A.Example.COM,b.example.com")

    assert settings.turnstile_allowed_hostnames == ("a.example.com", "b.example.com")


def test_empty_turnstile_secret_counts_as_unset(make_settings: SettingsFactory) -> None:
    assert make_settings(TURNSTILE_SECRET_KEY="").turnstile_secret_key is None


# --- the database URL is a secret ----------------------------------------------------------


def test_database_url_password_is_hidden_in_repr(make_settings: SettingsFactory) -> None:
    settings = make_settings(TURNSTILE_SECRET_KEY="sentinel-turnstile-secret-key")

    for text in (repr(settings), str(settings)):
        assert "sentinel-db-password" not in text
        assert "sentinel-turnstile-secret-key" not in text


# --- DATABASE_URL is validated and normalised in Settings ----------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "postgres://user:pw@db.example.com:5432/app",
            "postgresql+psycopg://user:pw@db.example.com:5432/app",
        ),
        ("postgresql://user@db.example.com/app", "postgresql+psycopg://user@db.example.com/app"),
        (
            "postgresql+psycopg://user@db.example.com/app",
            "postgresql+psycopg://user@db.example.com/app",
        ),
    ],
)
def test_database_url_is_normalised(
    make_settings: SettingsFactory, raw: str, expected: str
) -> None:
    assert make_settings(DATABASE_URL=raw).database_url.get_secret_value() == expected


@pytest.mark.parametrize(
    "raw",
    [
        "mysql://user:sentinel-db-password@db.example.com/app",
        "postgresql://user:sentinel-db-password@db.example.com:notaport/app",
        "postgresql://user:sentinel-db-password@/app",
        "postgresql://user:sentinel-db-password@db.example.com",
        "not a url sentinel-db-password",
        "postgresql://user:sentinel-db-password@db.exa\nmple.com/app",
    ],
)
def test_invalid_database_url_is_rejected_without_echo(
    make_settings: SettingsFactory, raw: str
) -> None:
    with pytest.raises(ConfigError) as error:
        make_settings(DATABASE_URL=raw)

    message = str(error.value)
    assert "DATABASE_URL" in message
    assert "sentinel-db-password" not in message
    assert "notaport" not in message


def test_normalize_database_url_error_does_not_echo_value() -> None:
    with pytest.raises(ValueError) as error:
        normalize_database_url("mysql://user:sentinel-db-password@db.example.com/app")

    assert "sentinel-db-password" not in str(error.value)


# --- REDIRECT_BASE_URL: an absolute http(s) site root --------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://new.example.com/", "https://new.example.com"),
        ("https://new.example.com", "https://new.example.com"),
        ("http://new.example.com:8080/", "http://new.example.com:8080"),
        ("https://New.Example.COM", "https://new.example.com"),
        ("http://localhost:8000", "http://localhost:8000"),
        ("http://127.0.0.1:8000/", "http://127.0.0.1:8000"),
        ("http://[::1]:8000", "http://[::1]:8000"),
        # An internationalised name becomes ASCII: header values cannot carry Cyrillic.
        ("https://пошта.укр/", "https://xn--80a1acn3a.xn--j1amh"),
    ],
)
def test_redirect_base_url_is_normalised(
    make_settings: SettingsFactory, raw: str, expected: str
) -> None:
    assert make_settings(REDIRECT_BASE_URL=raw).redirect_base_url == expected


def test_empty_redirect_base_url_means_off(make_settings: SettingsFactory) -> None:
    assert make_settings(REDIRECT_BASE_URL="").redirect_base_url == ""


@pytest.mark.parametrize(
    "raw",
    [
        "new.example.com",
        "//new.example.com",
        "ftp://new.example.com",
        "https://",
        "https://new.example.com/path",
        "https://new.example.com?x=1",
        "https://new.example.com/?x=1",
        "https://new.example.com#top",
        "https://user:pw@new.example.com",
        "https://new.exa\nmple.com",
        "https://new.example.com:notaport",
        # the host itself must be DNS labels or an IP address
        "https://new.example.com\\evil.example.org",
        "https://new.example.com,",
        "https://new.example.com;x",
        "https://new.example.com%2F",
        "https://new.example.com:",
        "https://new..example.com",
        "https://-new.example.com",
        "https://new_site.example.com",
        "https://[not-an-ip]",
    ],
)
def test_invalid_redirect_base_url_is_rejected_without_values(
    make_settings: SettingsFactory, raw: str
) -> None:
    with pytest.raises(ConfigError) as error:
        make_settings(REDIRECT_BASE_URL=raw, **SENTINEL_VALUES)

    message = str(error.value)
    assert "REDIRECT_BASE_URL" in message
    assert raw not in message
    assert_no_values_leak(message)
