"""The form ``_form.html`` on ``/`` (requirements, sections 5 and 12; docs/copy.md, 1.8).

The partial is self-contained: it brings ``section#register``, the Turnstile widget and script
and its own script; the page includes it by name. Texts are the oracle's: copy.md 1.8 by mode,
the consent of docs/legal/consent.md word for word. Without JavaScript the form is a plain POST.
"""

import pytest
from fastapi.testclient import TestClient
from jinja2 import ChoiceLoader, DictLoader

from tests import copy_oracle as copy
from tests.conftest import REQUIRED_ENV
from tests.html_tree import Node, normalize, parse
from tests.markdown_text import LEGAL_DIR, plain
from tests.registration.conftest import ClientFactory

FORM = copy.section("1.8")
FIELDS = copy.table(FORM)
MODES = {"live": {}, "replay": {"SITE_MODE": "replay", "RECORDING_YOUTUBE_ID": "Rec0rding_ID"}}
# Explicit rendering: registration.js renders the widget, whichever script runs first.
TURNSTILE_SCRIPT = (
    "https://challenges.cloudflare.com/turnstile/v0/api.js"
    "?render=explicit&onload=registrationTurnstileLoad"
)
FORM_SCRIPT = "/static/js/registration.js"


def consent_text() -> str:
    markdown = (LEGAL_DIR / "consent.md").read_text(encoding="utf-8")
    return plain(markdown.split("## Текст позначки", 1)[1].split("\n## ", 1)[0])


def home(client: TestClient) -> Node:
    response = client.get("/")
    assert response.status_code == 200
    return parse(response.text)


def register_section(page: Node) -> Node:
    return page.find("main").find("section", id="register")


@pytest.mark.parametrize("mode", sorted(MODES))
def test_the_form_has_the_texts_of_its_mode(client_factory: ClientFactory, mode: str) -> None:
    other = "replay" if mode == "live" else "live"
    texts, foreign = copy.group(FORM, mode), copy.group(FORM, other)

    section = register_section(home(client_factory(**MODES[mode])))

    assert section.find("h2").text() == copy.one(texts, "Заголовок")
    assert copy.one(texts, "Вступ") in section.text()
    assert copy.one(foreign, "Вступ") not in section.text()


def test_the_fields_and_their_labels(client_factory: ClientFactory) -> None:
    section = register_section(home(client_factory()))
    form = section.find("form")

    email = form.find("input", name="email")
    assert email.attrs["type"] == "email"
    assert email.attrs["placeholder"] == FIELDS["Поле: підказка в полі"]
    assert email.attrs["value"] == ""
    assert FIELDS["Поле: підпис"] in form.find("label", class_="field").text()
    assert FIELDS["Поле: пояснення під полем"] in form.text()
    button = form.find("button", type="submit")
    assert button.text() == FIELDS["Кнопка"]
    assert button.attrs["data-busy-label"] == FIELDS["Кнопка під час надсилання"]
    assert "disabled" not in button.attrs  # without JavaScript the form still posts


def test_the_consent_is_the_legal_text_and_is_not_preset(client_factory: ClientFactory) -> None:
    form = register_section(home(client_factory())).find("form")

    checkbox = form.find("input", name="consent")
    assert checkbox.attrs["type"] == "checkbox"
    assert checkbox.attrs["value"] == "yes"
    assert "checked" not in checkbox.attrs
    label = checkbox.parent
    assert label is not None
    assert normalize(label.text()) == consent_text()
    assert [a.attrs["href"] for a in label.find_all("a")] == ["/privacy"]


def test_the_form_posts_with_and_without_javascript(client_factory: ClientFactory) -> None:
    form = register_section(home(client_factory())).find("form")

    assert (form.attrs["method"], form.attrs["action"]) == ("post", "/register#register")
    assert (form.attrs["hx-post"], form.attrs["hx-target"], form.attrs["hx-swap"]) == (
        "/register",
        "#register",
        "outerHTML",
    )
    assert form.find("input", name="ga_client_id").attrs == {
        "type": "hidden",
        "name": "ga_client_id",
        "value": "",
    }
    [alert] = [node for node in form.iter() if "data-network-error" in node.attrs]
    assert "hidden" in alert.attrs


def test_the_turnstile_widget_and_the_scripts_come_with_the_partial(
    client_factory: ClientFactory,
) -> None:
    page = home(client_factory())

    [widget] = page.find_all("div", class_="cf-turnstile")
    assert widget.attrs["data-sitekey"] == REQUIRED_ENV["TURNSTILE_SITE_KEY"]
    assert (widget.attrs["data-language"], widget.attrs["data-theme"]) == ("uk", "light")
    assert "data-callback" not in widget.attrs  # the script passes its callbacks to render()
    scripts = [s.attrs["src"] for s in page.find_all("script") if "src" in s.attrs]
    assert scripts.count(TURNSTILE_SCRIPT) == 1
    assert [s for s in scripts if s.startswith(FORM_SCRIPT)] == [FORM_SCRIPT]
    assert scripts.count("/static/js/htmx.min.js") == 1  # from base.html, not from the partial


def test_the_landing_includes_the_same_partial(client_factory: ClientFactory) -> None:
    client = client_factory()
    env = client.app.state.container.templates.env  # type: ignore[attr-defined]
    landing = (
        '{% extends "base.html" %}{% block main %}<h1>LANDING</h1>'
        '{% include "_form.html" ignore missing %}{% endblock %}'
    )
    env.loader = ChoiceLoader([DictLoader({"landing.html": landing}), env.loader])

    page = home(client)

    assert page.find("h1").text() == "LANDING"
    assert register_section(page).find("form").attrs["hx-post"] == "/register"


def test_the_form_and_its_script_are_served(client_factory: ClientFactory) -> None:
    client = client_factory()

    script = client.get(FORM_SCRIPT)
    styles = [link.attrs["href"] for link in home(client).find_all("link", rel="stylesheet")]

    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert "/static/css/registration.css" in styles


def test_without_the_slice_the_partial_shows_nothing(client_factory: ClientFactory) -> None:
    """The partial needs the slice's values; a page renders without them at any stage."""
    client = client_factory()
    client.app.state.container.templates.env.globals.pop("registration")  # type: ignore[attr-defined]

    page = home(client)

    assert page.find_all("form") == []
    assert page.find_all("section", id="register") == []
