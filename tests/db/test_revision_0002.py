"""Revision 0002 only adds to v1's tables (requirements, section 10, «Правила міграції»).

v1 keeps working on the database after 0002: none of its columns, constraints or indexes
changes, except the check of email kinds, which only gets wider. New tables reference the
participant with cascading deletes in the database, so v1's unsubscribe removes everything;
a referral is cleared instead. The revision takes the locks of both v1 tables before any change,
waits for each at most ``LOCK_TIMEOUT_SECONDS`` and leaves the database as it was if it fails.
"""

import time
import uuid
from collections.abc import Iterator

import pytest
from psycopg import errors
from sqlalchemy import Connection, Engine, event, text
from sqlalchemy.exc import IntegrityError, OperationalError

from tests.database import migrate
from tests.db.schema import Schema, index_columns, read_schema, revision_of

V1_KINDS = ("confirmation", "reminder_day", "reminder_hour")
V2_KINDS = ("lesson_invitation", "lesson_reminder_day", "lesson_reminder_hour", "recording")
# v1 bounds every statement by 2 s, waiting for a lock included; a registration of v1 queued
# behind the migration must not run out of it. The migration waits for two tables, one by one.
LOCK_TIMEOUT_SECONDS = 0.5
V1_STATEMENT_TIMEOUT_SECONDS = 2
LOCK_BOTH_TABLES = "LOCK TABLE participants, emails IN ACCESS EXCLUSIVE MODE"


def add_participant(connection: Connection, email: str, **v2_fields: object) -> int:
    """A participant row as v1 writes it (named v1 columns), plus any v2 fields."""
    fields: dict[str, object] = {
        "email": email,
        "unsubscribe_id": uuid.uuid4(),
        "consent_version": "consent-v1",
        **v2_fields,
    }
    names = ", ".join(fields)
    values = ", ".join(f":{name}" for name in fields)
    statement = text(
        f"INSERT INTO participants ({names}, registered_at, consent_at) "
        f"VALUES ({values}, now(), now()) RETURNING id"
    )
    return int(connection.execute(statement, fields).scalar_one())


def add_email(connection: Connection, participant_id: int, kind: str) -> None:
    connection.execute(
        text(
            "INSERT INTO emails (participant_id, kind, status, idempotency_key) "
            "VALUES (:participant_id, :kind, 'pending', :key)"
        ),
        {"participant_id": participant_id, "kind": kind, "key": uuid.uuid4()},
    )


def add_link_token(
    connection: Connection, participant_id: int, token: str = "a" * 32, source: str = "email"
) -> None:
    connection.execute(
        text(
            "INSERT INTO link_tokens (participant_id, token, source, created_at, expires_at) "
            "VALUES (:participant_id, :token, :source, now(), now() + interval '7 days')"
        ),
        {"participant_id": participant_id, "token": token, "source": source},
    )


def add_click(connection: Connection, participant_id: int, kind: str = "lesson") -> None:
    connection.execute(
        text("INSERT INTO clicks (participant_id, kind, created_at) VALUES (:id, :kind, now())"),
        {"id": participant_id, "kind": kind},
    )


def count(connection: Connection, table: str) -> int:
    return int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


@pytest.fixture
def schemas(fresh_engine: Engine) -> tuple[Schema, Schema]:
    """The schema after 0001 and after 0002."""
    migrate(fresh_engine, "0001")
    with fresh_engine.connect() as connection:
        before = read_schema(connection)
    migrate(fresh_engine, "head")
    with fresh_engine.connect() as connection:
        return before, read_schema(connection)


@pytest.fixture
def migrated(migrated_engine: Engine) -> Iterator[Connection]:
    with migrated_engine.begin() as connection:
        yield connection


# --- only additions ------------------------------------------------------------------------


def test_v1_columns_are_unchanged(schemas: tuple[Schema, Schema]) -> None:
    before, after = schemas

    for table, columns in before.columns.items():
        assert after.columns[table][: len(columns)] == columns


def test_new_columns_of_v1_tables_may_stay_empty(schemas: tuple[Schema, Schema]) -> None:
    """v1 inserts without them: no new column is required or filled by a default."""
    before, after = schemas
    added = [
        column
        for table, columns in before.columns.items()
        for column in after.columns[table][len(columns) :]
    ]

    assert [column.name for column in added] == [
        "origin",
        "tg_user_id",
        "tg_username",
        "tg_linked_at",
        "channel_member",
        "level",
        "extra",
        "ref_code",
        "referred_by",
    ]
    assert all(column.nullable and column.default is None for column in added)


def test_v1_constraints_and_indexes_stay_except_the_kind_check(
    schemas: tuple[Schema, Schema],
) -> None:
    before, after = schemas

    changed = {
        name
        for name, constraint in before.constraints.items()
        if after.constraints.get(name) != constraint
    }
    assert changed == {"ck_emails_kind"}
    assert before.indexes.items() <= after.indexes.items()


