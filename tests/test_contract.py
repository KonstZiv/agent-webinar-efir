"""The template's part of docs/contract.md: what v2 keeps to replace v1 at the same addresses.

The tables, the reference token, the lead cookie and the stage are read from the contract
itself, so the document and the code cannot drift apart. The checks cover names and presence:
variables, routes, the token module, the token prefix and the lead cookie. Behaviour is checked
by the tests of the slices.

A row marked «ні» is owed by a v2 slice and is checked as well: the template must not have it
yet, so the slice that adds it has to update the contract. At the stage «запуск» every row
marked «ні» fails, and so does a script without the contract's lead cookie line. Nothing is
skipped, and nothing from the contract is read while tests are collected: a missing or broken
contract fails these tests, not the whole run.
"""

import base64
import hashlib
import hmac
import importlib
import importlib.util
import re
import sys
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

from app.adapters.web import token_paths
from app.adapters.web.dependencies import STATIC_DIR
from app.adapters.web.routers.health import HEALTH_PATH
from app.adapters.web.token_paths import carries_token
from app.main import create_app
from app.settings import Settings
from tests.conftest import SettingsFactory
from tests.fakes import FakeDatabaseProbe
from tests.markdown_text import table_rows

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "contract.md"
ENV_EXAMPLE = ROOT / "docs" / "env.example"
CONSENT_JS = STATIC_DIR / "js" / "consent.js"

PRESENT, OWED = "так", "ні"
DEVELOPMENT, LAUNCH = "розробка", "запуск"
# Railway sets PORT for the Procfile; Settings never reads it.
SET_BY_PLATFORM = frozenset({"PORT"})
PLAN_PREFIX = "APP_"
# No route for the path (404) or none for the method (405).
NOT_SERVED = frozenset({404, 405})
# The unsubscribe route answers 400 to a token it cannot verify.
TOKEN_REJECTED = 400
UNSUBSCRIBE_PATH = "/unsubscribe/{token}"

BASE = "https://v2.example.com"
CLICK_QUERY = "utm_source=contract&gclid=contract"
ONE_CLICK_BODY = b"List-Unsubscribe=One-Click"
TOKEN_FORMAT = re.compile(r"[0-9a-f]{32}\.[A-Za-z0-9_-]{43}", re.ASCII)
TOKEN_LENGTH = 76

# Status code of a request ``(method, path)`` to the application under test.
type Probe = Callable[[str, str], int]


@dataclass(frozen=True, slots=True)
class Row:
    """One row of a contract table: a variable or a path, and whether the template has it."""

    name: str
    status: str
    methods: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class TokenExample:
    secret: str
    unsubscribe_id: uuid.UUID
    token: str


# --- reading the contract ------------------------------------------------------------------


def section(markdown: str, title: str) -> str:
    """Text of the section ``## [N. ]title`` up to the next ``## `` heading."""
    pattern = rf"^## (?:\d+\. )?{re.escape(title)}\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, markdown, re.MULTILINE | re.DOTALL)
    if match is None:
        raise LookupError(f"docs/contract.md has no section «{title}»")
    return match.group(1)


def status_of(cell: str) -> str:
    """«так» or «ні» from the start of a cell or an item; anything else is a mistake."""
    words = cell.split()
    if not words or words[0] not in (PRESENT, OWED):
        raise ValueError(f"status must start with «{PRESENT}» or «{OWED}»: {cell!r}")
    return words[0]


def rows_of(text: str, *, name: int, status: int, methods: int | None = None) -> list[Row]:
    """Rows of the only table in ``text``; an empty table would make every check vacuous."""
    rows = [
        Row(
            name=cells[name],
            status=status_of(cells[status]),
            methods=frozenset()
            if methods is None
            else frozenset(method.strip() for method in cells[methods].split(",")),
        )
        for cells in table_rows(text)
    ]
    if not rows:
        raise LookupError("the contract table has no rows")
    return rows


def item(text: str, label: str) -> str:
    """The value of the first list item ``- <label>…: <value>``."""
    match = re.search(rf"^- {re.escape(label)}[^:\n]*: (.+)$", text, re.MULTILINE)
    if match is None:
        raise LookupError(f"docs/contract.md has no item «{label}»")
    return match.group(1)


def code_item(text: str, label: str) -> str:
    """The value of the item ``- <label>…: `value```."""
    match = re.fullmatch(r"`([^`]+)`", item(text, label))
    if match is None:
        raise LookupError(f"the item «{label}» must hold a single `code` value")
    return match.group(1)


