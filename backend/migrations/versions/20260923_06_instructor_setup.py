"""Persist instructor setup, workstations, groups, and reusable templates.

Revision ID: 20260923_06
Revises: 20260922_05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260923_06"
down_revision: str | None = "20260922_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

training_mode = postgresql.ENUM(
    "FLOW", "FIXED_SET", "MANUAL", name="training_mode", create_type=False
)
delivery_order = postgresql.ENUM("SEQUENTIAL", "RANDOM", name="delivery_order", create_type=False)
queue_mode = postgresql.ENUM(
    "INDIVIDUAL_QUEUE", "SHARED_QUEUE", name="queue_mode", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    training_mode.create(bind, checkfirst=True)
    delivery_order.create(bind, checkfirst=True)
    queue_mode.create(bind, checkfirst=True)
    op.add_column(
        "training_sessions", sa.Column("topic", sa.String(200), nullable=False, server_default="")
    )
    op.add_column(
        "training_sessions",
        sa.Column("mode", training_mode, nullable=False, server_default="MANUAL"),
    )
    op.add_column("training_sessions", sa.Column("duration_minutes", sa.Integer(), nullable=True))
    op.add_column(
        "training_sessions", sa.Column("delivery_interval_seconds", sa.Integer(), nullable=True)
    )
    op.add_column(
        "training_sessions",
        sa.Column("delivery_order", delivery_order, nullable=False, server_default="SEQUENTIAL"),
    )
    op.add_column(
        "training_sessions",
        sa.Column("workstation_count", sa.Integer(), nullable=False, server_default="30"),
    )
    op.create_table(
        "training_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "training_session_id",
            sa.Integer(),
            sa.ForeignKey("training_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("dds_profile", sa.String(120), nullable=True),
        sa.Column("difficulty", sa.String(40), nullable=True),
        sa.Column("queue_mode", queue_mode, nullable=False, server_default="INDIVIDUAL_QUEUE"),
        sa.UniqueConstraint("training_session_id", "name"),
    )
    op.create_index(
        "ix_training_groups_training_session_id", "training_groups", ["training_session_id"]
    )
    op.add_column("training_runs", sa.Column("workstation_number", sa.Integer(), nullable=True))
    op.add_column("training_runs", sa.Column("difficulty", sa.String(40), nullable=True))
    op.add_column(
        "training_runs",
        sa.Column("queue_mode", queue_mode, nullable=False, server_default="INDIVIDUAL_QUEUE"),
    )
    op.add_column(
        "training_runs",
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("training_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "training_runs", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_unique_constraint(
        "uq_training_runs_session_workstation",
        "training_runs",
        ["training_session_id", "workstation_number"],
    )
    op.create_table(
        "training_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "instructor_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_training_templates_instructor_id", "training_templates", ["instructor_id"])


def downgrade() -> None:
    op.drop_table("training_templates")
    op.drop_constraint("uq_training_runs_session_workstation", "training_runs", type_="unique")
    op.drop_column("training_runs", "last_seen_at")
    op.drop_column("training_runs", "group_id")
    op.drop_column("training_runs", "queue_mode")
    op.drop_column("training_runs", "difficulty")
    op.drop_column("training_runs", "workstation_number")
    op.drop_table("training_groups")
    op.drop_column("training_sessions", "workstation_count")
    op.drop_column("training_sessions", "delivery_order")
    op.drop_column("training_sessions", "delivery_interval_seconds")
    op.drop_column("training_sessions", "duration_minutes")
    op.drop_column("training_sessions", "mode")
    op.drop_column("training_sessions", "topic")
    queue_mode.drop(op.get_bind(), checkfirst=True)
    delivery_order.drop(op.get_bind(), checkfirst=True)
    training_mode.drop(op.get_bind(), checkfirst=True)