def test_the_v2_structure(schemas: tuple[Schema, Schema]) -> None:
    """Keys of the new tables, the referral link and the indexes on every reference."""
    _, after = schemas
    constraints = {name: constraint.definition for name, constraint in after.constraints.items()}

    assert constraints["fk_participants_referred_by_participants"] == (
        "FOREIGN KEY (referred_by) REFERENCES participants(id) ON DELETE SET NULL"
    )
    assert constraints["fk_link_tokens_participant_id_participants"] == (
        "FOREIGN KEY (participant_id) REFERENCES participants(id) ON DELETE CASCADE"
    )
    assert constraints["fk_clicks_participant_id_participants"] == (
        "FOREIGN KEY (participant_id) REFERENCES participants(id) ON DELETE CASCADE"
    )
    assert constraints["uq_participants_ref_code"] == "UNIQUE (ref_code)"
    assert constraints["uq_link_tokens_token"] == "UNIQUE (token)"
    assert constraints["pk_link_tokens"] == "PRIMARY KEY (id)"
    assert constraints["pk_clicks"] == "PRIMARY KEY (id)"

    indexes = after.indexes
    assert {
        name: index_columns(indexes[name].definition)
        for name in (
            "ix_participants_referred_by",
            "ix_link_tokens_participant_id",
            "ix_clicks_participant_id",
        )
    } == {
        "ix_participants_referred_by": ("referred_by",),
        "ix_link_tokens_participant_id": ("participant_id",),
        "ix_clicks_participant_id": ("participant_id",),
    }
    tg_user = indexes["ix_participants_tg_user_id"].definition
    assert tg_user.startswith("CREATE UNIQUE INDEX")
    assert index_columns(tg_user) == ("tg_user_id",)
    assert tg_user.endswith("WHERE (tg_user_id IS NOT NULL)")


def test_v1_rows_survive_and_v1_inserts_still_work(fresh_engine: Engine) -> None:
    migrate(fresh_engine, "0001")
    with fresh_engine.begin() as connection:
        add_email(connection, add_participant(connection, "before@example.com"), "confirmation")

    migrate(fresh_engine, "head")

    with fresh_engine.begin() as connection:
        add_email(connection, add_participant(connection, "after@example.com"), "confirmation")
        rows = connection.execute(
            text(
                "SELECT email, origin, tg_user_id, referred_by, extra FROM participants ORDER BY id"
            )
        ).all()
        assert [tuple(row) for row in rows] == [
            ("before@example.com", None, None, None, None),
            ("after@example.com", None, None, None, None),
        ]
        assert count(connection, "emails") == 2


# --- deleting a participant ----------------------------------------------------------------


def test_deleting_a_participant_cascades_to_every_table(migrated: Connection) -> None:
    """v1's unsubscribe is a plain DELETE; the database removes the rest."""
    leaving = add_participant(migrated, "leaving@example.com", origin="v2")
    staying = add_participant(migrated, "staying@example.com")
    for participant in (leaving, staying):
        add_email(migrated, participant, "lesson_invitation")
        add_link_token(migrated, participant, token=f"token-{participant}".ljust(32, "x"))
        add_click(migrated, participant)

    migrated.execute(text("DELETE FROM participants WHERE id = :id"), {"id": leaving})

    for table in ("emails", "link_tokens", "clicks"):
        owners = migrated.execute(text(f"SELECT participant_id FROM {table}")).scalars().all()
        assert owners == [staying], table


def test_deleting_a_referrer_clears_the_referral(migrated: Connection) -> None:
    referrer = add_participant(migrated, "referrer@example.com", ref_code="ABC123")
    invited = add_participant(migrated, "invited@example.com", referred_by=referrer)

    migrated.execute(text("DELETE FROM participants WHERE id = :id"), {"id": referrer})

    referred_by = migrated.execute(
        text("SELECT referred_by FROM participants WHERE id = :id"), {"id": invited}
    ).scalar_one()
    assert referred_by is None


# --- checks and unique values --------------------------------------------------------------


def test_kind_check_accepts_v1_and_v2_kinds(migrated: Connection) -> None:
    participant = add_participant(migrated, "kinds@example.com")

    for kind in V1_KINDS + V2_KINDS:
        add_email(migrated, participant, kind)

    assert count(migrated, "emails") == len(V1_KINDS) + len(V2_KINDS)


def violation(engine: Engine, write: str, **params: object) -> BaseException | None:
    """The database error of ``write`` after one valid participant (id in ``:participant``)."""
    try:
        with engine.begin() as connection:
            participant = add_participant(connection, f"{uuid.uuid4().hex}@example.com")
            connection.execute(text(write), {"participant": participant, **params})
    except IntegrityError as error:
        return error.orig
    return None