def stage_of(markdown: str) -> str:
    """The stage from the line ``Етап: `розробка` …`` (or ``запуск``)."""
    match = re.search(r"^Етап: `([^`]+)`", markdown, re.MULTILINE)
    if match is None:
        raise LookupError("docs/contract.md has no line «Етап: `…`»")
    if match.group(1) not in (DEVELOPMENT, LAUNCH):
        raise ValueError(f"the stage must be «{DEVELOPMENT}» or «{LAUNCH}»: {match.group(1)!r}")
    return match.group(1)


@cache
def contract() -> str:
    if not CONTRACT.exists():
        pytest.fail(
            "docs/contract.md is missing: write the project's own contract, or delete "
            "tests/test_contract.py together with it (README, «Як почати проєкт»)",
            pytrace=False,
        )
    return CONTRACT.read_text(encoding="utf-8")


@cache
def variable_rows() -> list[Row]:
    return rows_of(section(contract(), "Змінні середовища"), name=0, status=1)


@cache
def path_rows() -> list[Row]:
    return rows_of(section(contract(), "Спільні шляхи"), name=0, status=2, methods=1)


@cache
def reference_token() -> TokenExample:
    text = section(contract(), "Токен відписки")
    return TokenExample(
        secret=code_item(text, "секрет"),
        unsubscribe_id=uuid.UUID(code_item(text, "`unsubscribe_id`")),
        token=code_item(text, "токен"),
    )


def token_module() -> str:
    return code_item(section(contract(), "Токен відписки"), "модуль у v2")


def unsubscribe_status() -> str:
    for row in path_rows():
        if row.name == UNSUBSCRIBE_PATH:
            return row.status
    raise LookupError(f"the table of shared paths has no row {UNSUBSCRIBE_PATH}")


def lead_cookie() -> tuple[str, str]:
    """The cookie line of the contract and whether the template sets it."""
    text = section(contract(), "Cookie `webinar_lead`")
    return code_item(text, "рядок cookie"), status_of(item(text, "у шаблоні"))


def concrete(path: str) -> str:
    """A shared path as an old link carries it: ``{token}`` is the reference token."""
    result = path.replace("{token}", reference_token().token)
    assert "{" not in result, f"no sample value for the parameters of {path}"
    return result


# --- the checks ----------------------------------------------------------------------------


def settings_names() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


def env_example_names() -> set[str]:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    return {line.split("=", 1)[0] for line in lines if re.match(r"^[A-Z][A-Z0-9_]*=", line)}


def aliased_fields(settings: type[BaseSettings]) -> list[str]:
    """Fields read from a variable other than their own name (``alias``, ``validation_alias``)."""
    return [
        name
        for name, field in settings.model_fields.items()
        if field.alias is not None or field.validation_alias is not None
    ]


def missing_variables(rows: list[Row], settings: set[str], listed: set[str]) -> list[str]:
    """Variables marked «так» that ``Settings`` does not read or ``env.example`` does not list."""
    return [
        row.name
        for row in rows
        if row.status == PRESENT
        and (row.name not in listed or row.name not in settings | SET_BY_PLATFORM)
    ]


def premature_variables(rows: list[Row], settings: set[str], listed: set[str]) -> list[str]:
    """Variables marked «ні» that the template already has: the contract must be updated."""
    return [
        row.name
        for row in rows
        if row.status == OWED and (row.name in settings or row.name in listed)
    ]


def missing_paths(rows: list[Row], probe: Probe) -> list[str]:
    """Paths marked «так» that do not answer every method the contract names."""
    return [
        row.name
        for row in rows
        if row.status == PRESENT
        and any(probe(method, concrete(row.name)) in NOT_SERVED for method in sorted(row.methods))
    ]


def premature_paths(rows: list[Row], probe: Probe) -> list[str]:
    """Paths marked «ні» that the template already serves: the contract must be updated."""
    return [
        row.name
        for row in rows
        if row.status == OWED
        and any(probe(method, concrete(row.name)) != 404 for method in sorted(row.methods))
    ]


def owed_at_launch(stage: str, rows: list[Row]) -> list[str]:
    """At the stage «запуск» every row marked «ні» is a debt v2 must not launch with."""
    if stage not in (DEVELOPMENT, LAUNCH):
        raise ValueError(f"unknown stage {stage!r}")
    return [row.name for row in rows if row.status == OWED] if stage == LAUNCH else []


