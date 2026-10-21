"""Threads of the bot's own for the updates of the webhook (operator's addition to the plan).

Handling an update means up to three calls to Telegram and a few statements, seconds at worst.
On the shared threads of the plain-function routes a surge of people pressing the bot's button
right after an announcement would hold every thread, and the pages would wait for Telegram. The
updates run on ``BOT_AT_ONCE`` threads of their own instead; an update waiting for a free thread
holds none, and Telegram's webhook connection simply waits for its answer.
"""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

BOT_AT_ONCE = 8


class BotWorkers:
    """Runs jobs on the bot's threads, at most ``size`` at once, in the order they came."""

    def __init__(self, size: int = BOT_AT_ONCE) -> None:
        self._executor = ThreadPoolExecutor(max_workers=size, thread_name_prefix="bot")

    async def run[**P, R](self, job: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
        """Run ``job`` on a bot thread and return its result; the wait holds no thread."""
        return await asyncio.wrap_future(self._executor.submit(job, *args, **kwargs))

    def close(self) -> None:
        """Take no more jobs and drop the waiting ones; a running job finishes on its own."""
        self._executor.shutdown(wait=False, cancel_futures=True)
