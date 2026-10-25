"""The feature Ф1: the personal link, the cookie ``ref``, the invitation counted once."""

import re

from tests import copy_oracle as copy
from tests.conftest import ParticipantFactory
from tests.html_tree import parse
from tests.referral.conftest import BASE_URL, HTMX, Site

INVITER = "inviter@example.com"
GUEST = "guest@example.com"
REFERRAL = copy.section("12.1")


def code_of(site: Site, email: str) -> str:
    code = site.row(email).ref_code
    assert code is not None
    return code


def counter(html: str) -> str:
    return parse(html).find("p", class_="referral__count").text()


def test_the_code_is_made_once_and_never_changes(site: Site) -> None:
    site.register(INVITER)
    first = code_of(site, INVITER)
    site.register(INVITER)
    site.register(INVITER.upper())

    assert code_of(site, INVITER) == first
    assert re.fullmatch(r"[A-Za-z0-9_-]{8}", first)


def test_the_screen_shows_the_link_and_the_number(site: Site) -> None:
    html = site.register(INVITER)
    code = code_of(site, INVITER)
    node = parse(html)

    assert node.find("input", class_="referral__link").attrs["value"] == f"{BASE_URL}/?ref={code}"
    assert counter(html) == copy.one(REFERRAL, "Лічильник").replace("{referrals}", "0")


def test_the_texts_are_the_documents(site: Site) -> None:
    node = parse(site.register(INVITER))

    assert node.find("h3", class_="referral__title").text() == copy.one(REFERRAL, "Заголовок")
    assert node.find("p", class_="referral__intro").text() == copy.one(REFERRAL, "Текст")
    assert node.find("label").text() == copy.one(REFERRAL, "Підпис поля")
    button = node.find("button", class_="referral__copy")
    assert button.text() == copy.one(REFERRAL, "Кнопка")
    assert button.attrs["data-copied"] == copy.one(REFERRAL, "Кнопка після копіювання")


def test_a_new_address_with_the_cookie_is_counted_once(site: Site) -> None:
    site.register(INVITER)
    code = code_of(site, INVITER)

    site.register(GUEST, ref=code)
    site.register(GUEST, ref=code)

    assert site.row(GUEST).referred_by == site.row(INVITER).id
    assert counter(site.register(INVITER)).endswith(": 1")


def test_several_guests_are_counted_each(site: Site) -> None:
    site.register(INVITER)
    code = code_of(site, INVITER)
    for number in range(3):
        site.register(f"guest-{number}@example.com", ref=code)

    assert counter(site.register(INVITER)).endswith(": 3")


def test_a_known_address_is_not_counted(site: Site) -> None:
    site.register(INVITER)
    site.register("other@example.com")
    site.register(GUEST)
    site.register(GUEST, ref=code_of(site, INVITER))
    site.register(GUEST, ref=code_of(site, "other@example.com"))

    assert site.row(GUEST).referred_by is None
    assert counter(site.register(INVITER)).endswith(": 0")


def test_a_participant_of_v1_is_not_counted(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    site.register(INVITER)
    participant_factory(GUEST, origin=None)

    site.register(GUEST, ref=code_of(site, INVITER))

    assert site.row(GUEST).referred_by is None


def test_inviting_oneself_is_ignored(site: Site) -> None:
    site.register(INVITER)
    own = code_of(site, INVITER)

    html = site.register(INVITER, ref=own)

    assert site.row(INVITER).referred_by is None
    assert counter(html).endswith(": 0")


def test_an_unknown_or_damaged_code_is_ignored(site: Site) -> None:
    codes = ("Zz9_-Zz9", "x" * 500, "../../etc", "a b", "'; drop table participants; --", "")
    for number, code in enumerate(codes):
        email = f"guest-{number}@example.com"

        site.register(email, ref=code)

        assert site.row(email).referred_by is None


def test_the_part_shows_a_number_and_no_one_else(site: Site) -> None:
    site.register(INVITER)
    site.register("secret-name@example.com", ref=code_of(site, INVITER))

    html = site.register(INVITER)

    assert "secret-name" not in html
    assert counter(html).endswith(": 1")


def test_the_cookie_is_set_by_the_link(site: Site) -> None:
    site.register(INVITER)
    code = code_of(site, INVITER)
    site.client.cookies.clear()

    response = site.client.get(f"/?ref={code}")

    cookies = response.headers.get_list("set-cookie")
    cookie = next(line for line in cookies if line.startswith("ref="))
    assert cookie.startswith(f"ref={code};")
    assert "Max-Age=2592000" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie


def test_the_cookie_is_not_set_for_a_damaged_code_or_without_one(site: Site) -> None:
    for query in ("?ref=", "?ref=a%20b", "?ref=" + "x" * 40, "?ref=%3Cscript%3E", ""):
        site.client.cookies.clear()

        response = site.client.get(f"/{query}")

        assert response.status_code == 200
        cookies = response.headers.get_list("set-cookie")
        assert not [line for line in cookies if line.startswith("ref=")]


def test_the_cookie_of_the_link_registers_the_guest(site: Site) -> None:
    site.register(INVITER)
    code = code_of(site, INVITER)
    site.client.cookies.clear()
    site.client.get(f"/?ref={code}")  # the browser keeps the cookie

    site.client.post(
        "/register",
        data={"email": GUEST, "consent": "yes", "cf-turnstile-response": "tok"},
        headers=HTMX,
    )

    assert site.row(GUEST).referred_by == site.row(INVITER).id


def test_the_block_is_absent_where_the_registration_was_refused(site: Site) -> None:
    response = site.client.post("/register", data={"email": "", "consent": "yes"}, headers=HTMX)

    assert "referral" not in response.text