def misplaced_token_paths(rows: list[Row], prefixes: tuple[str, ...]) -> list[str]:
    """Rows with ``{token}``: under a token prefix exactly when marked «так».

    The prefix keeps the token out of the access log and Google Analytics.
    """
    return [
        row.name
        for row in rows
        if "{token}" in row.name
        and carries_token(concrete(row.name), prefixes) != (row.status == PRESENT)
    ]


def rejected_reference_tokens(rows: list[Row], probe: Probe) -> list[str]:
    """Rows with ``{token}`` marked «так» whose GET rejects the reference token."""
    return [
        row.name
        for row in rows
        if "{token}" in row.name
        and row.status == PRESENT
        and probe("GET", concrete(row.name)) == TOKEN_REJECTED
    ]


def cookie_owed_at_launch(stage: str, cookie: str, script: str) -> list[str]:
    """At the stage «запуск» the script sets the contract's cookie line, whatever its mark."""
    if stage not in (DEVELOPMENT, LAUNCH):
        raise ValueError(f"unknown stage {stage!r}")
    if stage == LAUNCH and cookie not in script:
        return [f"the stage is «запуск», but consent.js does not set «{cookie}»"]
    return []


def lead_cookie_problems(status: str, cookie: str, script: str) -> list[str]:
    """«ні»: the script has no such cookie yet; «так»: it sets exactly the contract's line."""
    name = cookie.split("=", 1)[0]
    if status == OWED:
        if name in script:
            return [f"consent.js has {name}: mark it «так» in docs/contract.md"]
        return []
    return [] if cookie in script else [f"consent.js does not set exactly «{cookie}»"]


def token_module_problems(status: str, module_name: str, example: TokenExample) -> list[str]:
    """«ні»: the module does not exist yet; «так»: it reproduces the reference token."""
    try:
        found = importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:  # a parent package is missing
        found = False
    if status == OWED:
        if found:
            return [f"{module_name} exists: mark {UNSUBSCRIBE_PATH} «так» in docs/contract.md"]
        return []
    if not found:
        return [f"{module_name} is missing"]
    module = importlib.import_module(module_name)
    make_token = getattr(module, "make_token", None)
    read_token = getattr(module, "read_token", None)
    if not callable(make_token) or not callable(read_token):
        return [f"{module_name} must define make_token and read_token"]
    problems = []
    if make_token(example.unsubscribe_id, example.secret) != example.token:
        problems.append("make_token does not give the reference token")
    if read_token(example.token, example.secret) != example.unsubscribe_id:
        problems.append("read_token does not accept the reference token")
    if read_token(example.token, example.secret + "x") is not None:
        problems.append("read_token accepts the reference token with another secret")
    return problems


def contract_token(unsubscribe_id: uuid.UUID, secret: str) -> str:
    """The token as docs/contract.md describes it, written independently of any implementation."""
    hex_id = unsubscribe_id.hex
    message = f"unsubscribe:{hex_id}".encode("ascii")
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return f"{hex_id}.{base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')}"


def follows_the_format(example: TokenExample) -> bool:
    token = example.token
    return (
        len(token) == TOKEN_LENGTH
        and TOKEN_FORMAT.fullmatch(token) is not None
        and token == contract_token(example.unsubscribe_id, example.secret)
    )


def redirected_requests() -> list[tuple[str, str]]:
    return [
        (row.name, method)
        for row in path_rows()
        if row.name != HEALTH_PATH
        for method in sorted(row.methods)
    ]


# --- fixtures ------------------------------------------------------------------------------


@pytest.fixture
def probe(make_settings: SettingsFactory) -> Iterator[Probe]:
    """The template app; ``UNSUBSCRIBE_SECRET`` is the reference secret once v2 reads it."""
    settings = make_settings(UNSUBSCRIBE_SECRET=reference_token().secret)
    app = create_app(settings, db_probe=FakeDatabaseProbe())
    with TestClient(app, follow_redirects=False) as client:
        yield lambda method, path: client.request(method, path).status_code


@pytest.fixture
def redirecting(make_settings: SettingsFactory) -> Iterator[TestClient]:
    app = create_app(make_settings(REDIRECT_BASE_URL=BASE), db_probe=FakeDatabaseProbe())
    with TestClient(app, follow_redirects=False) as client:
        yield client


