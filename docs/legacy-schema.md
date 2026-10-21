# Схема даних v1 і спільна база

**Версія 2 · 13.10.2026.** Таблиці v1 — за міграцією `0001` (v1: `src/webinar/adapters/db/migrations/versions/0001_initial.py`; моделі — `src/webinar/adapters/db/models.py`; коміт `40b5de5`). За рішенням 18 плану v2 працює на тій самій базі: імпорту немає, v2 зберігає ці таблиці й лише доповнює їх. Модель v2 — `docs/requirements.md`, розділ 10; решту домовленостей v1 і v2 описує `docs/contract.md`. Версія 2 лежить у репозиторії репетицій і в репозиторії шаблону (`docs/legacy-schema.md`), копії однакові; у репозиторії сайту лишається версія 1 (`docs/contract.md`, розділ 11).

Зміни версії 2: розділи про імпорт (відповідність `participants` → `leads`, злиття за email, порядок імпорту, остаточний імпорт, відкриті питання імпорту) замінено розділом «Спільна база».

## Таблиці v1

Усі позначки часу — `timestamptz` в UTC. Ревізія Alembic — `0001` (таблиця `alembic_version`).

### `participants` — учасник

| Стовпець | Тип | NULL | Примітка |
| :-- | :-- | :-- | :-- |
| `id` | `bigint`, identity | ні | первинний ключ `pk_participants`; назовні не показується |
| `email` | `varchar(254)` | ні | `uq_participants_email`; CHECK `ck_participants_email_normalized`: `email = lower(email) AND email !~ '^\s\|\s$'` — без пробілів на краях, у нижньому регістрі |
| `unsubscribe_id` | `uuid` | ні | `uq_participants_unsubscribe_id`; основа токена відписки (`docs/contract.md`, розділ 4); застосунок генерує `uuid4` |
| `registered_at` | `timestamptz` | ні | час реєстрації за годинником застосунку |
| `consent_version` | `varchar(16)` | ні | завжди `consent-v1` (v1: `src/webinar/core/registration.py`, `CONSENT_VERSION`) |
| `consent_at` | `timestamptz` | ні | час згоди |
| `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content` | `varchar(500)` | так | джерело переходу з cookie `src` |
| `gclid`, `gbraid`, `wbraid` | `varchar(500)` | так | ідентифікатори рекламного кліку Google |
| `landing_url`, `referrer` | `varchar(500)` | так | сторінка входу і сторінка, з якої перейшли |
| `ga_client_id` | `varchar(100)` | так | лише вигляду `<цифри>.<цифри>` і лише з активною аналітикою |

Позначки «відписаний» немає: відписка видаляє рядок, листи учасника видаляються каскадом.

### `emails` — лист учасникові

| Стовпець | Тип | NULL | Примітка |
| :-- | :-- | :-- | :-- |
| `id` | `bigint`, identity | ні | первинний ключ `pk_emails` |
| `participant_id` | `bigint` | ні | `fk_emails_participant_id_participants` → `participants.id`, `ON DELETE CASCADE` |
| `kind` | `varchar(32)` | ні | CHECK `ck_emails_kind`: `confirmation`, `reminder_day`, `reminder_hour`; UNIQUE `uq_emails_participant_id_kind` разом із `participant_id` |
| `status` | `varchar(16)` | ні | CHECK `ck_emails_status`: `pending`, `sent`, `failed` |
| `idempotency_key` | `uuid` | ні | `uq_emails_idempotency_key`; заголовок `Idempotency-Key` для Resend |
| `scheduled_at` | `timestamptz` | так | час відкладеного надсилання |
| `sent_at` | `timestamptz` | так | коли Resend прийняв лист |
| `resend_id` | `varchar(100)` | так | ідентифікатор листа в Resend |
| `last_error` | `varchar(500)` | так | статус і назва помилки, без персональних даних |
| `attempts` | `integer` | ні | за замовчуванням `0` (у базі й у моделі) |
| `created_at` | `timestamptz` | ні | за замовчуванням `now()` |
| `updated_at` | `timestamptz` | ні | за замовчуванням `now()`; оновлює ORM (`onupdate`), тригера в базі немає |

v1 створює лише листи `confirmation`: нагадування не реалізовано.

### Індекси

Окремих індексів міграція не створює. Є лише унікальні індекси, які PostgreSQL будує під первинні ключі й обмеження UNIQUE:

