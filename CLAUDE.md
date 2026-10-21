# Правила проєкту

Сайт v2 вебінару на основі шаблону FastAPI-застосунку. Фундамент: модель даних на спільній з v1 базі, налаштування всіх зрізів, режими сайту, `/` (запасна сторінка до лендінгу), сторінка матеріалів, службові теги, `/healthz`, `/privacy` і банер cookie, режим переадресації; решту додають зрізи (розділ «Зрізи»). Що будуємо — `docs/requirements.md`; як саме — `spec.md` (його пише живий зріз «специфікація»). Задача не суперечить специфікації: якщо суперечить, спершу змінюється специфікація, і це погоджує оператор.

## Порядок роботи

- Кожна задача приходить постановкою у файлі (Goal / Context / Constraints / Done when). Виконується лише те, що в ній названо; обсяг не розширюється.
- Перед кодом — план у режимі планування; код пишеться після погодження плану оператором.
- Тести пишуться першими.
- Розбіжність між постановкою, специфікацією і реальністю — зупинка і повідомлення операторові. Постановку і специфікацію самостійно не «виправляти».
- Робота завершується лише на зелених гейтах і підсумком: що змінено, коміти, результат гейтів, розбіжності, відкриті запитання.
- Підсумок виконавця і рецензія між сесіями — файлами в теці `.handoff/` (поза git).
- Шаблони: задача — `docs/templates/task-template.md`, специфікація — `docs/templates/spec-template.md`, рецензія — `docs/templates/review-checklist.md`.

## Стек

Python 3.14, uv, FastAPI, SQLAlchemy 2.x + Alembic, PostgreSQL, Jinja2 + HTMX 2.0.11 (файл бібліотеки — у `static/`), pydantic-settings, httpx (Telegram Bot API і Resend — через нього), markdown-it-py, python-multipart, icalendar, anthropic (Issue Л), pytest, ruff, mypy, pre-commit, GitHub Actions. Розгортання — Railway. Стилі — статичний CSS.

## Команди

- Тести: `uv run pytest`
- Лінтер: `uv run ruff check .`
- Типи: `uv run mypy src`
- Гейти перед комітом: `uv run pre-commit install` (один раз), далі запускаються самі.

- Пакет: `app` (`src/app/`).
- Запуск локально: `docker compose up -d` (база), далі `uv run --env-file .env uvicorn app.main:create_app --factory --reload`. На Railway — `Procfile`.
- Міграції: `uv run --env-file .env alembic upgrade head`; на Railway — команда перед деплоєм `alembic upgrade head`.

Конфігурації гейтів курсу — `docs/gates/`: `ci.yml` (CI), `pre-commit-config.yaml`, `pyproject-gates.toml` (секції для `pyproject.toml`).

## Межі коду

- `src/<пакет>/core` — сутності, сценарії, порти (`Protocol`). Ядро не імпортує FastAPI, SQLAlchemy, HTTP-клієнти і адаптери.
- `src/<пакет>/adapters` — реалізації портів: база, Turnstile, обмеження частоти, тексти, веб (маршрути і шаблони).
- Адаптери обираються налаштуваннями. У тестах порти замінюються підставними реалізаціями: тести не звертаються до Turnstile, Google і мережі. Відоме обмеження: запобіжник мережі в тестах (`tests/conftest.py`) закриває httpx і нелокальні сокети, але не DNS — `socket.getaddrinfo` розв'язує імена через системний резолвер.
- Глобального стану немає: застосунок збирається фабрикою, налаштування і залежності передаються явно.
- Маршрут, у шляху якого є секретний токен, лежить під префіксом із `TOKEN_PATH_PREFIXES` (`adapters/web/token_paths.py`): зараз це `/unsubscribe/` і `/m/`.

## Зрізи

Фундамент дає зрізам усе спільне; зріз лише додає свої файли (`docs/requirements.md`, розділ 12). Спільні файли — перелік власності там само — зріз не змінює; дозволені винятки — лише з переліку розділу 12. Потрібен новий пакет або зміна спільного файла — запитання операторові.

