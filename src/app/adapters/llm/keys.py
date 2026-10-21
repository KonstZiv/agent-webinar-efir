"""Services of the slice «llm» by key (``app.services``), named ``llm.*``.

``llm.responder`` is the key the bot looks for under the same name (the bot's own typing of it
is ``FreeTextResponder``): slices do not import each other, and the name is what they share.
"""

from app.core.llm.assistant import Assistant
from app.core.llm.ports import ClassificationStore, LanguageModel
from app.services import Key

MODEL = Key[LanguageModel]("llm.model")
CLASSIFICATIONS = Key[ClassificationStore]("llm.classifications")
RESPONDER = Key[Assistant]("llm.responder")
