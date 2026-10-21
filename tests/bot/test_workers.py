"""Updates run on the bot's own threads, so a surge of Telegram never holds up the pages.

The plain-function routes share AnyIO's 40 threads. If the bot ran on them, 40 updates waiting
for Telegram would make every page wait too (operator's addition to the plan).
"""

import time
from concurrent.futures import ThreadPoolExecutor

from app.adapters.bot.workers import BOT_AT_ONCE
from app.core.entities import TelegramAccount
from tests.bot.conftest import BotSiteFactory
from tests.bot.helpers import StuckTelegram
from tests.conftest import ParticipantFactory

SURGE = 45  # more than AnyIO's 40 shared threads


def wait_for(condition: object, seconds: float = 5) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():  # type: ignore[operator]
            return
        time.sleep(0.02)
    raise AssertionError("the condition did not come true")


def test_pages_answer_while_telegram_holds_a_surge_of_updates(
    bot_site_factory: BotSiteFactory, participant_factory: ParticipantFactory
) -> None:
    telegram = StuckTelegram()
    site = bot_site_factory(messenger=telegram)
    accounts = [TelegramAccount(900_000_000 + number) for number in range(SURGE)]
    for account in accounts:
        participant_factory(telegram=account)

    with ThreadPoolExecutor(SURGE + 1) as pool:
        updates = [pool.submit(site.start, account) for account in accounts]
        try:
            wait_for(lambda: telegram.waiting >= BOT_AT_ONCE)
            time.sleep(0.3)  # the rest of the surge arrives and queues

            page = pool.submit(site.client.get, "/")

            assert page.result(timeout=5).status_code == 200
            assert telegram.waiting == BOT_AT_ONCE
        finally:
            telegram.release()
        assert [update.result(timeout=30).status_code for update in updates] == [200] * SURGE

    assert len(site.sent) == SURGE


def test_an_update_runs_on_a_thread_of_the_bot(
    bot_site_factory: BotSiteFactory, participant_factory: ParticipantFactory
) -> None:
    telegram = StuckTelegram()
    telegram.release()
    site = bot_site_factory(messenger=telegram)
    participant_factory(telegram=TelegramAccount(900_000_001))

    site.start(TelegramAccount(900_000_001))

    assert [name.startswith("bot") for name in telegram.threads] == [True]
