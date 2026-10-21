"""The whole v2 model: participant fields, link_tokens, clicks, wider email kinds.

Only additions to v1's tables (docs/requirements.md, section 10): no v1 column changes type,
becomes required or disappears; no check gets narrower. So v1 keeps working on the database.
The revision runs in one transaction; if it does not get a lock in time, it fails and the
database stays as it was. ``downgrade`` is for test databases only.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

V1_EMAIL_KINDS = ("confirmation", "reminder_day", "reminder_hour")
V2_EMAIL_KINDS = ("lesson_invitation", "lesson_reminder_day", "lesson_reminder_hour", "recording")
NEW_PARTICIPANT_COLUMNS = (
    "origin",
    "tg_user_id",
    "tg_username",
    "tg_linked_at",
    "channel_member",
    "level",
    "extra",
    "ref_code",
    "referred_by",
)


def _kinds(values: tuple[str, ...]) -> str:
    return f"kind IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    # v1 bounds each statement by 2 s, lock waits included: a v1 request queued behind this
    # migration must not run out of it. Both v1 tables are locked first, one after the other,
    # each wait bounded by lock_timeout: at most 2 × 0.5 s, before any change and in one
    # order. No lock in time — the deploy fails, nothing changes.
    op.execute("SET LOCAL lock_timeout = '500ms'")
    op.execute("LOCK TABLE participants, emails IN ACCESS EXCLUSIVE MODE")

    op.add_column("participants", sa.Column("origin", sa.String(8), nullable=True))
    op.add_column("participants", sa.Column("tg_user_id", sa.BigInteger(), nullable=True))
    op.add_column("participants", sa.Column("tg_username", sa.String(64), nullable=True))
    op.add_column(
        "participants", sa.Column("tg_linked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("participants", sa.Column("channel_member", sa.Boolean(), nullable=True))
    op.add_column("participants", sa.Column("level", sa.String(32), nullable=True))
    op.add_column("participants", sa.Column("extra", postgresql.JSONB(), nullable=True))
    op.add_column("participants", sa.Column("ref_code", sa.String(16), nullable=True))
    op.add_column("participants", sa.Column("referred_by", sa.BigInteger(), nullable=True))
    op.create_unique_constraint(op.f("uq_participants_ref_code"), "participants", ["ref_code"])
    op.create_foreign_key(
        op.f("fk_participants_referred_by_participants"),
        "participants",
        "participants",
        ["referred_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_participants_referred_by"), "participants", ["referred_by"])
    op.create_index(
        op.f("ix_participants_tg_user_id"),
        "participants",
        ["tg_user_id"],
        unique=True,
        postgresql_where=sa.text("tg_user_id IS NOT NULL"),
    )

    # A wider list: every kind v1 writes still passes.
    op.drop_constraint(op.f("ck_emails_kind"), "emails", type_="check")
    op.create_check_constraint(
        op.f("ck_emails_kind"), "emails", _kinds(V1_EMAIL_KINDS + V2_EMAIL_KINDS)
    )

    op.create_table(
        "link_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("participant_id", sa.BigInteger(), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_tg_user_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_link_tokens")),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participants.id"],
            name=op.f("fk_link_tokens_participant_id_participants"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token", name=op.f("uq_link_tokens_token")),
        sa.CheckConstraint("token ~ '^[A-Za-z0-9_-]+$'", name=op.f("ck_link_tokens_token")),
        sa.CheckConstraint("source IN ('screen', 'email')", name=op.f("ck_link_tokens_source")),
    )
    op.create_index(op.f("ix_link_tokens_participant_id"), "link_tokens", ["participant_id"])

    op.create_table(
        "clicks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("participant_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clicks")),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participants.id"],
            name=op.f("fk_clicks_participant_id_participants"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("kind IN ('lesson', 'course')", name=op.f("ck_clicks_kind")),
    )
    op.create_index(op.f("ix_clicks_participant_id"), "clicks", ["participant_id"])


def downgrade() -> None:
    """Test databases only: emails of v2 kinds make the narrow check impossible."""
    op.drop_table("clicks")
    op.drop_table("link_tokens")
    op.drop_constraint(op.f("ck_emails_kind"), "emails", type_="check")
    op.create_check_constraint(op.f("ck_emails_kind"), "emails", _kinds(V1_EMAIL_KINDS))
    op.drop_index(op.f("ix_participants_tg_user_id"), table_name="participants")
    op.drop_index(op.f("ix_participants_referred_by"), table_name="participants")
    op.drop_constraint(
        op.f("fk_participants_referred_by_participants"), "participants", type_="foreignkey"
    )
    op.drop_constraint(op.f("uq_participants_ref_code"), "participants", type_="unique")
    for column in reversed(NEW_PARTICIPANT_COLUMNS):
        op.drop_column("participants", column)