@pytest.mark.parametrize(
    ("write", "params", "expected"),
    [
        (
            "INSERT INTO emails (participant_id, kind, status, idempotency_key) "
            "VALUES (:participant, 'newsletter', 'pending', gen_random_uuid())",
            {},
            errors.CheckViolation,
        ),
        (
            "INSERT INTO link_tokens (participant_id, token, source, created_at, expires_at) "
            "VALUES (:participant, :token, 'email', now(), now())",
            {"token": "not allowed!" + "a" * 20},
            errors.CheckViolation,
        ),
        (
            "INSERT INTO link_tokens (participant_id, token, source, created_at, expires_at) "
            "VALUES (:participant, :token, 'chat', now(), now())",
            {"token": "a" * 32},
            errors.CheckViolation,
        ),
        (
            "INSERT INTO clicks (participant_id, kind, created_at) "
            "VALUES (:participant, 'stream', now())",
            {},
            errors.CheckViolation,
        ),
    ],
    ids=["email-kind", "token-characters", "token-source", "click-kind"],
)
def test_checks_reject_unknown_values(
    migrated_engine: Engine, write: str, params: dict[str, object], expected: type[Exception]
) -> None:
    assert isinstance(violation(migrated_engine, write, **params), expected)


def test_allowed_values_pass_the_checks(migrated: Connection) -> None:
    participant = add_participant(migrated, "allowed@example.com")

    add_link_token(migrated, participant, token="Az09_-" * 6, source="screen")
    add_link_token(migrated, participant, token="b" * 64, source="email")
    add_click(migrated, participant, "lesson")
    add_click(migrated, participant, "course")

    assert (count(migrated, "link_tokens"), count(migrated, "clicks")) == (2, 2)


def test_one_telegram_account_per_registration(migrated_engine: Engine) -> None:
    """Unique among filled values: many participants without Telegram, one per account."""
    with migrated_engine.begin() as connection:
        add_participant(connection, "first@example.com")
        add_participant(connection, "second@example.com")
        add_participant(connection, "linked@example.com", tg_user_id=42)

    assert isinstance(
        violation(
            migrated_engine,
            "UPDATE participants SET tg_user_id = 42 WHERE id = :participant",
        ),
        errors.UniqueViolation,
    )


@pytest.mark.parametrize(
    ("setup", "write"),
    [
        (
            "INSERT INTO participants (email, unsubscribe_id, registered_at, consent_version, "
            "consent_at, ref_code) VALUES ('ref@example.com', gen_random_uuid(), now(), "
            "'consent-v1', now(), 'SAME')",
            "UPDATE participants SET ref_code = 'SAME' WHERE id = :participant",
        ),
        (
            "INSERT INTO link_tokens (participant_id, token, source, created_at, expires_at) "
            "SELECT id, 'same-token-0123456789abcdef012345', 'email', now(), now() "
            "FROM participants LIMIT 1",
            "INSERT INTO link_tokens (participant_id, token, source, created_at, expires_at) "
            "VALUES (:participant, 'same-token-0123456789abcdef012345', 'screen', now(), now())",
        ),
    ],
    ids=["ref-code", "token"],
)
def test_unique_values(migrated_engine: Engine, setup: str, write: str) -> None:
    with migrated_engine.begin() as connection:
        add_participant(connection, "owner@example.com")
        connection.execute(text(setup))

    assert isinstance(violation(migrated_engine, write), errors.UniqueViolation)


# --- locks and atomicity -------------------------------------------------------------------


def test_lock_timeout_and_the_locks_come_before_any_change(fresh_engine: Engine) -> None:
    """Every wait happens at the start, in one order, with no work done between the waits."""
    migrate(fresh_engine, "0001")
    statements: list[str] = []
    event.listen(
        fresh_engine, "before_cursor_execute", lambda *args: statements.append(args[2].strip())
    )

    migrate(fresh_engine, "head")

    lock = next(i for i, sql in enumerate(statements) if "lock_timeout" in sql)
    first_change = next(
        i for i, sql in enumerate(statements) if sql.startswith(("ALTER", "CREATE", "DROP"))
    )
    assert statements[lock] == f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT_SECONDS * 1000:.0f}ms'"
    assert statements[lock + 1] == LOCK_BOTH_TABLES
    assert lock + 1 < first_change


def test_both_waits_fit_into_a_v1_statement() -> None:
    assert 2 * LOCK_TIMEOUT_SECONDS < V1_STATEMENT_TIMEOUT_SECONDS


@pytest.mark.parametrize("table", ["participants", "emails"])
def test_upgrade_gives_up_on_a_held_lock_and_changes_nothing(
    fresh_engine: Engine, table: str
) -> None:
    """While a v1 request reads a table, 0002 fails fast and the database stays at 0001."""
    migrate(fresh_engine, "0001")
    with fresh_engine.connect() as connection:
        v1_schema = read_schema(connection)

    with fresh_engine.connect() as v1_request:
        # What any open read of v1 holds until its transaction ends.
        v1_request.execute(text(f"LOCK TABLE {table} IN ACCESS SHARE MODE"))
        started = time.monotonic()
        with pytest.raises(OperationalError) as failure:
            migrate(fresh_engine, "head")
        elapsed = time.monotonic() - started
        v1_request.rollback()

    assert isinstance(failure.value.orig, errors.LockNotAvailable)
    assert LOCK_TIMEOUT_SECONDS <= elapsed < V1_STATEMENT_TIMEOUT_SECONDS
    with fresh_engine.connect() as connection:
        assert revision_of(connection) == "0001"
        assert read_schema(connection) == v1_schema
