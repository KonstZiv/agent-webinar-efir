"""Attendance: course groups, check-ins of lessons and the marks of participants.

Only new tables (docs/requirements.md, section 9а): v1's tables are not touched. Everything
that points at a participant cascades with the participant, so an unsubscribe deletes the
marks and the group membership. ``downgrade`` is for test databases only.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GROUP_CODE_FORMAT = "group_code ~ '^[a-z0-9-]{2,32}$'"


def upgrade() -> None:
    op.create_table(
        "participant_groups",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("participant_id", sa.BigInteger(), nullable=False),
        sa.Column("group_code", sa.String(32), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_participant_groups")),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participants.id"],
            name=op.f("fk_participant_groups_participant_id_participants"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "participant_id",
            "group_code",
            name=op.f("uq_participant_groups_participant_id_group_code"),
        ),
        sa.CheckConstraint(GROUP_CODE_FORMAT, name=op.f("ck_participant_groups_group_code")),
    )
    op.create_index(
        op.f("ix_participant_groups_participant_id"), "participant_groups", ["participant_id"]
    )
    op.create_index(op.f("ix_participant_groups_group_code"), "participant_groups", ["group_code"])

    op.create_table(
        "checkins",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("code", sa.String(8), nullable=False),
        sa.Column("lesson_date", sa.Date(), nullable=False),
        sa.Column("group_code", sa.String(32), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checkins")),
        sa.CheckConstraint("closes_at > opened_at", name=op.f("ck_checkins_window")),
        sa.CheckConstraint(
            f"group_code IS NULL OR ({GROUP_CODE_FORMAT})", name=op.f("ck_checkins_group_code")
        ),
    )
    op.create_index(op.f("ix_checkins_code"), "checkins", ["code"])

    op.create_table(
        "attendance",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("checkin_id", sa.BigInteger(), nullable=False),
        sa.Column("participant_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
        sa.Column("question", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attendance")),
        sa.ForeignKeyConstraint(
            ["checkin_id"],
            ["checkins.id"],
            name=op.f("fk_attendance_checkin_id_checkins"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participants.id"],
            name=op.f("fk_attendance_participant_id_participants"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "checkin_id", "participant_id", name=op.f("uq_attendance_checkin_id_participant_id")
        ),
        sa.CheckConstraint("source IN ('site', 'telegram')", name=op.f("ck_attendance_source")),
        sa.CheckConstraint(
            "rating IS NULL OR rating BETWEEN 1 AND 5", name=op.f("ck_attendance_rating")
        ),
    )
    op.create_index(op.f("ix_attendance_checkin_id"), "attendance", ["checkin_id"])
    op.create_index(op.f("ix_attendance_participant_id"), "attendance", ["participant_id"])


def downgrade() -> None:
    """Test databases only: the marks and the groups are lost."""
    op.drop_table("attendance")
    op.drop_table("checkins")
    op.drop_table("participant_groups")
