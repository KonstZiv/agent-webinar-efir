"""Application settings read from environment variables (see docs/env.example).

Every variable of docs/requirements.md, section 14, is here, with its format. Which ones are
required depends on the mode of operation: the redirect stub needs only ``DATABASE_URL`` and
``REDIRECT_BASE_URL``; normal operation needs ``NORMAL_REQUIRED``; ``replay`` adds
``RECORDING_YOUTUBE_ID``; the bot and LLM groups work only as a whole. Without a required
variable the application does not start, so ``/healthz`` never answers 200 for it.

Errors never echo setting values: an invalid ``REDIRECT_BASE_URL`` must not print the
database URL or any other secret that happens to be set.
"""

import ipaddress
import re
from datetime import datetime
from typing import Annotated, Literal, Self
from urllib.parse import SplitResult, urlsplit

from pydantic import (
    AfterValidator,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pydantic_settings import SettingsError as SettingsSourceError

from app.core.timezone import KYIV

COMMIT_SHORT_LENGTH = 7
MIN_SECRET_LENGTH = 32
# Telegram accepts a webhook secret of 1–256 characters of A-Z a-z 0-9 _ - only.
_WEBHOOK_SECRET = re.compile(r"[A-Za-z0-9_-]{32,256}")
_MATERIALS_SLUG = re.compile(r"[A-Za-z0-9_-]{8,32}")
_BOT_USERNAME = re.compile(r"[A-Za-z0-9_]+")
_CHANNEL = re.compile(r"@[A-Za-z0-9_]+")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# The model-level error that lists required variables one by one (see ``_describe``).
_MISSING = "settings_missing"
REQUIRED = "required but not set"
NORMAL_REQUIRED = (
    "public_base_url",
    "event_start",
    "event_end",
    "lesson_start",
    "lesson_end",
    "course_url",
    "resend_api_key",
    "sender_email",
    "unsubscribe_secret",
    "admin_token",
    "turnstile_site_key",
    "turnstile_secret_key",
)
BOT_GROUP = (
    "telegram_bot_token",
    "telegram_bot_username",
    "telegram_webhook_secret",
    "telegram_channel",
)

type SiteMode = Literal["live", "replay"]
DRIVER_SCHEME = "postgresql+psycopg"
_POSTGRES_SCHEMES = frozenset({"postgres", "postgresql", DRIVER_SCHEME})
_WEB_SCHEMES = frozenset({"http", "https"})
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")

_ENV_CONFIG = SettingsConfigDict(
    env_ignore_empty=True,  # an empty variable counts as unset
    hide_input_in_errors=True,
    extra="ignore",
)


class ConfigError(Exception):
    """Settings are missing or invalid; the message names variables, never their values."""


def _has_unsafe_characters(value: str) -> bool:
    return any(char.isspace() or not char.isprintable() for char in value)


def _split_url(value: str, error: ValueError) -> SplitResult:
    """Split a URL, turning every parsing problem into ``error`` (which carries no value)."""
    if _has_unsafe_characters(value):
        raise error
    try:
        parts = urlsplit(value)
        _ = parts.port  # raises on a non-numeric port; its message would echo the value
    except ValueError:
        raise error from None
    return parts


def normalize_database_url(url: str) -> str:
    """Validate a PostgreSQL URL and point it at the psycopg 3 driver.

    The error message never contains the URL: it may hold a password.

    >>> normalize_database_url("postgres://user@db.example.com:5432/app")
    'postgresql+psycopg://user@db.example.com:5432/app'
    """
    error = ValueError("must be a PostgreSQL URL like postgresql://user:password@host:5432/db")
    parts = _split_url(url, error)
    if parts.scheme not in _POSTGRES_SCHEMES or not parts.hostname or not parts.path.strip("/"):
        raise error
    return f"{DRIVER_SCHEME}://{url.split('://', 1)[1]}"


def _database_url(value: SecretStr) -> SecretStr:
    return SecretStr(normalize_database_url(value.get_secret_value()))


def _ascii_host(host: str) -> str | None:
    """``host`` as ``urlsplit`` gives it, written as ASCII DNS labels or an IP address.

    ``None`` when it is neither: commas, backslashes, underscores, empty labels.

    >>> _ascii_host("пошта.укр"), _ascii_host("::1"), _ascii_host("a,b.example.com")
    ('xn--80a1acn3a.xn--j1amh', '[::1]', None)
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return f"[{address}]" if address.version == 6 else str(address)
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    labels = ascii_host.split(".")
    return ascii_host if all(_DNS_LABEL.fullmatch(label) for label in labels) else None


def _site_address(value: str) -> str:
    """A site root such as ``https://site.example.com``; a trailing slash is dropped.

    The host comes out in lower case and ASCII (punycode): a ``Location`` header cannot
    carry other characters.

    >>> _site_address("https://Site.Example.com/")
    'https://site.example.com'
    >>> _site_address("https://site.example.com/?x=1")
    Traceback (most recent call last):
    ...
    ValueError: must be a site root: http(s) and host only, no path, query, fragment or login
    """
    if not value:
        return value
    error = ValueError(
        "must be a site root: http(s) and host only, no path, query, fragment or login"
    )
    parts = _split_url(value, error)
    if (
        parts.scheme not in _WEB_SCHEMES
        or not parts.hostname
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
        or "?" in value
        or "#" in value
        or parts.username is not None
        or parts.netloc.endswith(":")  # an empty port
        or "\\" in parts.netloc
        or "%" in parts.netloc
    ):
        raise error
    host = _ascii_host(parts.hostname)
    if host is None:
        raise error
    port = f":{parts.port}" if parts.port is not None else ""
    return f"{parts.scheme}://{host}{port}"


def _web_address(value: str) -> str:
    """Any absolute http(s) URL, kept as given.

    >>> _web_address("https://course.example.com/agentic?utm_source=site")
    'https://course.example.com/agentic?utm_source=site'
    """
    if not value:
        return value
    error = ValueError("must be an absolute http(s) URL")
    parts = _split_url(value, error)
    if parts.scheme not in _WEB_SCHEMES or not parts.hostname:
        raise error
    return value


def _email_address(value: str) -> str:
    if value and (not _EMAIL.fullmatch(value) or not value.isprintable()):
        raise ValueError("must be an email address like webinar@mail.example.com")
    return value


def _kyiv_local_time(value: datetime) -> datetime:
    """Local Europe/Kyiv wall time that occurs exactly once (not inside a clock change)."""
    if value.tzinfo is not None:
        raise ValueError("must be local Europe/Kyiv time without a UTC offset")
    first = value.replace(tzinfo=KYIV, fold=0).utcoffset()
    second = value.replace(tzinfo=KYIV, fold=1).utcoffset()
    if first != second:
        raise ValueError("does not exist or is ambiguous in Europe/Kyiv (clock change)")
    return value


def _long_secret(value: SecretStr) -> SecretStr:
    if len(value.get_secret_value()) < MIN_SECRET_LENGTH:
        raise ValueError(f"must be at least {MIN_SECRET_LENGTH} characters long")
    return value


def _webhook_secret(value: SecretStr) -> SecretStr:
    if not _WEBHOOK_SECRET.fullmatch(value.get_secret_value()):
        raise ValueError("must be 32–256 characters of A-Z a-z 0-9 _ - (Telegram's rule)")
    return value


def _matching(pattern: re.Pattern[str], message: str) -> AfterValidator:
    def check(value: str) -> str:
        if value and not pattern.fullmatch(value):
            raise ValueError(message)
        return value

    return AfterValidator(check)


DatabaseUrl = Annotated[SecretStr, AfterValidator(_database_url)]
SiteAddress = Annotated[str, AfterValidator(_site_address)]
WebAddress = Annotated[str, AfterValidator(_web_address)]
EmailAddress = Annotated[str, AfterValidator(_email_address)]
KyivLocalTime = Annotated[datetime, AfterValidator(_kyiv_local_time)]
LongSecret = Annotated[SecretStr, AfterValidator(_long_secret)]
WebhookSecret = Annotated[SecretStr, AfterValidator(_webhook_secret)]
MaterialsSlug = Annotated[
    str, _matching(_MATERIALS_SLUG, "must be 8–32 characters of A-Z a-z 0-9 _ -")
]
BotUsername = Annotated[
    str, _matching(_BOT_USERNAME, "must be the bot's username without @: A-Z a-z 0-9 _")
]
ChannelName = Annotated[str, _matching(_CHANNEL, "must be a public channel as @name")]


class DatabaseSettings(BaseSettings):
    """The only setting Alembic needs."""

    model_config = _ENV_CONFIG

    database_url: DatabaseUrl


class Settings(BaseSettings):
    """All settings of the site; field ``name`` is read from the variable ``NAME``.

    A field required only in normal operation has an empty default (``""`` or ``None``): the
    redirect stub runs without it. In normal operation the model check below makes it required,
    so code that runs only then (the slices) may rely on it.
    """

    model_config = _ENV_CONFIG

    database_url: DatabaseUrl
    redirect_base_url: SiteAddress = ""  # non-empty: every request but /healthz gets a 307
    indexing_enabled: bool = False  # off until launch: every response is noindex
    ga4_measurement_id: str = ""  # empty: no analytics and no automatic cookie banner
    turnstile_site_key: str = ""
    turnstile_secret_key: SecretStr | None = None
    turnstile_allowed_hostnames: Annotated[tuple[str, ...], NoDecode] = Field(default=())
    site_mode: SiteMode = "live"
    public_base_url: SiteAddress = ""
    event_start: KyivLocalTime | None = None
    event_end: KyivLocalTime | None = None
    lesson_start: KyivLocalTime | None = None
    lesson_end: KyivLocalTime | None = None
    stream_url: WebAddress = ""
    lesson_url: WebAddress = ""
    course_url: WebAddress = ""
    recording_youtube_id: str = ""
    resend_api_key: SecretStr | None = None
    sender_email: EmailAddress = ""
    unsubscribe_secret: LongSecret | None = None
    admin_token: LongSecret | None = None
    registration_allowlist: Annotated[tuple[str, ...], NoDecode] = Field(default=())
    telegram_bot_token: SecretStr | None = None
    telegram_bot_username: BotUsername = ""
    telegram_webhook_secret: WebhookSecret | None = None
    telegram_channel: ChannelName = ""
    telegram_admin_user_id: int | None = None  # the teacher's Telegram id; none: no admin commands
    materials_slug: MaterialsSlug = ""  # empty: the materials page answers 404
    llm_enabled: bool = False
    anthropic_api_key: SecretStr | None = None
    railway_git_commit_sha: str = ""

    @field_validator("turnstile_allowed_hostnames", mode="before")
    @classmethod
    def _split_hostnames(cls, value: object) -> object:
        if isinstance(value, str):
            # DNS names ignore case; Turnstile reports them in lower case.
            return tuple(item.strip().lower() for item in value.split(",") if item.strip())
        return value

    @field_validator("registration_allowlist", mode="before")
    @classmethod
    def _split_allowlist(cls, value: object) -> object:
        """Addresses as registration stores them: trimmed, lower case; never with ``+``."""
        if not isinstance(value, str):
            return value
        entries = tuple(item.strip().lower() for item in value.split(",") if item.strip())
        if any("+" in entry or not _EMAIL.fullmatch(entry) for entry in entries):
            raise ValueError("must be comma-separated addresses without + (variants are implied)")
        return entries

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        for start, end in (("event_start", "event_end"), ("lesson_start", "lesson_end")):
            first, last = getattr(self, start), getattr(self, end)
            if first is not None and last is not None and last <= first:
                raise ValueError(f"{end.upper()} must be later than {start.upper()}")
        problems = self._missing()
        if problems:
            summary = "; ".join(f"{name}: {reason}" for name, reason in problems)
            raise PydanticCustomError(_MISSING, summary, {"problems": problems})
        return self

    def _missing(self) -> tuple[tuple[str, str], ...]:
        """Required variables that are not set, as ``(NAME, reason)``."""
        if self.redirect_base_url:
            return ()  # the redirect stub: DATABASE_URL and REDIRECT_BASE_URL are enough
        missing = [(name, REQUIRED) for name in NORMAL_REQUIRED if not getattr(self, name)]
        if self.site_mode == "replay" and not self.recording_youtube_id:
            missing.append(("recording_youtube_id", f"{REQUIRED} (required in replay mode)"))
        bot = [name for name in BOT_GROUP if not getattr(self, name)]
        if len(bot) < len(BOT_GROUP):
            missing.extend((name, f"{REQUIRED} (the bot settings go together)") for name in bot)
        if self.llm_enabled and self.anthropic_api_key is None:
            missing.append(("anthropic_api_key", f"{REQUIRED} (required when LLM_ENABLED)"))
        return tuple((name.upper(), reason) for name, reason in missing)

    @property
    def commit_short(self) -> str:
        """Short commit hash of the deployed build, or an empty string."""
        return self.railway_git_commit_sha[:COMMIT_SHORT_LENGTH]


def _describe(error: ValidationError) -> str:
    """One line per problem: the variable and the reason, never its value."""
    lines: list[str] = []
    for item in error.errors(include_url=False, include_input=False):
        if item["type"] == _MISSING:
            problems: tuple[tuple[str, str], ...] = item.get("ctx", {})["problems"]
            lines.extend(f"  - {name}: {reason}" for name, reason in problems)
            continue
        name = ".".join(str(part) for part in item["loc"][:1]).upper()
        reason = REQUIRED if item["type"] == "missing" else item["msg"]
        lines.append(f"  - {name}: {reason}" if name else f"  - {reason}")
    return "\n".join(lines)


def _load[T: BaseSettings](cls: type[T]) -> T:
    try:
        return cls()
    except ValidationError as error:
        message = f"Invalid configuration (environment variables):\n{_describe(error)}"
    except SettingsSourceError:
        message = "Invalid configuration: an environment variable could not be parsed"
    raise ConfigError(message) from None


def load_settings() -> Settings:
    """Read and validate all settings; raise ``ConfigError`` without values on failure."""
    return _load(Settings)


def load_database_settings() -> DatabaseSettings:
    """Read only ``DATABASE_URL`` (for Alembic)."""
    return _load(DatabaseSettings)
