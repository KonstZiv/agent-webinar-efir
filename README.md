# Архітектор замість кодера — сайт вебінару v2

Репозиторій ефіру вебінару «Архітектор замість кодера: як працює агентна розробка на Python» (21.10.2026, ведучий — Костянтин Зівенко). У ньому — друга версія сайту вебінару [agent.pythoncourse.me](https://agent.pythoncourse.me): застосунок на FastAPI, який агенти будували за процесом курсу «Агентна розробка на Python» — постановка, план, тести, код, гейти, рецензія.

**Для кого.** Для тих, хто подивився запис вебінару, — новачків і junior-розробників на Python. Тут можна прочитати документи, з яких агенти будували сайт, запустити сайт у себе, розібратися, як він влаштований, і взяти шаблони постановок для власних задач.

- Сайт: [agent.pythoncourse.me](https://agent.pythoncourse.me)
- Курс «Агентна розробка на Python»: [agent.pythoncourse.me/go/course](https://agent.pythoncourse.me/go/course)
- Telegram-канал «Agentic Engineers»: [t.me/agentic_engineers](https://t.me/agentic_engineers)

## Запис і як ішов ефір

- **Запис ефіру:** [youtube.com/watch?v=tTLH7REm6_E](https://www.youtube.com/watch?v=tTLH7REm6_E).
- **Слайди:** [`docs/webinar/slides.pdf`](docs/webinar/slides.pdf).
- **План Б.** У день ефіру хостинг Railway мав масштабний збій: збирання й розгортання було зупинено, тому розгортань наживо не було. Етапи показано за планом Б — підготовленими зрізами.
- **Коміти «Підготовлений зріз: …»** в історії — це перенесення зрізів однією командою з приватного репозиторію, у якому автор готував і репетирував зрізи.
- **Макет.** Переміг у голосуванні макет «М'яке світло» — [`design/live/`](design/live/). Зображення-референс — `design/live/3 · soft-light-reference1x.png`. `Soft.dc.html` — експорт з інструмента дизайну: його середовища виконання (`support.js`, `vendor/`) у репозиторії немає, тож у браузері макет не відкриється, дивіться зображення.
- **Реліз.** У продакшн v2 вийшла 23.10.2026 — коміт `b4e5e3a` «Підготовлений зріз: реліз».
- **Фічі голосування.** Фічі, за які голосували глядачі, реалізує хмарний агент через Issue і PR цього репозиторію — їх видно у вкладках Issues і Pull requests.

## Як запустити локально

Потрібні Python 3.14, [uv](https://docs.astral.sh/uv/), Docker (для PostgreSQL) і Node.js (для тестів банера cookie).

```bash
git clone https://github.com/KonstZiv/agent-webinar-efir.git
cd agent-webinar-efir
uv sync                                     # залежності з uv.lock
uv run pre-commit install                   # гейти перед кожним комітом
docker compose up -d                        # PostgreSQL з compose.yaml на 127.0.0.1:55433
cp docs/env.example .env                    # перелік змінних без значень
```

Заповніть `.env`. Повний перелік змінних і їхні правила — у `docs/env.example` (позначка `[обов'язкова]`) і в `docs/requirements.md`, розділ 14. Для локального запуску досить таких значень:

```dotenv
DATABASE_URL=postgresql://app@localhost:55433/app
PUBLIC_BASE_URL=http://localhost:8000
EVENT_START=2026-10-21T19:00
EVENT_END=2026-10-21T21:00
LESSON_START=2026-10-28T19:00
LESSON_END=2026-10-28T21:00
COURSE_URL=https://example.com/course
TURNSTILE_SITE_KEY=1x00000000000000000000AA
TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA
RESEND_API_KEY=re_local
SENDER_EMAIL=webinar@mail.example.com
UNSUBSCRIBE_SECRET=<випадковий рядок, ≥ 32 символи>
ADMIN_TOKEN=<інший випадковий рядок, ≥ 32 символи>
```

- `DATABASE_URL` — база з `compose.yaml`: користувач `app`, без пароля, лише на `127.0.0.1`.
- `TURNSTILE_*` — офіційні [тестові ключі Cloudflare](https://developers.cloudflare.com/turnstile/troubleshooting/testing/): перевірка людини проходить завжди.
- `RESEND_API_KEY` — заглушка: сторінки працюють, але листів без справжнього ключа Resend не буде.
- Випадковий рядок для секретів: `uv run python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- Бот Telegram і LLM-чернетка бота необов'язкові: без їхніх змінних сайт працює.

Далі — міграції і запуск:

```bash
uv run --env-file .env alembic upgrade head                            # таблиці v1 (0001) і v2 (0002)
uv run --env-file .env uvicorn app.main:create_app --factory --reload  # http://127.0.0.1:8000
curl -s http://127.0.0.1:8000/healthz                                  # {"status":"ok"}
```

Без обов'язкової змінної або з неправильним значенням застосунок не стартує; повідомлення називає змінну, але не показує значення.

**Гейти:** `uv run pytest`, `uv run ruff check .`, `uv run mypy src` — ті самі запускають pre-commit перед комітом і CI (`.github/workflows/ci.yml`, зі службовим PostgreSQL). Тести не звертаються до зовнішніх сервісів: їх підмінено реалізаціями з `tests/fakes.py`. Тести бази беруть сервер із `TEST_DATABASE_URL`, без неї — з `compose.yaml` і працюють в окремій базі `app_test`; якщо сервер недоступний, ці тести пропускаються локально і падають у CI.

## Як влаштовано

### Ядро й адаптери

- `src/app/core` — сутності, сценарії й порти (`Protocol`). Ядро не імпортує FastAPI, SQLAlchemy, HTTP-клієнтів і адаптерів.
- `src/app/adapters` — реалізації портів: база, Turnstile, Resend, Telegram, обмеження частоти, тексти, веб (маршрути і шаблони Jinja2).
- Застосунок збирає фабрика `create_app` (`src/app/main.py`): налаштування і залежності передаються явно, глобального стану немає. Адаптери обираються налаштуваннями; у тестах їх замінюють підставні реалізації.
- Межі тримає тест `tests/test_architecture.py`.

### Фундамент і зрізи

Фундамент — спільне для всього сайту: модель даних, налаштування, режими сайту `live` і `replay`, сторінка `/`, політика приватності, банер cookie, службові теги. Решту додають **зрізи** — шматки функціональності від постановки до працюючої сторінки:

| Зріз | Що робить |
| :-- | :-- |
| `registration` | реєстрація і лист-запрошення, посилання з листів, відписка |
| `bot` | Telegram-бот: прив'язка до реєстрації, перевірка підписки на канал, видача матеріалів |
| `extras` | лічильники на сторінці, статистика й експорт для організатора |

Зріз лише додає свої файли: `src/app/slices/<зріз>.py` (функція `install(setup)` — `create_app` знаходить модуль сам), `src/app/core/<зріз>/`, `src/app/adapters/<зріз>/`, маршрути в `src/app/adapters/web/routers/` і тести в `tests/<зріз>/`. Імпорт між зрізами заборонено: спільне — лише через фундамент. Правила — `CLAUDE.md` (розділ «Зрізи») і `docs/requirements.md` (розділ 12).

### Контракт із v1

v2 замінила першу версію сайту на тих самих адресах і працює на тій самій базі PostgreSQL. Що v2 зобов'язана зберегти — посилання з уже надісланих листів, cookie, аналітику, спільні таблиці, — записано в `docs/contract.md`; схема таблиць v1 і правила спільної бази — у `docs/legacy-schema.md`. Ревізія Alembic `0001` — дослівна копія таблиць v1, `0002` лише додає модель v2. Контракт перевіряють `tests/test_contract.py` і `tests/db/test_legacy_schema.py`.

### Документи, з яких агенти будували сайт

| Файл | Що в ньому |
| :-- | :-- |
| `docs/brief.md` | бриф: що обіцяємо і кому |
| `docs/webinar.md`, `docs/course.md` | факти про вебінар і курс |
| `docs/requirements.md` | вимоги: що сайт має вміти |
| `docs/spec.md` | специфікація: як саме і в яких межах |
| `docs/copy.md`, `docs/quiz.md` | готові тексти сторінок, листів, бота і мінітесту |
| `docs/materials.md` | тексти сторінки матеріалів |
| `docs/legal/` | згода, політика приватності, банер cookie |
| `docs/env.example` | змінні середовища без значень |

### Що всередині

- **Застосунок** (`src/app/`). Фабрика `create_app`; маршрути з пакета `adapters/web/routers` підключаються без ручного переліку. Межі: `core` (сутності, порти) і `adapters` (реалізації).
- **Налаштування** зі змінних середовища (pydantic-settings), перелік — `docs/env.example`. Без обов'язкової змінної або з неправильним значенням застосунок не стартує; повідомлення називає змінну, але не показує значень.
- **Маршрути фундаменту:**
  - `/` — лендінг (`landing.html`) або, поки його немає, запасна сторінка фундаменту: перший екран режиму з `docs/copy.md` і службові теги;
  - `/healthz` (GET і HEAD) — 200, коли база відповідає;
  - `/privacy` — політика приватності;
  - `/favicon.ico`;
  - `/static/…`.
- **Маршрути зрізів:** `/register`, `/unsubscribe/…`, `/go/stream`, `/go/lesson`, `/go/course`, `/calendar/lesson.ics`, `/telegram/webhook`, `/counters`, маршрути адміністратора `/admin/…` — `docs/requirements.md`, розділ 4.
- **Сторінки:** базовий шаблон Jinja2, футер, банер cookie з Google Consent Mode v2 (`static/js/consent.js`), htmx 2.0.11 локальною копією. Юридичні тексти читаються під час старту з `docs/legal/` (тексти v1, згода `consent-v1`), тексти сторінок — з `docs/copy.md` і `docs/materials.md`; без них застосунок не стартує.
- **Адаптери:**
  - база: рушій із тайм-аутами, перевірка з'єднання;
  - Cloudflare Turnstile;
  - обмеження частоти в пам'яті;
  - юридичні тексти;
  - годинник;
  - IP клієнта за проксі Railway;
  - заголовки `noindex` / `no-store`;
  - маскування токенів у журналі доступу;
  - маскування email у журналах.
- **Alembic:** ревізія `0001` — таблиці v1 (дослівна копія), `0002` — уся модель v2; база спільна з v1 (`docs/legacy-schema.md`).
- **Гейти:** pytest, ruff, mypy, pre-commit, GitHub Actions зі службовим PostgreSQL.
- **Хмарний агент:** `.github/workflows/claude.yml` — `@claude` в Issue і коментарях від людей із правом запису; `claude-code-review.yml` — рев'ю кожного PR. Потрібні Claude GitHub App і секрет `CLAUDE_CODE_OAUTH_TOKEN`.
- **Правила для агента:** `CLAUDE.md`, `.claude/settings.json`. Шаблони постановки, специфікації й рецензії — `docs/templates/`; гейти курсу — `docs/gates/`.
- **Контракт** (`docs/contract.md`, `docs/legacy-schema.md`, `tests/test_contract.py`) — контракт конкретного проєкту, наведений як приклад; новий проєкт пише свій.

### Режим переадресації (заглушка)

Сервісу досить двох змінних: `DATABASE_URL` і `REDIRECT_BASE_URL` (плюс ті, що ставить Railway).

- `REDIRECT_BASE_URL` — адреса `https://вузол` без шляху, параметрів і фрагмента. З нею кожен запит, крім `/healthz`, отримує `307` на `REDIRECT_BASE_URL` + той самий шлях і ті самі параметри.
- Метод і тіло запиту зберігаються.
- `Cache-Control: no-store`: ні браузер, ні проміжні кеші відповідь не запам'ятовують, тож адресу згодом можна віддати іншому сайту.
- `/healthz` працює як завжди.
- Поки `INDEXING_ENABLED` вимкнено, відповідь 307 несе `X-Robots-Tag: noindex`, як і решта відповідей. Заглушці на основній адресі сайту задайте `INDEXING_ENABLED=true`.

```bash
curl -sI "http://127.0.0.1:8000/?utm_source=test&gclid=test"
# HTTP/1.1 307 Temporary Redirect
# location: https://new.example.com/?utm_source=test&gclid=test
```

### Розгортання на Railway

- Збирач Railpack бере `pyproject.toml`, `uv.lock` і `.python-version`; запуск — `Procfile`.
- У сервісі: команда перед деплоєм `alembic upgrade head`, перевірка працездатності `/healthz`, змінні з `docs/env.example`.
- `Dockerfile` і `railway.toml` у репозиторії немає: `Dockerfile` перемкнув би Railway з Railpack на Docker.
- Розгортання — автоматичне з гілки `main` після зеленого CI.

## Шаблони постановок і картки задач

- **Правила для агента** — `CLAUDE.md`: порядок роботи (постановка → план → тести → код → гейти → рецензія), межі коду, зрізи, секрети, правила рецензії.
- **Шаблони** — `docs/templates/`:
  - `task-template.md` — постановка задачі агентові (Goal / Context / Constraints / Done when);
  - `spec-template.md` — специфікація проєкту;
  - `review-checklist.md` — чек-лист рецензії коду від агента.
- **Картки задач для хмарного агента** — Issue цього репозиторію. Агент (`.github/workflows/claude.yml`) береться до роботи за згадкою `@claude` від людини з правом запису, пише план, тести й код і відкриває PR; `claude-code-review.yml` рецензує кожен PR. Приклади — у вкладках Issues і Pull requests.
- **Гейти курсу** — `docs/gates/`: `ci.yml`, `pre-commit-config.yaml`, `pyproject-gates.toml`.
- Підсумки виконавця і рецензії між сесіями — файлами в теці `.handoff/` (поза git).

### Як почати свій проєкт на цій основі

1. Склонуйте репозиторій або зробіть fork.
2. Напишіть `docs/requirements.md` (що будуємо) і `docs/spec.md` за `docs/templates/spec-template.md` (як саме і в яких межах). На них спирається `CLAUDE.md`.
3. Замініть тексти в `docs/legal/` своїми; назву і опис — у `pyproject.toml`.
4. Видаліть або перепишіть разом `docs/contract.md`, `docs/legacy-schema.md` і `tests/test_contract.py`: це контракт конкретного проєкту.
5. Додавайте можливості задачами за `docs/templates/task-template.md`: план → тести → код → гейти → рецензія.
6. Таблиці бази — першою ревізією: `uv run --env-file .env alembic revision -m "…"` (моделі — у `adapters/db/models.py`).

## Інструкція «Зроби сам»

Покрокову інструкцію «Зроби сам» видає Telegram-бот на сайті [agent.pythoncourse.me](https://agent.pythoncourse.me) після реєстрації.

## Ліцензія

- **Код** — MIT, файл [`LICENSE`](LICENSE).
- **Тексти й матеріали** — теки `docs/` і `design/`, зокрема слайди `docs/webinar/slides.pdf`, — CC BY 4.0, файл [`LICENSE-docs`](LICENSE-docs).

Усе можна вільно використовувати в будь-яких цілях; умова одна — згадати джерело: Костянтин Зівенко, вебінар «Архітектор замість кодера: як працює агентна розробка на Python», посилання на цей репозиторій.