@pytest.fixture
def synthetic_probe() -> Iterator[Probe]:
    """A tiny app: GET-only, a parameter route, a token route that accepts and one that rejects."""
    app = FastAPI()
    app.add_api_route("/get-only", lambda: None, methods=["GET"])
    app.add_api_route("/u/{key}", lambda key: key, methods=["GET"])
    app.add_api_route("/ok/{token}", lambda token: Response(status_code=200), methods=["GET"])
    app.add_api_route("/bad/{token}", lambda token: Response(status_code=400), methods=["GET"])
    with TestClient(app) as client:
        yield lambda method, path: client.request(method, path).status_code


# --- the contract file and the stage -------------------------------------------------------


def test_missing_contract_fails_with_a_clear_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.modules[__name__], "CONTRACT", tmp_path / "contract.md")
    contract.cache_clear()
    try:
        with pytest.raises(pytest.fail.Exception, match="Як почати проєкт"):
            contract()
    finally:
        contract.cache_clear()


def test_nothing_is_owed_at_launch() -> None:
    owed = owed_at_launch(stage_of(contract()), variable_rows() + path_rows())
    assert owed == [], "the stage is «запуск», but v2 still owes these rows"


def test_launch_stage_turns_owed_rows_into_failures() -> None:
    rows = [Row("DONE", PRESENT), Row("LATER", OWED), Row("/later", OWED)]

    assert owed_at_launch(DEVELOPMENT, rows) == []
    assert owed_at_launch(LAUNCH, rows) == ["LATER", "/later"]
    assert owed_at_launch(LAUNCH, [Row("DONE", PRESENT)]) == []
    with pytest.raises(ValueError, match="готово"):
        owed_at_launch("готово", rows)


def test_stage_line_is_read() -> None:
    assert stage_of("# K\n\nЕтап: `розробка`. Значення…\n") == DEVELOPMENT
    assert stage_of("Етап: `запуск`.\n") == LAUNCH
    with pytest.raises(ValueError, match="готово"):
        stage_of("Етап: `готово`.\n")
    with pytest.raises(LookupError):
        stage_of("# K\n\nбез етапу\n")


# --- environment variables -----------------------------------------------------------------


def test_variables_have_no_prefix() -> None:
    """``APP_X`` in the plan is ``X`` here: pydantic-settings reads field names as they are."""
    assert not Settings.model_config.get("env_prefix")
    names = settings_names() | env_example_names() | {row.name for row in variable_rows()}
    assert sorted(name for name in names if name.startswith(PLAN_PREFIX)) == []


def test_settings_fields_have_no_alias() -> None:
    """An alias would read another variable (``APP_X``) than the field name the tests see."""
    assert aliased_fields(Settings) == []


def test_alias_check_finds_aliased_fields() -> None:
    class Aliased(BaseSettings):
        plain: str = ""
        renamed: str = Field(default="", validation_alias="APP_RENAMED")
        either: str = Field(default="", validation_alias=AliasChoices("EITHER", "APP_EITHER"))
        aliased: str = Field(default="", alias="APP_ALIASED")

    assert aliased_fields(Aliased) == ["renamed", "either", "aliased"]


def test_template_variables_are_read_and_listed() -> None:
    assert missing_variables(variable_rows(), settings_names(), env_example_names()) == []


def test_variables_owed_by_v2_are_absent() -> None:
    premature = premature_variables(variable_rows(), settings_names(), env_example_names())
    assert premature == [], "the template has them now: mark them «так» in docs/contract.md"


def test_variable_checks_find_gaps_both_ways() -> None:
    rows = [
        Row("LISTED", PRESENT),
        Row("UNLISTED", PRESENT),
        Row("NOT_READ", PRESENT),
        Row("PORT", PRESENT),
        Row("EARLY", OWED),
        Row("LATER", OWED),
    ]
    settings = {"LISTED", "UNLISTED", "EARLY"}
    listed = {"LISTED", "NOT_READ", "PORT"}

    assert missing_variables(rows, settings, listed) == ["UNLISTED", "NOT_READ"]
    assert premature_variables(rows, settings, listed) == ["EARLY"]


# --- shared paths --------------------------------------------------------------------------


def test_template_paths_are_served(probe: Probe) -> None:
    assert missing_paths(path_rows(), probe) == []


def test_paths_owed_by_v2_are_not_served_yet(probe: Probe) -> None:
    premature = premature_paths(path_rows(), probe)
    assert premature == [], "the template serves them now: mark them «так» in docs/contract.md"


