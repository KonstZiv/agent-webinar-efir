"""The slice «llm»: the LLM draft of the bot, for staging only (Issue Л).

Without ``LLM_ENABLED`` the slice adds nothing and the bot does not know it exists. Enabled, it
provides by key (``app.adapters.llm.keys``) the language model on Claude API, the SQL store of
the classification and the assistant the bot asks under the name ``llm.responder``; all are
built on first use, so creating the application builds no client and reaches no network. The
knowledge base is read at start: a missing ``docs/course.md`` is an error that stops the start
rather than one every question meets. The client is closed when the application stops.
"""

from datetime import timedelta
from pathlib import Path

from app.adapters.llm.claude import ClaudeModel, make_client
from app.adapters.llm.keys import CLASSIFICATIONS, MODEL, RESPONDER
from app.adapters.llm.knowledge import read_knowledge
from app.adapters.llm.settings import LlmSettings
from app.adapters.llm.store import SqlClassificationStore
from app.adapters.ratelimit.memory import InMemoryRateLimiter
from app.core.llm.assistant import Assistant
from app.core.llm.ports import LanguageModel
from app.services import CLOCK
from app.slices import SliceSetup

DOCS_DIR = Path("docs")


def install(setup: SliceSetup) -> None:
    settings = setup.settings
    if not settings.llm_enabled or settings.anthropic_api_key is None:
        return
    key = settings.anthropic_api_key
    limits = LlmSettings()
    knowledge = read_knowledge(DOCS_DIR)
    services = setup.services

    def model() -> LanguageModel:
        client = make_client(key.get_secret_value(), limits.timeout)
        setup.close_on_shutdown(client.close)
        return ClaudeModel(client, model=limits.model)

    def responder() -> Assistant:
        # The quota lives in the memory of this process: one worker, one counter (see the PR).
        limiter = InMemoryRateLimiter(
            limit=limits.per_hour, window=timedelta(hours=1), clock=services.get(CLOCK)
        )
        return Assistant(
            model=services.get(MODEL),
            knowledge=knowledge,
            classifications=services.get(CLASSIFICATIONS),
            limiter=limiter,
            max_chars=limits.max_chars,
            max_tokens=limits.max_tokens,
        )

    setup.provide(MODEL, model)
    setup.provide(CLASSIFICATIONS, lambda: SqlClassificationStore(setup.engine()))
    setup.provide(RESPONDER, responder)
