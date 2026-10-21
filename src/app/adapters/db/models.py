"""Database model: v1's tables (revision 0001) and the whole v2 model (revision 0002).

The database is shared with v1 (docs/legacy-schema.md): v1 writes ``participants`` and
``emails`` by named columns and knows nothing else, so every column v2 adds may stay empty,
and new tables reference the participant with cascading deletes in the database itself
(docs/requirements.md, section 10). Constraint names follow ``NAMING_CONVENTION``, so Alembic
can find and drop them later. All timestamps are UTC.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Stored addresses are normalised (lower case, no surrounding whitespace), so the unique
# constraint on ``email`` is case-insensitive in effect; the database enforces it.
EMAIL_NORMALIZED = "email = lower(email) AND email !~ '^\\s|\\s$'"
V1_EMAIL_KINDS = ("confirmation", "reminder_day", "reminder_hour")
EMAIL_KINDS = (
    *V1_EMAIL_KINDS,
    "lesson_invitation",
    "lesson_reminder_day",
    "lesson_reminder_hour",
    "recording",
)
EMAIL_STATUSES = ("pending", "sent", "failed")
LINK_TOKEN_CHARACTERS = "token ~ '^[A-Za-z0-9_-]+$'"
LINK_TOKEN_SOURCES = ("screen", "email")
CLICK_KINDS = ("lesson", "course")

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Participant(Base):
    """A registered visitor; unsubscribing deletes the row (no «unsubscribed» flag).

    ``origin`` is ``v2`` for rows created by v2 and empty for rows of v1. One Telegram account
    belongs to at most one participant: ``tg_user_id`` is unique among filled values.
    """

    __tablename__ = "participants"
    __table_args__ = (
        CheckConstraint(EMAIL_NORMALIZED, name="email_normalized"),
        Index(
            "ix_participants_tg_user_id",
            "tg_user_id",
            unique=True,
            postgresql_where=text("tg_user_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    unsubscribe_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consent_version: Mapped[str] = mapped_column(String(16))
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    utm_source: Mapped[str | None] = mapped_column(String(500))
    utm_medium: Mapped[str | None] = mapped_column(String(500))
    utm_campaign: Mapped[str | None] = mapped_column(String(500))
    utm_term: Mapped[str | None] = mapped_column(String(500))
    utm_content: Mapped[str | None] = mapped_column(String(500))
    gclid: Mapped[str | None] = mapped_column(String(500))
    gbraid: Mapped[str | None] = mapped_column(String(500))
    wbraid: Mapped[str | None] = mapped_column(String(500))
    landing_url: Mapped[str | None] = mapped_column(String(500))
    referrer: Mapped[str | None] = mapped_column(String(500))
    ga_client_id: Mapped[str | None] = mapped_column(String(100))
    origin: Mapped[str | None] = mapped_column(String(8))
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger)
    tg_username: Mapped[str | None] = mapped_column(String(64))
    tg_linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channel_member: Mapped[bool | None] = mapped_column(Boolean)
    level: Mapped[str | None] = mapped_column(String(32))
    extra: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    ref_code: Mapped[str | None] = mapped_column(String(16), unique=True)
    # Unsubscribing the one who invited does not delete the invited: the link is cleared.
    referred_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("participants.id", ondelete="SET NULL"), index=True
    )


class EmailRecord(Base):
    """One email to a participant: one of each kind (v1: confirmation; v2: the lesson)."""

    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("participant_id", "kind"),
        CheckConstraint(_in("kind", EMAIL_KINDS), name="kind"),
        CheckConstraint(_in("status", EMAIL_STATUSES), name="status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    participant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("participants.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resend_id: Mapped[str | None] = mapped_column(String(100))
    last_error: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # No trigger in the database: the application stamps every change (v1 does the same).
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("attempts", 0)
        super().__init__(**kwargs)


class LinkToken(Base):
    """A personal link to the bot, ``t.me/<bot>?start=<token>``.

    ``screen`` tokens are single-use, ``email`` tokens last their whole term; ``used_at`` is the
    first use, ``used_by_tg_user_id`` the latest user.
    """

    __tablename__ = "link_tokens"
    __table_args__ = (
        CheckConstraint(LINK_TOKEN_CHARACTERS, name="token"),
        CheckConstraint(_in("source", LINK_TOKEN_SOURCES), name="source"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    participant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("participants.id", ondelete="CASCADE"), index=True
    )
    token: Mapped[str] = mapped_column(String(64), unique=True)
    source: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by_tg_user_id: Mapped[int | None] = mapped_column(BigInteger)


class Click(Base):
    """A click on a link in an email: to the lesson or to the course page (S3, after the air)."""

    __tablename__ = "clicks"
    __table_args__ = (CheckConstraint(_in("kind", CLICK_KINDS), name="kind"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    participant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("participants.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
