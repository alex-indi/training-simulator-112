"""Добавляет базовые учебные сессии и назначения обучаемых.

Revision ID: 20260922_02
Revises: 20260922_01
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_02"
down_revision: str | None = "20260922_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

training_session_state = sa.Enum(
    "DRAFT",
    "READY",
    "ACTIVE",
    "COMPLETED",
    "CANCELLED",
    name="training_session_state",
)


def upgrade() -> None:
    """Создаёт сессии и связь с назначенными обучаемыми."""
    op.create_table(
        "training_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("instructor_id", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            training_session_state,
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["instructor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_training_sessions_instructor_id"),
        "training_sessions",
        ["instructor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_training_sessions_state"),
        "training_sessions",
        ["state"],
        unique=False,
    )

    op.create_table(
        "training_session_trainees",
        sa.Column("training_session_id", sa.Integer(), nullable=False),
        sa.Column("trainee_id", sa.Integer(), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["training_session_id"],
            ["training_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["trainee_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("training_session_id", "trainee_id"),
    )


def downgrade() -> None:
    """Удаляет назначения, сессии и enum их состояний."""
    op.drop_table("training_session_trainees")
    op.drop_index(op.f("ix_training_sessions_state"), table_name="training_sessions")
    op.drop_index(
        op.f("ix_training_sessions_instructor_id"),
        table_name="training_sessions",
    )
    op.drop_table("training_sessions")
    training_session_state.drop(op.get_bind(), checkfirst=False)