def test_path_checks_find_gaps_both_ways(synthetic_probe: Probe) -> None:
    rows = [
        Row("/get-only", PRESENT, frozenset({"GET", "POST"})),
        Row("/absent", PRESENT, frozenset({"GET"})),
        Row("/u/{token}", OWED, frozenset({"GET"})),
        Row("/later", OWED, frozenset({"GET"})),
    ]

    assert missing_paths(rows, synthetic_probe) == ["/get-only", "/absent"]
    assert premature_paths(rows, synthetic_probe) == ["/u/{token}"]


def test_unknown_status_is_rejected() -> None:
    table = "| Шлях | Методи | У шаблоні |\n| :-- | :-- | :-- |\n| `/x` | GET | можливо |\n"

    with pytest.raises(ValueError, match="можливо"):
        rows_of(table, name=0, status=2, methods=1)


def test_empty_table_is_rejected() -> None:
    with pytest.raises(LookupError):
        rows_of("| Змінна | У шаблоні |\n| :-- | :-- |\n", name=0, status=1)


def test_token_paths_sit_under_a_token_prefix_once_served() -> None:
    assert misplaced_token_paths(path_rows(), token_paths.TOKEN_PATH_PREFIXES) == []


def test_token_prefix_check_finds_both_mistakes() -> None:
    rows = [
        Row("/t/{token}", PRESENT),
        Row("/open/{token}", PRESENT),
        Row("/early/{token}", OWED),
        Row("/later/{token}", OWED),
        Row("/plain", PRESENT),
    ]

    assert misplaced_token_paths(rows, ("/t/", "/early/")) == ["/open/{token}", "/early/{token}"]


def test_served_token_paths_accept_the_reference_token(probe: Probe) -> None:
    assert rejected_reference_tokens(path_rows(), probe) == []


def test_reference_token_check_finds_a_rejecting_route(synthetic_probe: Probe) -> None:
    rows = [
        Row("/ok/{token}", PRESENT),
        Row("/bad/{token}", PRESENT),
        Row("/bad/{token}", OWED),
    ]

    assert rejected_reference_tokens(rows, synthetic_probe) == ["/bad/{token}"]


# --- redirect rule -------------------------------------------------------------------------


def test_shared_paths_survive_the_redirect(redirecting: TestClient) -> None:
    """Old links keep their path and parameters; POST (one-click unsubscribe) keeps its body."""
    wrong = []
    for path, method in redirected_requests():
        target = f"{concrete(path)}?{CLICK_QUERY}"
        body = ONE_CLICK_BODY if method == "POST" else None
        headers = {"content-type": "application/x-www-form-urlencoded"} if body else None

        response = redirecting.request(method, target, content=body, headers=headers)

        answer = (
            response.status_code,
            response.headers.get("location"),
            response.headers.get("cache-control"),
        )
        if answer != (307, BASE + target, "no-store"):
            wrong.append(f"{method} {path}: {answer}")

    assert wrong == []


def test_health_path_is_shared_and_never_redirected(redirecting: TestClient) -> None:
    assert HEALTH_PATH in {row.name for row in path_rows()}

    response = redirecting.get(HEALTH_PATH)

    assert response.status_code == 200
    assert "location" not in response.headers


# --- unsubscribe token ---------------------------------------------------------------------


def test_reference_token_follows_the_format() -> None:
    """The example in the contract was computed by v1's ``make_token``."""
    assert follows_the_format(reference_token())


def test_format_check_rejects_forged_examples() -> None:
    example = reference_token()
    last = "B" if example.token.endswith("A") else "A"
    other_id = uuid.UUID(int=example.unsubscribe_id.int ^ 1)
    forged = [
        TokenExample(example.secret, example.unsubscribe_id, example.token[:-1] + last),
        TokenExample(example.secret + "x", example.unsubscribe_id, example.token),
        TokenExample(example.secret, other_id, example.token),
        TokenExample(example.secret, example.unsubscribe_id, example.token.upper()),
        TokenExample(example.secret, example.unsubscribe_id, example.token + "="),
    ]

    assert [follows_the_format(item) for item in forged] == [False] * len(forged)


def test_token_module_follows_the_contract() -> None:
    """Until the row is «так» the module must not exist; then it reproduces the reference."""
    problems = token_module_problems(unsubscribe_status(), token_module(), reference_token())
    assert problems == []


