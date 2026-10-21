# Шаблон FastAPI-застосунку

Основа для нового проєкту без бізнес-коду. Шаблон стартує, проходить гейти якості й розгортається на Railway. Без власного коду він або показує службову сторінку, або працює заглушкою, яка тимчасово переадресовує всі запити на інший сайт.

У цьому репозиторії поверх шаблону — фундамент сайту v2 вебінару (`docs/requirements.md`): модель даних на спільній з v1 базі, налаштування всіх зрізів, режими сайту `live` і `replay`, запасна сторінка `/`, сторінка матеріалів, службові теги. Зрізи підключаються модулями `src/app/slices/` (`CLAUDE.md`, «Зрізи»).

## Що всередині

- **Застосунок** (`src/app/`). Фабрика `create_app`; маршрути з пакета `adapters/web/routers` підключаються без ручного переліку. Межі: `core` (сутності, порти) і `adapters` (реалізації).
- **Налаштування** зі змінних середовища (pydantic-settings), перелік — `docs/env.example`. Без обов'язкової змінної або з неправильним значенням застосунок не стартує; повідомлення називає змінну, але не показує значень.
- **Маршрути:**
  - `/` — лендінг (`landing.html`) або, поки його немає, запасна сторінка фундаменту: перший екран режиму з `docs/copy.md` і службові теги;
  - `/m/{slug}` — сторінка матеріалів з `docs/materials.md` (адреса — `MATERIALS_SLUG`);
  - `/healthz` (GET і HEAD) — 200, коли база відповідає;
  - `/privacy` — політика приватності;
  - `/favicon.ico`;
  - `/static/…`.
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

## Як запустити локально

Потрібні Python 3.14, [uv](https://docs.astral.sh/uv/), Docker, Node.js (для тестів банера cookie).

```bash
uv sync
uv run pre-commit install
docker compose up -d                        # PostgreSQL на 127.0.0.1:55433
cp docs/env.example .env                    # заповніть DATABASE_URL та інші потрібні змінні
uv run --env-file .env alembic upgrade head
uv run --env-file .env uvicorn app.main:create_app --factory --reload
```

Для локальної бази з `compose.yaml`: `DATABASE_URL=postgresql://app@localhost:55433/app`.

Гейти: `uv run pytest`, `uv run ruff check .`, `uv run mypy src`. Тести бази беруть сервер із `TEST_DATABASE_URL`, без неї — з `compose.yaml`; якщо база недоступна, ці тести пропускаються локально і падають у CI.

## Режим переадресації (заглушка)

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

## Як почати проєкт

1. Створіть репозиторій із цього шаблону (кнопка «Use this template» на GitHub) і склонуйте його.
2. Напишіть `docs/requirements.md` (що будуємо) і `spec.md` за `docs/templates/spec-template.md` (як саме і в яких межах). На них спирається `CLAUDE.md`.
3. Замініть зразки в `docs/legal/` справжніми текстами; назву і опис — у `pyproject.toml`.
4. Видаліть або перепишіть разом `docs/contract.md`, `docs/legacy-schema.md` і `tests/test_contract.py`: це контракт конкретного проєкту.
5. Додавайте можливості задачами за `docs/templates/task-template.md`: план → тести → код → гейти → рецензія.
6. Таблиці бази — першою ревізією: `uv run --env-file .env alembic revision -m "…"` (моделі — у `adapters/db/models.py`).

## Розгортання на Railway

- Збирач Railpack бере `pyproject.toml`, `uv.lock` і `.python-version`; запуск — `Procfile`.
- У сервісі: команда перед деплоєм `alembic upgrade head`, перевірка працездатності `/healthz`, змінні з `docs/env.example`.
- `Dockerfile` і `railway.toml` у репозиторії немає: `Dockerfile` перемкнув би Railway з Railpack на Docker.
