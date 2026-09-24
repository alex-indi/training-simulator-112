"""Immutable generated scenario content.

Revision ID: 20260924_19
Revises: 20260924_18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_19"
down_revision: str | None = "20260924_18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scenario_instances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "scenario_template_id",
            sa.Integer(),
            sa.ForeignKey("scenario_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "training_session_id",
            sa.Integer(),
            sa.ForeignKey("training_sessions.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False),
        sa.Column("generation_seed", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="CONFIRMED"),
        sa.Column("classifier_snapshot", sa.JSON(), nullable=False),
        sa.Column("object_snapshot", sa.JSON(), nullable=False),
        sa.Column("service_snapshot", sa.JSON(), nullable=False),
        sa.Column("initial_state_snapshot", sa.JSON(), nullable=False),
        sa.Column("expected_actions_snapshot", sa.JSON(), nullable=False),
        sa.Column("assessment_criteria_snapshot", sa.JSON(), nullable=False),
        sa.Column("template_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("difficulty BETWEEN 1 AND 5", name="ck_instance_difficulty"),
        sa.CheckConstraint("status IN ('CONFIRMED', 'CANCELLED')", name="ck_instance_status"),
    )
    for field in ("scenario_template_id", "training_session_id", "created_by_user_id"):
        op.create_index(f"ix_scenario_instances_{field}", "scenario_instances", [field])
    op.create_table(
        "scenario_instance_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "scenario_instance_id",
            sa.Integer(),
            sa.ForeignKey("scenario_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("offset_seconds", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("payload_snapshot", sa.JSON(), nullable=False),
        sa.CheckConstraint("offset_seconds >= 0", name="ck_instance_event_offset"),
    )
    op.create_index(
        "ix_scenario_instance_events_scenario_instance_id",
        "scenario_instance_events",
        ["scenario_instance_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scenario_instance_events_scenario_instance_id", table_name="scenario_instance_events"
    )
    op.drop_table("scenario_instance_events")
    for field in ("created_by_user_id", "training_session_id", "scenario_template_id"):
        op.drop_index(f"ix_scenario_instances_{field}", table_name="scenario_instances")
    op.drop_table("scenario_instances")
