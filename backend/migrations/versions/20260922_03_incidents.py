"""Добавляет базовые карточки происшествий.

Revision ID: 20260922_03
Revises: 20260922_02
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260922_03"
down_revision: str | None = "20260922_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

incident_lifecycle_state = sa.Enum(
    "CREATED",
    "DELIVERED",
    "OPENED",
    "FINISHED",
    name="incident_lifecycle_state",
)


def upgrade() -> None:
    """Создаёт карточки со snapshot сценария и серверными временными метками."""
    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("training_session_id", sa.Integer(), nullable=False),
        sa.Column("incident_number", sa.String(length=64), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("applicant_name", sa.String(length=200), nullable=True),
        sa.Column("applicant_phone", sa.String(length=50), nullable=True),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("incident_type", sa.String(length=200), nullable=False),
        sa.Column("source_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "lifecycle_state",
            incident_lifecycle_state,
            server_default="CREATED",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("primary_status_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["training_session_id"],
            ["training_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_incidents_training_session_id"),
        "incidents",
        ["training_session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_incidents_incident_number"),
        "incidents",
        ["incident_number"],
        unique=False,
    )
    op.create_index(
        op.f("ix_incidents_lifecycle_state"),
        "incidents",
        ["lifecycle_state"],
        unique=False,
    )


def downgrade() -> None:
    """Удаляет карточки и enum их технического lifecycle."""
    op.drop_index(op.f("ix_incidents_lifecycle_state"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_incident_number"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_training_session_id"), table_name="incidents")
    op.drop_table("incidents")
    incident_lifecycle_state.drop(op.get_bind(), checkfirst=False)
