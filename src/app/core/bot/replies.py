"""Messages and buttons of the bot: docs/copy.md, section 8, word for word.

Texts are not written or shortened here: the text oracle (tests/bot/test_copy_oracle.py) reads
the table of copy.md on its own and compares every message the bot sends with it. ``{site_url}``
is ``PUBLIC_BASE_URL``, ``{materials_url}`` the materials page ``/m/<MATERIALS_SLUG>`` on it
(copy.md, section 11).
"""

from dataclasses import dataclass
from enum import StrEnum

from app.core.entities import Button

# ``callback_data`` of the button «Перевірити ще раз».
RECHECK = "recheck"

MATERIALS = (
    "Готово: ваш Telegram підключено. Ось інструкція «Зроби сам» — покроковий опис, як зібрати "
    "такий сайт самостійно з кодинг-агентом: {materials_url}"
)
NOT_SUBSCRIBED = (
    "Telegram підключено. Інструкцію «Зроби сам» бот видає підписникам каналу «Agentic "
    "Engineers» — там голосування ефірів і дописи про агентну розробку. Підпишіться і натисніть "
    "«Перевірити ще раз»."
)
STILL_NOT_SUBSCRIBED = (
    "Підписки на канал поки не видно. Якщо ви щойно підписалися, зачекайте кілька секунд і "
    "натисніть ще раз."
)
CHECK_FAILED = "Не вдалося перевірити підписку. Спробуйте ще раз за хвилину."
EXPIRED = "Посилання застаріло. Введіть свою адресу на сайті ще раз — і отримаєте нове: {site_url}"
LINK_USED = (
    "Це посилання вже використано. Введіть свою адресу на сайті ще раз, щоб отримати нове: "
    "{site_url}"
)
REGISTRATION_TAKEN = (
    "Ця реєстрація вже прив'язана до іншого облікового запису Telegram. Щоб перенести її сюди, "
    "відкрийте посилання з листа-запрошення."
)
TELEGRAM_TAKEN = (
    "Ваш Telegram уже прив'язаний до іншої реєстрації. Щоб перенести його на цю адресу, "
    "відкрийте посилання з листа-запрошення."
)
TRANSFERRED = "Готово: Telegram тепер прив'язаний до цієї реєстрації."
WELCOME = (
    "Вітаю! Я бот вебінару «Архітектор замість кодера». Видаю інструкцію «Зроби сам» тим, хто "
    "зареєструвався на сайті і підписаний на канал «Agentic Engineers». Зареєструйтеся: "
    "{site_url} — на екрані успіху буде кнопка, яка підключить ваш Telegram."
)

OPEN_MATERIALS = "Відкрити інструкцію"
GO_TO_CHANNEL = "Перейти в канал"
CHECK_AGAIN = "Перевірити ще раз"


class Answer(StrEnum):
    """The situations of the table, by what the person gets; the values go to the log."""

    MATERIALS = "materials"
    NO_MATERIALS_LINK = "no_materials_link"  # subscribed, but MATERIALS_SLUG is not set
    NOT_SUBSCRIBED = "not_subscribed"
    STILL_NOT_SUBSCRIBED = "still_not_subscribed"
    CHECK_FAILED = "check_failed"
    EXPIRED = "expired"
    LINK_USED = "link_used"
    REGISTRATION_TAKEN = "registration_taken"
    TELEGRAM_TAKEN = "telegram_taken"
    TRANSFERRED = "transferred"
    WELCOME = "welcome"


@dataclass(frozen=True, slots=True)
class Reply:
    """A message: its text and rows of inline buttons."""

    text: str
    buttons: tuple[tuple[Button, ...], ...] = ()


def channel_url(channel: str) -> str:
    """The public link of a channel given as ``@name``.

    >>> channel_url("@agentic_engineers")
    'https://t.me/agentic_engineers'
    """
    return "https://t.me/" + channel.removeprefix("@")


class Replies:
    """The message for each ``Answer``, with the addresses of this site filled in.

    Without the materials page (``materials_url`` is ``None``) a subscribed person gets «could
    not check» and the button: no link to a page that answers 404 (operator's decision); the
    same button gives the link once ``MATERIALS_SLUG`` is set.

    >>> replies = Replies(site_url="https://site.example.com", materials_url=None, channel="@c")
    >>> replies.has_materials, replies.reply(Answer.EXPIRED).text.endswith("site.example.com")
    (False, True)
    >>> replies.reply(Answer.NO_MATERIALS_LINK) == replies.reply(Answer.CHECK_FAILED)
    True
    """

    def __init__(self, *, site_url: str, materials_url: str | None, channel: str) -> None:
        check_again = Button(CHECK_AGAIN, callback_data=RECHECK)
        subscribe = ((Button(GO_TO_CHANNEL, url=channel_url(channel)), check_again),)
        failed = Reply(CHECK_FAILED, ((check_again,),))
        self.has_materials = materials_url is not None
        self._replies = {
            Answer.NO_MATERIALS_LINK: failed,
            Answer.NOT_SUBSCRIBED: Reply(NOT_SUBSCRIBED, subscribe),
            Answer.STILL_NOT_SUBSCRIBED: Reply(STILL_NOT_SUBSCRIBED, subscribe),
            Answer.CHECK_FAILED: failed,
            Answer.EXPIRED: Reply(EXPIRED.format(site_url=site_url)),
            Answer.LINK_USED: Reply(LINK_USED.format(site_url=site_url)),
            Answer.REGISTRATION_TAKEN: Reply(REGISTRATION_TAKEN),
            Answer.TELEGRAM_TAKEN: Reply(TELEGRAM_TAKEN),
            Answer.TRANSFERRED: Reply(TRANSFERRED),
            Answer.WELCOME: Reply(WELCOME.format(site_url=site_url)),
        }
        if materials_url is not None:
            self._replies[Answer.MATERIALS] = Reply(
                MATERIALS.format(materials_url=materials_url),
                ((Button(OPEN_MATERIALS, url=materials_url),),),
            )

    def reply(self, answer: Answer) -> Reply:
        """The message of ``answer``; ``MATERIALS`` needs the materials page."""
        return self._replies[answer]