- **Де код зрізу `<зріз>`** (`registration`, `bot`, `extras`; фіча — своя назва): `src/app/slices/<зріз>.py` — підключення; `src/app/core/<зріз>/` — сценарії і власні порти; `src/app/adapters/<зріз>/` — адаптери (Resend, Telegram, SQL-запити зрізу); `src/app/adapters/web/routers/<зріз>.py` або `<зріз>_*.py` — маршрути; `tests/<зріз>/` — тести. Модуль токена відписки `src/app/core/unsubscribe.py` (назва з `docs/contract.md`, розділ 4) — файл зрізу «реєстрація і лист» поза його пакетом; інших таких файлів немає. Частини шаблонів — `templates/_<назва>.html`; htmx і спільну `meta htmx-config` (`responseHandling` для 422/429/503, як у v1) підключає `base.html`, частини зрізів htmx не підключають; стилі — власний файл `static/css/<зріз>.css`. Зріз з'являється разом із `src/app/slices/<зріз>.py`.
- **Імпорт між зрізами заборонено** (`tests/test_architecture.py`): спільне — лише через фундамент.
- **Підключення** — функція `install(setup: SliceSetup)` у `src/app/slices/<зріз>.py`; `create_app` знаходить модулі сам, `main.py` і `dependencies.py` зріз не змінює. `setup.provide(KEY, build)` — адаптер, обраний за налаштуваннями (будується при першому зверненні); `setup.add_middleware` / `setup.http_middleware`; `setup.on_startup` / `setup.on_shutdown` / `setup.close_on_shutdown` (виняток дії під час запуску журналюється — клас винятку — і не зупиняє застосунок: критичних дій під час запуску в зрізах немає; падіння дії під час зупинки журналюється так само і не скасовує решти дій і closers); `setup.template_global` — значення для частин шаблонів; `setup.engine()` — рушій бази. У режимі переадресації зрізи не підключаються.
- **Сервіси за ключами** (`app/services.py`): маршрут отримує сервіс через `Depends(service(KEY))` (`adapters/web/dependencies.py`). Спільні порти — `app/core/ports.py`: `CLOCK`, `PARTICIPANTS` (`ParticipantStore`), `LINK_TOKENS` (`LinkTokenStore`) дає фундамент; `EMAIL_SENDER` і `HUMAN_CHECK` — зріз «реєстрація і лист»; `MESSENGER` — зріз «бот». Власні ключі зріз оголошує у своєму пакеті з префіксом `<зріз>.` (наприклад, `bot.rate_limiter`): `setup.provide` інших назв не приймає, крім спільних ключів.
- **Адміністратор** — `AdminDep` (`adapters/web/admin_auth.py`): `Authorization: Bearer <ADMIN_TOKEN>`.
- **Тести:** `create_app(settings, db_probe=FakeDatabaseProbe(), overrides=fake_overrides(...))` — підставні реалізації всіх зовнішніх портів (`tests/fakes.py`); фікстури `make_settings`, `migrated_engine`, `participant_factory` (`tests/conftest.py`); тексти — `tests/copy_oracle.py`.

## Маршрут `/` і `landing.html`

Маршрут `/` (`adapters/web/routers/home.py`) віддає `landing.html`, щойно він з'являється; до того — запасну сторінку фундаменту `home.html`. Тексти — готові, поточного режиму і дня (`docs/copy.md`, 1.1–1.7); лендінг лише розставляє їх у макеті. У шаблоні:

| Змінна | Блок `copy.md` | Поля |
| :-- | :-- | :-- |
| `hero` | 1.1 Перший екран | `eyebrow`, `title`, `subtitle`, `when`, `host`, `button` (веде на `#register`), `note` |
| `blocks.on_air` | 1.2 Що в ефірі / Що в записі | `title`, `intro`, `items`, `likes_goal` (після 30.10.2026 — `None`) |
| `blocks.audience` | 1.3 Для кого | `title`, `items`, `subtitle`, `text`, `note` |
| `blocks.benefits` | 1.4 Що ви отримаєте | `title`, `items` |
| `blocks.channel` | 1.5 Telegram-канал | `title`, `text`, `link` (готове посилання `<a>`) |
| `blocks.presenter` | 1.6 Ведучий | `title`, `name`, `text` |
| `blocks.course` | 1.7 Курс («акордеон») | `title`, `intro`; `sections` — розділи: `title`, `html`, `always_visible` (не згортається), `blocks` (блоки «Програми»: `title`, `html`) |
| `page_meta` | 10 | службові теги; виводить `base.html` у блоках `title` і `meta` |
| `site_mode` | — | `live` або `replay`; лише для частин зрізів |

