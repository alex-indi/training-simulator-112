"""Добавляет участие обучаемого и виртуальные назначения групп реагирования.

Revision ID: 20260922_05
Revises: 20260922_04
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260922_05"
down_revision: str | None = "20260922_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

assignment_state = postgresql.ENUM(
    "ASSIGNED",
    "ACKNOWLEDGED",
    "EN_ROUTE",
    "ARRIVED",
    "WORKING",
    "COMPLETED",
    "CANCELLED",
    name="response_assignment_state",
    create_type=False,
)


def upgrade() -> None:
    assignment_state.create(op.get_bind(), checkfirst=False)
    op.create_table(
        "training_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "training_session_id",
            sa.Integer(),
            sa.ForeignKey("training_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "trainee_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("dds_profile", sa.String(120), server_default="ДДС", nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("training_session_id", "trainee_id"),
    )
    op.create_index(
        "ix_training_runs_training_session_id", "training_runs", ["training_session_id"]
    )
    op.create_index("ix_training_runs_trainee_id", "training_runs", ["trainee_id"])
    op.execute(
        sa.text("""
        INSERT INTO training_runs (training_session_id, trainee_id, started_at)
        SELECT t.training_session_id, t.trainee_id, COALESCE(s.started_at, now())
        FROM training_session_trainees AS t
        JOIN training_sessions AS s ON s.id = t.training_session_id
        WHERE s.state = 'ACTIVE'
    """)
    )
    op.add_column("incidents", sa.Column("training_run_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_incidents_training_run_id",
        "incidents",
        "training_runs",
        ["training_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_incidents_training_run_id", "incidents", ["training_run_id"])
    op.execute(
        sa.text("""
        UPDATE incidents AS i SET training_run_id = r.id
        FROM training_runs AS r
        WHERE i.training_session_id = r.training_session_id
          AND (SELECT count(*) FROM training_runs AS all_runs
               WHERE all_runs.training_session_id = i.training_session_id) = 1
    """)
    )

    op.create_table(
        "response_units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("dds_profile", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("ix_response_units_dds_profile", "response_units", ["dds_profile"])
    op.create_table(
        "response_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "incident_id",
            sa.Integer(),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "response_unit_id",
            sa.Integer(),
            sa.ForeignKey("response_units.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "training_run_id",
            sa.Integer(),
            sa.ForeignKey("training_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("state", assignment_state, nullable=False, server_default="ASSIGNED"),
        sa.Column(
            "assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "state_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("incident_id", "response_unit_id"),
    )
    op.create_index("ix_response_assignments_incident_id", "response_assignments", ["incident_id"])
    op.create_index(
        "ix_response_assignments_response_unit_id", "response_assignments", ["response_unit_id"]
    )
    op.create_index(
        "ix_response_assignments_training_run_id", "response_assignments", ["training_run_id"]
    )
    op.create_table(
        "response_assignment_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "response_assignment_id",
            sa.Integer(),
            sa.ForeignKey("response_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_state", assignment_state, nullable=True),
        sa.Column("to_state", assignment_state, nullable=False),
        sa.Column("event_key", sa.String(120), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("response_assignment_id", "event_key"),
    )
    op.create_index(
        "ix_response_assignment_events_response_assignment_id",
        "response_assignment_events",
        ["response_assignment_id"],
    )


def downgrade() -> None:
    op.drop_table("response_assignment_events")
    op.drop_table("response_assignments")
    op.drop_table("response_units")
    op.drop_index("ix_incidents_training_run_id", table_name="incidents")
    op.drop_constraint("fk_incidents_training_run_id", "incidents", type_="foreignkey")
    op.drop_column("incidents", "training_run_id")
    op.drop_table("training_runs")
    assignment_state.drop(op.get_bind(), checkfirst=False)