_TOKENS = """
import base64, hashlib, hmac, uuid


def _sig(hex_id, secret):
    digest = hmac.new(secret.encode(), f"unsubscribe:{hex_id}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def make_token(unsubscribe_id, secret):
    return f"{unsubscribe_id.hex}.{_sig(unsubscribe_id.hex, secret)}"
"""
_STRICT_READ = """

def read_token(token, secret):
    hex_id, _, sig = token.partition(".")
    return uuid.UUID(hex=hex_id) if hmac.compare_digest(sig, _sig(hex_id, secret)) else None
"""
_LAX_READ = """

def read_token(token, secret):
    return uuid.UUID(hex=token.partition(".")[0])
"""
_WRONG_MAKE = """

def make_token(unsubscribe_id, secret):
    return f"{unsubscribe_id}.{_sig(str(unsubscribe_id), secret)}"
"""


def test_token_module_check_on_synthetic_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    modules = {
        "contract_tokens_good": _TOKENS + _STRICT_READ,
        "contract_tokens_lax": _TOKENS + _LAX_READ,
        "contract_tokens_wrong": _TOKENS + _STRICT_READ + _WRONG_MAKE,
        "contract_tokens_partial": _TOKENS,
    }
    for name, source in modules.items():
        (tmp_path / f"{name}.py").write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    example = reference_token()

    try:
        assert token_module_problems(OWED, "contract_tokens_absent", example) == []
        assert token_module_problems(OWED, "absent_package.unsubscribe", example) == []
        assert token_module_problems(OWED, "contract_tokens_good", example) == [
            f"contract_tokens_good exists: mark {UNSUBSCRIBE_PATH} «так» in docs/contract.md"
        ]
        assert token_module_problems(PRESENT, "contract_tokens_absent", example) == [
            "contract_tokens_absent is missing"
        ]
        assert token_module_problems(PRESENT, "contract_tokens_good", example) == []
        assert token_module_problems(PRESENT, "contract_tokens_lax", example) == [
            "read_token accepts the reference token with another secret"
        ]
        assert token_module_problems(PRESENT, "contract_tokens_wrong", example) == [
            "make_token does not give the reference token"
        ]
        assert token_module_problems(PRESENT, "contract_tokens_partial", example) == [
            "contract_tokens_partial must define make_token and read_token"
        ]
    finally:
        for name in modules:
            sys.modules.pop(name, None)


# --- lead cookie ---------------------------------------------------------------------------


def test_lead_cookie_follows_the_contract() -> None:
    cookie, status = lead_cookie()
    script = CONSENT_JS.read_text(encoding="utf-8")

    assert lead_cookie_problems(status, cookie, script) == []


def test_lead_cookie_check_on_synthetic_scripts() -> None:
    cookie = "lead=1; Domain=.example.com; Path=/; Max-Age=31536000; Secure; SameSite=Lax"
    exact = f'const LEAD_COOKIE =\n  "{cookie}";\n'
    shorter = 'const LEAD_COOKIE = "lead=1; Path=/";\n'

    assert lead_cookie_problems(OWED, cookie, "const STORAGE_KEY = 1;") == []
    assert lead_cookie_problems(OWED, cookie, exact) == [
        "consent.js has lead: mark it «так» in docs/contract.md"
    ]
    assert lead_cookie_problems(PRESENT, cookie, exact) == []
    assert lead_cookie_problems(PRESENT, cookie, shorter) == [
        f"consent.js does not set exactly «{cookie}»"
    ]
    assert lead_cookie_problems(PRESENT, cookie, "") == [
        f"consent.js does not set exactly «{cookie}»"
    ]


def test_lead_cookie_is_set_at_launch() -> None:
    cookie, _ = lead_cookie()
    script = CONSENT_JS.read_text(encoding="utf-8")

    assert cookie_owed_at_launch(stage_of(contract()), cookie, script) == []


def test_launch_stage_requires_the_lead_cookie() -> None:
    cookie = "lead=1; Domain=.example.com; Path=/; Max-Age=31536000; Secure; SameSite=Lax"
    exact = f'const LEAD_COOKIE =\n  "{cookie}";\n'
    shorter = 'const LEAD_COOKIE = "lead=1; Path=/";\n'
    owed = [f"the stage is «запуск», but consent.js does not set «{cookie}»"]

    assert cookie_owed_at_launch(DEVELOPMENT, cookie, "") == []
    assert cookie_owed_at_launch(LAUNCH, cookie, exact) == []
    assert cookie_owed_at_launch(LAUNCH, cookie, shorter) == owed
    assert cookie_owed_at_launch(LAUNCH, cookie, "") == owed
    with pytest.raises(ValueError, match="готово"):
        cookie_owed_at_launch("готово", cookie, exact)