`hero`, `page_meta`, `site_mode` дає маршрут; `blocks` — фундамент на кожен рендер (`adapters/web/dependencies.py`), тож їх має й сторінка у відповіді `/register` без htmx. Ім'я `blocks` зарезервоване. Тексти — вже безпечний HTML: `{{ … }}` без `|safe`.

```jinja
<h2>{{ blocks.on_air.title }}</h2>
<p>{{ blocks.on_air.intro }}</p>
<ol>{% for item in blocks.on_air.items %}<li>{{ item }}</li>{% endfor %}</ol>
{% if blocks.on_air.likes_goal %}<p>{{ blocks.on_air.likes_goal }}</p>{% endif %}

{% for section in blocks.course.sections %}
  {% if section.always_visible %}<h3>{{ section.title }}</h3>{{ section.html }}
  {% else %}<details><summary>{{ section.title }}</summary>{{ section.html }}
    {% for block in section.blocks %}<details><summary>{{ block.title }}</summary>{{ block.html }}</details>{% endfor %}
  </details>{% endif %}
{% endfor %}
```

- Лендінг не містить текстів `copy.md`, вписаних вручну, і не має умов режиму чи дати. `{% if blocks.on_air.likes_goal %}` лише перевіряє наявність: дату врахував фундамент.
- `landing.html` розширює `base.html`, не перевизначає блоків `title` і `meta`, підключає `_form.html` і `_counters.html` за назвами (`{% include "_form.html" ignore missing %}`), скриптів форми не підключає; стилі — `static/css/landing.css`.
- Умова готовності — зелений тест-оракул (`tests/test_copy_oracle.py`: блоки 1.1–1.7 обох режимів, рядок про вподобання до 30.10.2026 включно).

## Тексти

- Тексти сторінок — з документів у `docs/`, які називає специфікація; згода, політика приватності, банер cookie — з `docs/legal/` (тексти v1, згода `consent-v1`). Тексти не дописуються і не скорочуються.
- Тексти `/` і сторінки матеріалів — з `docs/copy.md` (розділи 1.1–1.7 і 10) і `docs/materials.md`; читаються під час запуску (`adapters/content/copy.py`). Тест-оракул `tests/test_copy_oracle.py` читає `copy.md` сам і звіряє з ним сторінки.
- Невідоме значення — питання операторові, а не вигадка.

## Мова коду і конфігурацій

- Docstring і коментарі в коді Python — англійською.
- Конфігурації, скопійовані з `docs/gates/`, і похідні від них (`pyproject.toml`, `.pre-commit-config.yaml`), а також коментарі в `.gitignore` — мовою курсу (українською).

## Секрети і дані

- `.env` і `.env.*` агентові закриті правилами дозволів (`.claude/settings.json`). Не обходити: не читати їх скриптами, не друкувати змінні середовища.
- Ключі, токени і паролі — лише в змінних середовища. Перелік змінних без значень — `docs/env.example`.
- Адреса електронної пошти в журналах маскується (`u***@example.com`, `core/masking.py`). Реальні адреси в тестах і фікстурах не використовуються — лише `example.com`.

## Розгортання

- Розгортання робить Railway автоматично з гілки `main` після зеленого CI. Агент не виконує команд `railway`, не змінює налаштувань сервісів і змінних середовища в Railway.
- Коміт і push — після зелених гейтів і рецензії, коли оператор це підтвердить.

## Code Review Rules

Коментувати лише суттєве: поведінка, дані, безпека.

- Ключ, токен або пароль у коді, тестах чи журналах — найвищий пріоритет.
- Немасковані адреси електронної пошти в журналах — блокер.
- Зміна чи видалення даних через GET — блокер.
- Імпорт адаптерів або фреймворків у `core` — блокер.
- Зріз змінює спільний файл поза винятками `docs/requirements.md`, розділ 12, або імпортує модуль іншого зрізу — блокер.
- Текст сторінки, що розходиться з `docs/legal/` чи іншим джерелом тексту, яке називає специфікація, — знахідка.
- Стиль і форматування не коментувати — це територія ruff.