- `pk_participants` (`id`), `uq_participants_email` (`email`), `uq_participants_unsubscribe_id` (`unsubscribe_id`);
- `pk_emails` (`id`), `uq_emails_participant_id_kind` (`participant_id`, `kind`), `uq_emails_idempotency_key` (`idempotency_key`).

## Спільна база

### Що v2 робить із таблицями v1

- **Нічого не видаляє і не звужує.** Таблиці `participants` та `emails`, їхні стовпці й типи лишаються як у v1; одну перевірку розширює (нижче).
- **Додає** (ревізія `0002`): у `participants` — стовпці, що можуть бути порожніми (`origin`, `tg_user_id`, `tg_username`, `tg_linked_at`, `channel_member`, `level`, `extra`, `ref_code`, `referred_by`), частковий унікальний індекс на `tg_user_id` (`WHERE tg_user_id IS NOT NULL`) і індекс на `referred_by`; нові таблиці `link_tokens` (з `used_by_tg_user_id`) і `clicks` з каскадним видаленням за учасником і індексами на `participant_id`; у `emails` — нові види листів. Повний опис — `docs/requirements.md`, розділ 10.
- **Розширює одну перевірку:** `ck_emails_kind` замінюється ширшою — до `confirmation`, `reminder_day`, `reminder_hour` додаються `lesson_invitation`, `lesson_reminder_day`, `lesson_reminder_hour`, `recording`. Значення, які пише v1, перевірку проходять.

### Правила міграції v2

- Ревізія `0001` v2 — дослівна копія `0001_initial.py` v1 (змінюється лише docstring): схема, описана вище, з тими самими назвами обмежень. База v1 для v2 — своя, і `alembic upgrade head` v2 застосовує на ній лише `0002`. Тест звіряє схему після `0001` з цим документом повністю: назви обмежень, вирази перевірок, типові значення, відсутність окремих індексів.
- Ревізія `0002` лише додає: жоден стовпець v1 не змінює тип, не стає обов'язковим і не зникає; жодна перевірка не звужується.
- Нові таблиці посилаються на учасника з `ON DELETE CASCADE` у базі; посилання учасника на учасника (`referred_by`) — `ON DELETE SET NULL`.
- `0002` виконується однією транзакцією і на початку встановлює `lock_timeout = 500ms`, а першою інструкцією блокує обидві таблиці v1 (`LOCK TABLE participants, emails`). Таблиці блокуються по черзі, тому очікувань два, і разом вони тривають не більше 1 с: v1 у цей час приймає реєстрації й обмежує кожен запит двома секундами.
- `downgrade` `0002` — лише для тестової бази: на робочій базі з листами v2 повернення вузької перевірки неможливе.

### Що бачить v1 після `0002`

- **Реєстрація v1** пише учасника явно названими стовпцями: нові стовпці лишаються порожніми, `origin` порожній означає «зареєстровано через v1».
- **Відписка v1** видаляє рядок `participants` запитом `DELETE`; база каскадом видаляє листи, токени бота і переходи.
- **Статистика v1** рахує всіх учасників, зокрема зареєстрованих через v2; «листи зі збоєм» — за всіма видами листів, зокрема листами v2.
- **Повторне надсилання v1** бере лише листи `confirmation`; листи v2 не чіпає.
- **Ревізія бази невідома коду v1:** команда v1 перед деплоєм `alembic upgrade head` на базі після `0002` завершується помилкою. Тому після міграції v2 у сервісі `web-v1` не змінюють змінних, не пушать у `main` репозиторію сайту і не розгортають його повторно; працює він без змін.

Перевірку сумісності виконує фундамент v2 за процедурою `docs/requirements.md`, розділ 11: базу створює `0001` v1, далі `0002` v2; v1 (`fee3439`) працює на ній через свою фабрику з підставними перевіркою людини і поштою. Результат — `.handoff/compat-check.md` репозиторію репетицій, звідти — у `show/compat-check.md` теки кроку 05 репозиторію курсу.

## Згода `consent-v1`

`consent-v1` закріплено за текстом згоди v1 (`docs/legal/consent.md` v1, розділ «Текст позначки»). v2 використовує той самий текст і ту саму версію (рішення кроку 05). Якщо текст згоди колись зміниться, нова версія отримає іншу назву, і `consent_version` у кожному записі однозначно вказуватиме, на який текст погодилась людина.
