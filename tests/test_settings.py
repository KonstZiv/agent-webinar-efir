"""Settings: every variable of docs/requirements.md, section 14, with formats and obligations.

Which variables are required depends on the mode of operation: the redirect stub needs only
``DATABASE_URL`` and ``REDIRECT_BASE_URL``; normal operation needs the full list, ``replay``
adds ``RECORDING_YOUTUBE_ID``; the bot and LLM groups work only as a whole.
"""

from datetime import datetime

import pytest

from app.settings import (
    ConfigError,
    Settings,
    load_database_settings,
    load_settings,
    normalize_database_url,
)
from tests.conftest import (
    ALL_SETTING_NAMES,
    BOT_ENV,
    LLM_ENV,
    REQUIRED_ENV,
    SECRET_VALUES,
    SENTINEL_VALUES,
    SettingsFactory,
)

NORMAL_REQUIRED = sorted(name for name in REQUIRED_ENV if name != "DATABASE_URL")


def assert_no_values_leak(message: str) -> None:
    for name, value in {**SENTINEL_VALUES, **BOT_ENV, **LLM_ENV}.items():
        assert value not in message, f"value of {name} leaked into the error message"


def config_error(make_settings: SettingsFactory, **env: str | None) -> str:
    with pytest.raises(ConfigError) as error:
        make_settings(**env)
    message = str(error.value)
    assert_no_values_leak(message)
    return message


def test_settings_fields_match_known_variables() -> None:
    assert {name.upper() for name in Settings.model_fields} == set(ALL_SETTING_NAMES)


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


# --- obligations by mode of operation ------------------------------------------------------


def test_normal_operation_reads_the_required_variables(make_settings: SettingsFactory) -> None:
    settings = make_settings()

    assert settings.site_mode == "live"
    assert settings.public_base_url == "https://public-sentinel.example.com"
    assert settings.event_start == datetime(2026, 10, 21, 19, 0)
    assert settings.lesson_end == datetime(2026, 10, 28, 21, 0)
    assert settings.course_url == "https://course-sentinel.example.com/course"
    assert settings.sender_email == "sender-sentinel@example.com"
    assert settings.admin_token is not None
    assert settings.admin_token.get_secret_value() == REQUIRED_ENV["ADMIN_TOKEN"]


def test_optional_variables_default_to_off(make_settings: SettingsFactory) -> None:
    settings = make_settings()

    assert (settings.redirect_base_url, settings.ga4_measurement_id) == ("", "")
    assert (settings.stream_url, settings.lesson_url, settings.recording_youtube_id) == ("", "", "")
    assert settings.registration_allowlist == ()
    assert settings.turnstile_allowed_hostnames == ()
    assert settings.telegram_bot_token is None
    assert (settings.telegram_bot_username, settings.telegram_channel) == ("", "")
    assert settings.telegram_webhook_secret is None
    assert settings.materials_slug == ""
    assert (settings.llm_enabled, settings.anthropic_api_key) == (False, None)
    assert settings.indexing_enabled is False


@pytest.mark.parametrize("name", NORMAL_REQUIRED)
def test_each_required_variable_is_named_when_missing(
    make_settings: SettingsFactory, name: str
) -> None:
    message = config_error(make_settings, **{name: None})

    assert f"{name}: required but not set" in message


def test_every_missing_variable_is_reported_at_once(make_settings: SettingsFactory) -> None:
    message = config_error(make_settings, **dict.fromkeys(NORMAL_REQUIRED))

    assert all(f"{name}: required but not set" in message for name in NORMAL_REQUIRED)


