"""Pause, intervention and audit state for active training sessions.

Revision ID: 20260924_10
Revises: 20260923_09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_10"
down_revision: str | None = "20260923_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("training_sessions", sa.Column("paused_at", sa.DateTime(timezone=True)))
    op.add_column("training_sessions", sa.Column("paused_seconds", sa.Float(), nullable=False, server_default="0"))
    op.add_column("training_sessions", sa.Column("finish_mode", sa.String(20)))
    op.add_column("training_sessions", sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.add_column("training_runs", sa.Column("paused_at", sa.DateTime(timezone=True)))
    op.add_column("training_runs", sa.Column("paused_seconds", sa.Float(), nullable=False, server_default="0"))
    op.create_table("instructor_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("training_session_id", sa.Integer(), sa.ForeignKey("training_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instructor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_instructor_actions_training_session_id", "instructor_actions", ["training_session_id"])
    op.create_table("session_pauses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("training_session_id", sa.Integer(), sa.ForeignKey("training_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instructor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_seconds", sa.Float()),
    )
    op.create_index("ix_session_pauses_training_session_id", "session_pauses", ["training_session_id"])
    op.create_table("run_pauses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("training_run_id", sa.Integer(), sa.ForeignKey("training_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instructor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_seconds", sa.Float()),
    )
    op.create_index("ix_run_pauses_training_run_id", "run_pauses", ["training_run_id"])
    op.create_table("instructor_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("training_run_id", sa.Integer(), sa.ForeignKey("training_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instructor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_instructor_notes_training_run_id", "instructor_notes", ["training_run_id"])
    op.create_table("scenario_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instructor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_scenario_events_incident_id", "scenario_events", ["incident_id"])


def downgrade() -> None:
    for table, index in (("scenario_events", "ix_scenario_events_incident_id"), ("instructor_notes", "ix_instructor_notes_training_run_id"), ("run_pauses", "ix_run_pauses_training_run_id"), ("session_pauses", "ix_session_pauses_training_session_id"), ("instructor_actions", "ix_instructor_actions_training_session_id")):
        op.drop_index(index, table_name=table)
        op.drop_table(table)
    for column in ("paused_at", "paused_seconds"):
        op.drop_column("training_runs", column)
    for column in ("paused_at", "paused_seconds", "finish_mode", "completed_at"):
        op.drop_column("training_sessions", column)
