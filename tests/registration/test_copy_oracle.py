"""Text oracle of the success screen (docs/copy.md, section 2; requirements, section 16).

The oracle reads copy.md itself: in each mode, with a bot and without one, the screen shows
every text of its group and none that only the other mode has. The form, the letter, the pages
«the link will appear» and the unsubscribe pages have their oracles in test_form.py,
test_letter.py, test_links.py and test_unsubscribe.py.
"""

import pytest

from tests import copy_oracle as copy
from tests.conftest import BOT_ENV
from tests.html_tree import Node, parse
from tests.registration.conftest import SiteFactory
from tests.registration.helpers import EMAIL

SCREEN = copy.section("2")
MODES = {"live": {}, "replay": {"SITE_MODE": "replay", "RECORDING_YOUTUBE_ID": "Rec0rding_ID"}}
OTHER = {"live": "replay", "replay": "live"}


def lines(group: str) -> list[str]:
    """Every text of a group of section 2, ``{email}`` filled in; the player is not text."""
    texts = copy.group(SCREEN, group)
    found = []
    for label in ("Заголовок", "Текст", "Підказка", "Кнопка", "Посилання"):
        try:
            found += copy.labeled(texts, label)
        except AssertionError:  # the group has no such label
            continue
    return [text.replace("{email}", EMAIL) for text in found]


def screen(site_factory: SiteFactory, mode: str, *, bot: bool) -> Node:
    site = site_factory(**MODES[mode], **(BOT_ENV if bot else {}))
    response = site.register()
    assert response.status_code == 200
    return parse(response.text).find("section", id="register")


@pytest.mark.parametrize("bot", [True, False], ids=["bot", "no-bot"])
@pytest.mark.parametrize("mode", sorted(MODES))
def test_the_screen_shows_the_texts_of_its_mode_and_bot(
    site_factory: SiteFactory, mode: str, bot: bool
) -> None:
    shown = screen(site_factory, mode, bot=bot).text()

    expected = lines(mode) + lines("Бот" if bot else "Без бота")
    assert [text for text in expected if text not in shown] == []
    # Texts only the other mode has; «Ви зареєстровані» is a part of replay's own title.
    foreign = [text for text in lines(OTHER[mode]) if not any(text in own for own in expected)]
    assert [text for text in foreign if text in shown] == []
    absent = lines("Без бота" if bot else "Бот")
    assert [text for text in absent if text in shown] == []
    assert [text for text in lines("Адреса не зі списку дозволених") if text in shown] == []


def test_the_notice_of_the_staging_site(site_factory: SiteFactory) -> None:
    site = site_factory(REGISTRATION_ALLOWLIST="tester@example.com")

    shown = parse(site.register().text).find("section", id="register").text()

    assert [text for text in lines("Адреса не зі списку дозволених") if text not in shown] == []
    assert [text for text in lines("live") if text in shown] == []
