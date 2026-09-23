"""Prepared scenarios and durable delivery progress.

Revision ID: 20260923_07
Revises: 20260923_06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260923_07"
down_revision: str | None = "20260923_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

delivery_state = postgresql.ENUM("PENDING", "DELIVERED", name="delivery_state", create_type=False)


def upgrade() -> None:
    delivery_state.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "training_sessions",
        sa.Column("delivery_elapsed_seconds", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column("training_sessions", sa.Column("delivery_checked_at", sa.DateTime(timezone=True)))
    op.create_table(
        "training_scenarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "instructor_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_training_scenarios_instructor_id", "training_scenarios", ["instructor_id"])
    op.create_table(
        "scenario_queue_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "training_session_id",
            sa.Integer(),
            sa.ForeignKey("training_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "training_run_id",
            sa.Integer(),
            sa.ForeignKey("training_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "scenario_id", sa.Integer(), sa.ForeignKey("training_scenarios.id", ondelete="SET NULL")
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("delivery_position", sa.Integer()),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("delivery_state", delivery_state, nullable=False, server_default="PENDING"),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column(
            "incident_id",
            sa.Integer(),
            sa.ForeignKey("incidents.id", ondelete="SET NULL"),
            unique=True,
        ),
        sa.UniqueConstraint("training_session_id", "position"),
    )
    op.create_index(
        "ix_scenario_queue_items_training_session_id",
        "scenario_queue_items",
        ["training_session_id"],
    )
    op.create_index(
        "ix_scenario_queue_items_training_run_id", "scenario_queue_items", ["training_run_id"]
    )


def downgrade() -> None:
    op.drop_table("scenario_queue_items")
    op.drop_table("training_scenarios")
    op.drop_column("training_sessions", "delivery_checked_at")
    op.drop_column("training_sessions", "delivery_elapsed_seconds")
    delivery_state.drop(op.get_bind(), checkfirst=True)
