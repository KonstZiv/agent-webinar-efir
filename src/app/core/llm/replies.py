"""Messages of the LLM draft: docs/copy.md, section 12.4, word for word.

The test of the texts (tests/llm/test_texts.py) reads the table of copy.md on its own and
compares these. ``{max_chars}`` is the longest message the settings of the slice allow.
"""

REFUSAL = (
    "На це запитання в мене немає відповіді: я розповідаю лише про курс і реєстрацію. Про умови "
    "курсу можна запитати менеджерів CBS на сторінці курсу: "
    "edu.cbsystematics.com/ua/courses/ai-agent"
)
TOO_LONG = "Повідомлення задовге — напишіть, будь ласка, коротше: до {max_chars} символів."
TOO_MANY = "Ви поставили багато запитань за останню годину. Спробуйте трохи пізніше."
FAILURE = "Зараз не вдалося підготувати відповідь. Спробуйте пізніше."
