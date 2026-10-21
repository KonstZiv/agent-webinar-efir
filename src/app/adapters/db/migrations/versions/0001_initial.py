"""v1's tables: a verbatim copy of v1's revision 0001 (agent-webinar-v1, commit fee3439).

Revision ID: 0001
Revises:
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "participants",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("unsubscribe_id", sa.Uuid(), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_version", sa.String(16), nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("utm_source", sa.String(500), nullable=True),
        sa.Column("utm_medium", sa.String(500), nullable=True),
        sa.Column("utm_campaign", sa.String(500), nullable=True),
        sa.Column("utm_term", sa.String(500), nullable=True),
        sa.Column("utm_content", sa.String(500), nullable=True),
        sa.Column("gclid", sa.String(500), nullable=True),
        sa.Column("gbraid", sa.String(500), nullable=True),
        sa.Column("wbraid", sa.String(500), nullable=True),
        sa.Column("landing_url", sa.String(500), nullable=True),
        sa.Column("referrer", sa.String(500), nullable=True),
        sa.Column("ga_client_id", sa.String(100), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_participants")),
        sa.UniqueConstraint("email", name=op.f("uq_participants_email")),
        sa.UniqueConstraint("unsubscribe_id", name=op.f("uq_participants_unsubscribe_id")),
        sa.CheckConstraint(
            "email = lower(email) AND email !~ '^\\s|\\s$'",
            name=op.f("ck_participants_email_normalized"),
        ),
    )
    op.create_table(
        "emails",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("participant_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resend_id", sa.String(100), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_emails")),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participants.id"],
            name=op.f("fk_emails_participant_id_participants"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("participant_id", "kind", name=op.f("uq_emails_participant_id_kind")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_emails_idempotency_key")),
        sa.CheckConstraint(
            "kind IN ('confirmation', 'reminder_day', 'reminder_hour')", name=op.f("ck_emails_kind")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')", name=op.f("ck_emails_status")
        ),
    )


def downgrade() -> None:
    op.drop_table("emails")
    op.drop_table("participants")
