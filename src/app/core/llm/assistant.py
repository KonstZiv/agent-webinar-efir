"""The assistant: one message of a person in, the text of the answer out.

In this order: the length of the message, the hourly quota of the person (both answered with a
short text and no call to the API), the call. A reply without a call of the result tool, a cut
reply and a question outside the knowledge base all give the refusal of docs/copy.md, 12.4;
only a real result is classified and kept. A failure of the API gives the failure text and
returns the question to the quota. The log has the class of a failure, its HTTP code and the
type of the error, and the tokens of a success; never the key, the question or the answer.
"""

import logging

from app.core.llm import replies
from app.core.llm.classification import read_classification
from app.core.llm.ports import (
    ClassificationStore,
    LanguageModel,
    ModelReply,
    ModelRequest,
    ModelUnavailable,
)
from app.core.llm.prompt import frame, system_prompt
from app.core.ports import RateLimiter, StorageError

logger = logging.getLogger(__name__)

# Telegram refuses a message over 4096 characters; the token limit keeps answers far below it.
TELEGRAM_LIMIT = 4000


class Assistant:
    """Answers a person's free text from the knowledge base; safe to call from many threads."""

    def __init__(
        self,
        *,
        model: LanguageModel,
        knowledge: str,
        classifications: ClassificationStore,
        limiter: RateLimiter,
        max_chars: int,
        max_tokens: int,
    ) -> None:
        self._model = model
        self._system = system_prompt(knowledge)
        self._classifications = classifications
        self._limiter = limiter
        self._max_chars = max_chars
        self._max_tokens = max_tokens

    def respond(self, user_id: int, text: str) -> str:
        """The text to send to the person who is ``user_id`` in Telegram."""
        if len(text) > self._max_chars:
            return replies.TOO_LONG.format(max_chars=self._max_chars)
        key = str(user_id)
        if not self._limiter.allow(key):
            return replies.TOO_MANY
        request = ModelRequest(self._system, frame(text), self._max_tokens)
        try:
            reply = self._model.complete(request)
        except ModelUnavailable as error:
            self._limiter.refund(key)
            logger.error(
                "LLM request failed: %s, HTTP %s, %s", error.cause, error.status, error.error_type
            )
            return replies.FAILURE
        logger.info(
            "LLM answered: input tokens %d, output tokens %d",
            reply.input_tokens,
            reply.output_tokens,
        )
        return self._result(user_id, reply)

    def _result(self, user_id: int, reply: ModelReply) -> str:
        data = reply.tool_input
        if data is None or reply.truncated:
            why = "cut by the token limit" if reply.truncated else "no tool call"
            logger.warning("LLM gave no result: %s", why)
            return replies.REFUSAL
        self._keep(user_id, data)
        answer = data.get("answer")
        if data.get("in_knowledge_base") is not True or not isinstance(answer, str):
            return replies.REFUSAL
        return answer.strip()[:TELEGRAM_LIMIT] or replies.REFUSAL

    def _keep(self, user_id: int, data: dict[str, object]) -> None:
        classification = read_classification(data.get("level"), data.get("intent"))
        try:
            kept = self._classifications.save(user_id, classification)
        except StorageError as error:  # the answer is worth more than its classification
            logger.warning("LLM classification not kept: %s", type(error).__name__)
            return
        if not kept:
            logger.info("LLM classification not kept: no participant is linked")