def test_redirect_stub_needs_only_two_variables(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", REQUIRED_ENV["DATABASE_URL"])
    clean_env.setenv("REDIRECT_BASE_URL", "https://new.example.com")

    settings = load_settings()

    assert settings.redirect_base_url == "https://new.example.com"
    assert settings.public_base_url == ""


def test_without_redirect_the_full_list_is_required(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", REQUIRED_ENV["DATABASE_URL"])

    with pytest.raises(ConfigError) as error:
        load_settings()

    assert all(f"{name}: required but not set" in str(error.value) for name in NORMAL_REQUIRED)


# --- SITE_MODE -----------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["live", "replay"])
def test_site_modes(make_settings: SettingsFactory, mode: str) -> None:
    assert make_settings(SITE_MODE=mode, RECORDING_YOUTUBE_ID="dQw4w9WgXcQ").site_mode == mode


@pytest.mark.parametrize("mode", ["course", "Live", "recording", "announce"])
def test_unknown_site_mode_stops_the_start(make_settings: SettingsFactory, mode: str) -> None:
    assert "SITE_MODE" in config_error(make_settings, SITE_MODE=mode)


def test_replay_needs_the_recording(make_settings: SettingsFactory) -> None:
    message = config_error(make_settings, SITE_MODE="replay")

    assert "RECORDING_YOUTUBE_ID: required" in message


# --- optional groups -----------------------------------------------------------------------


def test_bot_group_is_read_whole(make_settings: SettingsFactory) -> None:
    settings = make_settings(**BOT_ENV)

    assert settings.telegram_bot_token is not None
    assert settings.telegram_bot_username == "sentinel_webinar_bot"
    assert settings.telegram_channel == "@sentinel_channel"


@pytest.mark.parametrize("left_out", sorted(BOT_ENV))
def test_partial_bot_group_stops_the_start(make_settings: SettingsFactory, left_out: str) -> None:
    message = config_error(make_settings, **{**BOT_ENV, left_out: None})

    assert f"{left_out}: required" in message


def test_llm_needs_its_key(make_settings: SettingsFactory) -> None:
    key = LLM_ENV["ANTHROPIC_API_KEY"]

    assert make_settings(**LLM_ENV).llm_enabled is True
    assert "ANTHROPIC_API_KEY: required" in config_error(
        make_settings, LLM_ENABLED="true", ANTHROPIC_API_KEY=None
    )
    assert make_settings(LLM_ENABLED=None, ANTHROPIC_API_KEY=key).llm_enabled is False


# --- formats -------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["EVENT_START", "EVENT_END", "LESSON_START", "LESSON_END"])
@pytest.mark.parametrize(
    "raw",
    [
        "2026-10-26T19:00+02:00",  # an offset: the time must be local
        "2026-10-26T19:00Z",
        "2026-03-29T03:30",  # does not exist in Kyiv: clocks jump from 03:00 to 04:00
        "2026-10-25T03:30",  # happens twice in Kyiv: clocks go back from 04:00 to 03:00
        "26.10.2026 19:00",
    ],
)
def test_event_times_are_single_kyiv_local_times(
    make_settings: SettingsFactory, name: str, raw: str
) -> None:
    assert name in config_error(make_settings, **{name: raw})


@pytest.mark.parametrize(
    ("start", "end"),
    [("EVENT_START", "EVENT_END"), ("LESSON_START", "LESSON_END")],
)
def test_end_is_later_than_start(make_settings: SettingsFactory, start: str, end: str) -> None:
    message = config_error(make_settings, **{start: "2026-10-26T19:00", end: "2026-10-26T19:00"})

    assert f"{end} must be later than {start}" in message


@pytest.mark.parametrize("name", ["COURSE_URL", "STREAM_URL", "LESSON_URL"])
@pytest.mark.parametrize("raw", ["course.example.com", "ftp://x.example.com", "https://", "x y"])
def test_links_are_absolute_web_addresses(
    make_settings: SettingsFactory, name: str, raw: str
) -> None:
    assert name in config_error(make_settings, **{name: raw})


def test_public_base_url_is_a_site_root(make_settings: SettingsFactory) -> None:
    assert make_settings(PUBLIC_BASE_URL="https://Agent.Example.com/").public_base_url == (
        "https://agent.example.com"
    )
    assert "PUBLIC_BASE_URL" in config_error(
        make_settings, PUBLIC_BASE_URL="https://agent.example.com/path"
    )


@pytest.mark.parametrize("raw", ["sender", "sender@", "@example.com", "a b@example.com"])
def test_sender_email_is_an_address(make_settings: SettingsFactory, raw: str) -> None:
    assert "SENDER_EMAIL" in config_error(make_settings, SENDER_EMAIL=raw)


@pytest.mark.parametrize("name", ["UNSUBSCRIBE_SECRET", "ADMIN_TOKEN"])
def test_secrets_have_at_least_32_characters(make_settings: SettingsFactory, name: str) -> None:
    assert make_settings(**{name: "s" * 32}) is not None
    assert f"{name}: " in config_error(make_settings, **{name: "s" * 31})


@pytest.mark.parametrize(
    ("raw", "accepted"),
    [
        ("A-z_0-9" * 5, True),
        ("s" * 256, True),
        ("s" * 31, False),
        ("s" * 257, False),
        ("s" * 31 + "!", False),
        ("s" * 32 + " ", False),
        ("s" * 31 + "ї", False),
    ],
)
def test_webhook_secret_is_what_telegram_accepts(
    make_settings: SettingsFactory, raw: str, accepted: bool
) -> None:
    """32–256 characters of A-Z a-z 0-9 _ - (requirements, section 14)."""
    env = {**BOT_ENV, "TELEGRAM_WEBHOOK_SECRET": raw}
    if accepted:
        secret = make_settings(**env).telegram_webhook_secret
        assert secret is not None and secret.get_secret_value() == raw
    else:
        assert "TELEGRAM_WEBHOOK_SECRET" in config_error(make_settings, **env)


@pytest.mark.parametrize(
    ("name", "raw"),
    [
        ("TELEGRAM_CHANNEL", "agentic_engineers"),
        ("TELEGRAM_CHANNEL", "@agentic engineers"),
        ("TELEGRAM_CHANNEL", "https://t.me/agentic_engineers"),
        ("TELEGRAM_BOT_USERNAME", "@webinar_bot"),
        ("TELEGRAM_BOT_USERNAME", "webinar bot"),
        ("TELEGRAM_BOT_USERNAME", "webinar-bot"),
    ],
)
def test_telegram_names(make_settings: SettingsFactory, name: str, raw: str) -> None:
    """The channel is ``@name``; the bot's username goes without ``@`` into t.me/<username>."""
    assert name in config_error(make_settings, **{**BOT_ENV, name: raw})


@pytest.mark.parametrize(
    ("raw", "accepted"),
    [
        ("Ab3_-xyz", True),
        ("a" * 32, True),
        ("a" * 7, False),
        ("a" * 33, False),
        ("abc/defgh", False),
        ("abc defgh", False),
        ("матеріали", False),
    ],
)
def test_materials_slug(make_settings: SettingsFactory, raw: str, accepted: bool) -> None:
    """8–32 characters of A-Z a-z 0-9 _ -; empty means no materials page."""
    if accepted:
        assert make_settings(MATERIALS_SLUG=raw).materials_slug == raw
    else:
        assert "MATERIALS_SLUG" in config_error(make_settings, MATERIALS_SLUG=raw)


def test_allowlist_is_comma_separated_and_normalised(make_settings: SettingsFactory) -> None:
    settings = make_settings(REGISTRATION_ALLOWLIST=" Tester@Example.com , qa@example.com,")

    assert settings.registration_allowlist == ("tester@example.com", "qa@example.com")


@pytest.mark.parametrize("raw", ["tester+1@example.com", "not-an-address", "a@b@example.com"])
def test_allowlist_entries_are_plain_addresses(make_settings: SettingsFactory, raw: str) -> None:
    """``+`` variants are allowed automatically (requirements, section 5), never listed."""
    message = config_error(make_settings, REGISTRATION_ALLOWLIST=f"qa@example.com,{raw}")

    assert "REGISTRATION_ALLOWLIST" in message
    assert raw not in message


# --- secrets stay hidden -------------------------------------------------------------------


def test_secrets_are_hidden_in_repr(make_settings: SettingsFactory) -> None:
    settings = make_settings(**BOT_ENV, **LLM_ENV)

    for text in (repr(settings), str(settings)):
        assert [name for name, value in SECRET_VALUES.items() if value in text] == []
