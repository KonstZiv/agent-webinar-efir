"""``POST /admin/checkins`` with the bot: the post in the channel, ``posted``, 409 (9а, part 3).

The bot is in the application (its settings are set, the messenger is a fake): the slice «відмітка
присутності» finds the post by the key ``bot.checkin_post`` and imports nothing of the bot.
"""

import logging
from collections.abc import Callable, Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.main import create_app
from tests import copy_oracle as copy
from tests.checkin.conftest import Site
from tests.checkin.helpers import GROUP, LESSON
from tests.conftest import BOT_ENV, SettingsFactory
from tests.fakes import FakeDatabaseProbe, FakeMessenger, FixedClock, fake_overrides

POST_SECTION = copy.section("14.3", copy.raw_copy_text())
POST_TEXT = copy.one(POST_SECTION, "Текст")
POST_BUTTON = copy.one(POST_SECTION, "Кнопка")

type BotSiteFactory = Callable[[FakeMessenger], tuple[Site, FakeMessenger]]


@pytest.fixture
def bot_site_factory(
    make_settings: SettingsFactory, test_db_url: str, migrated_engine: Engine
) -> Iterator[BotSiteFactory]:
    clients: list[TestClient] = []

    def build(messenger: FakeMessenger) -> tuple[Site, FakeMessenger]:
        clock = FixedClock()
        app = create_app(
            make_settings(DATABASE_URL=test_db_url, **BOT_ENV),
            db_probe=FakeDatabaseProbe(),
            overrides=fake_overrides(clock=clock, messenger=messenger),
        )
        client = TestClient(app, base_url="https://testserver")
        client.__enter__()
        clients.append(client)
        return Site(client, migrated_engine, clock), messenger

    yield build
    for client in clients:
        client.__exit__(None, None, None)


def post_text(group: str, window: int) -> str:
    return POST_TEXT.replace("{group}", group).replace("{window}", str(window))


def test_open_without_minutes_is_ten_minutes_and_posts_once(
    bot_site_factory: BotSiteFactory,
) -> None:
    site, messenger = bot_site_factory(FakeMessenger())

    response = site.admin_post("/admin/checkins", {"lesson_date": LESSON, "group": GROUP})

    body = response.json()
    assert response.status_code == 201 and body["posted"] is True
    [row] = site.checkins()
    assert row.closes_at - row.opened_at == timedelta(minutes=10)
    [sent] = messenger.sent
    assert sent.chat_id == BOT_ENV["TELEGRAM_CHANNEL"]
    assert sent.text == post_text(GROUP, 10)
    [[button]] = sent.buttons
    assert button.text == POST_BUTTON
    assert button.url == f"https://t.me/{BOT_ENV['TELEGRAM_BOT_USERNAME']}?start=checkin"
    assert button.callback_data is None
    assert body["code"] not in sent.text


def test_the_post_names_the_window_that_was_asked_for(bot_site_factory: BotSiteFactory) -> None:
    site, messenger = bot_site_factory(FakeMessenger())

    body = {"lesson_date": LESSON, "group": GROUP, "window_minutes": 45}
    site.admin_post("/admin/checkins", body)

    assert [message.text for message in messenger.sent] == [post_text(GROUP, 45)]


def test_when_telegram_refuses_the_check_in_stands_and_posted_is_false(
    bot_site_factory: BotSiteFactory, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    site, messenger = bot_site_factory(FakeMessenger(unavailable=True))

    response = site.admin_post("/admin/checkins", {"lesson_date": LESSON, "group": GROUP})

    body = response.json()
    assert response.status_code == 201 and body["posted"] is False
    assert [row.code for row in site.checkins()] == [body["code"]]
    assert messenger.sent == []
    log = "\n".join(record.getMessage() for record in caplog.records)
    assert "MessengerUnavailable" in log
    assert body["code"] not in log and GROUP not in log


def test_without_the_bot_posted_is_null(site: Site) -> None:
    response = site.admin_post("/admin/checkins", {"lesson_date": LESSON, "group": GROUP})

    assert response.status_code == 201 and response.json()["posted"] is None


def test_a_second_open_of_a_group_is_409_with_the_open_one_and_no_second_post(
    bot_site_factory: BotSiteFactory,
) -> None:
    site, messenger = bot_site_factory(FakeMessenger())
    first = site.admin_post("/admin/checkins", {"lesson_date": LESSON, "group": GROUP}).json()

    second = site.admin_post("/admin/checkins", {"lesson_date": LESSON, "group": GROUP})

    assert second.status_code == 409
    body = second.json()
    assert body["status"] == "open_exists"
    assert {key: body[key] for key in first if key != "posted"} == {
        key: value for key, value in first.items() if key != "posted"
    }
    assert len(site.checkins()) == 1
    assert len(messenger.sent) == 1


def test_a_group_without_a_name_is_one_group_for_the_rule(
    bot_site_factory: BotSiteFactory,
) -> None:
    site, _ = bot_site_factory(FakeMessenger())
    assert site.admin_post("/admin/checkins", {"lesson_date": LESSON}).status_code == 201

    again = site.admin_post("/admin/checkins", {"lesson_date": LESSON})

    assert again.status_code == 409 and again.json()["group"] is None
    assert len(site.checkins()) == 1


def test_another_group_may_be_open_at_the_same_time(bot_site_factory: BotSiteFactory) -> None:
    site, messenger = bot_site_factory(FakeMessenger())
    site.admin_post("/admin/checkins", {"lesson_date": LESSON, "group": GROUP})

    other = site.admin_post("/admin/checkins", {"lesson_date": LESSON, "group": "open-2026-10"})
    unnamed = site.admin_post("/admin/checkins", {"lesson_date": LESSON})

    assert (other.status_code, unnamed.status_code) == (201, 201)
    assert len(site.checkins()) == 3
    assert len(messenger.sent) == 3


def test_a_closed_or_expired_check_in_lets_the_group_open_again(site: Site) -> None:
    body = {"lesson_date": LESSON, "group": GROUP}
    first = site.open()
    site.clock.advance(timedelta(minutes=1))
    site.admin_post(f"/admin/checkins/{first['id']}/close")
    site.clock.advance(timedelta(minutes=1))

    assert site.admin_post("/admin/checkins", body).status_code == 201

    site.clock.advance(timedelta(minutes=20))  # the window of the second one is over

    assert site.admin_post("/admin/checkins", body).status_code == 201


def test_a_refused_open_does_not_need_the_bot_either(site: Site) -> None:
    site.open()

    response = site.admin_post("/admin/checkins", {"lesson_date": LESSON, "group": GROUP})

    assert response.status_code == 409 and response.json()["status"] == "open_exists"


def test_a_wrong_token_opens_and_posts_nothing(bot_site_factory: BotSiteFactory) -> None:
    site, messenger = bot_site_factory(FakeMessenger())

    response = site.admin_post(
        "/admin/checkins", {"lesson_date": LESSON, "group": GROUP}, token=False
    )

    assert response.status_code == 401
    assert site.checkins() == [] and messenger.sent == []
