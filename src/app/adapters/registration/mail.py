"""Threads of their own for the mail (docs/requirements.md, section 6).

One letter may take up to 15 s: Resend's retries and pauses, most likely right after an
announcement, when everyone registers at once. On the shared threads that run the plain-function
routes, such letters would hold every thread and the pages would wait for the mail. The mail runs
on two threads of its own instead — as many requests at once as Resend allows by default — and a
letter waiting for a free thread holds none. The queue lives in memory: a restart drops it, and
the invitations in it stay «pending» until they count as failed (15 minutes) and the operator
resends them.
"""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

MAIL_AT_ONCE = 2  # Resend's default rate limit


class MailWorkers:
    """Runs mail jobs on their own threads, at most ``size`` at once, in the order they came."""

    def __init__(self, size: int = MAIL_AT_ONCE) -> None:
        self._executor = ThreadPoolExecutor(max_workers=size, thread_name_prefix="mail")

    async def run[**P, R](self, job: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
        """Run ``job`` on a mail thread and return its result; the wait holds no thread."""
        return await asyncio.wrap_future(self._executor.submit(job, *args, **kwargs))

    def close(self) -> None:
        """Take no more jobs and drop the waiting ones; a running job finishes on its own."""
        self._executor.shutdown(wait=False, cancel_futures=True)
