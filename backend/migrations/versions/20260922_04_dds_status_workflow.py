"""Добавляет workflow статусов ДДС и историю действий.

Revision ID: 20260922_04
Revises: 20260922_03
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260922_04"
down_revision: str | None = "20260922_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

dds_response_status = postgresql.ENUM(
    "AWAITING_DECISION",
    "ACCEPTED",
    "REJECTED",
    "RESPONSE_STARTED",
    "ARRIVED",
    "WORKING",
    "COMPLETED",
    "WORK_REFUSED",
    name="dds_response_status",
    create_type=False,
)

incident_action_type = postgresql.ENUM(
    "ACCEPT",
    "REJECT",
    "START_RESPONSE",
    "MARK_ARRIVAL",
    "START_WORK",
    "COMPLETE_WORK",
    "REFUSE_WORK",
    name="incident_action_type",
    create_type=False,
)


def upgrade() -> None:
    """Добавляет канонический статус ДДС и аудит всех переходов."""
    dds_response_status.create(op.get_bind(), checkfirst=False)
    incident_action_type.create(op.get_bind(), checkfirst=False)

    op.add_column(
        "incidents",
        sa.Column(
            "dds_status",
            dds_response_status,
            server_default="AWAITING_DECISION",
            nullable=False,
        ),
    )
    op.create_index(
        op.f("ix_incidents_dds_status"),
        "incidents",
        ["dds_status"],
        unique=False,
    )

    op.create_table(
        "incident_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_display_name", sa.String(length=120), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("action", incident_action_type, nullable=True),
        sa.Column("from_status", dds_response_status, nullable=True),
        sa.Column("to_status", dds_response_status, nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_incident_actions_actor_user_id"),
        "incident_actions",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_incident_actions_incident_id"),
        "incident_actions",
        ["incident_id"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            INSERT INTO incident_actions (
                incident_id,
                actor_display_name,
                is_system,
                status,
                created_at
            )
            SELECT
                id,
                'Virtual112',
                true,
                'SERVICE_ADDED',
                COALESCE(delivered_at, created_at)
            FROM incidents
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO incident_actions (
                incident_id,
                actor_display_name,
                is_system,
                status,
                created_at
            )
            SELECT
                id,
                'Система-112',
                true,
                'SERVICE_RECEIVED',
                opened_at
            FROM incidents
            WHERE opened_at IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    """Удаляет историю действий и статус ДДС."""
    op.drop_index(op.f("ix_incident_actions_incident_id"), table_name="incident_actions")
    op.drop_index(
        op.f("ix_incident_actions_actor_user_id"),
        table_name="incident_actions",
    )
    op.drop_table("incident_actions")
    op.drop_index(op.f("ix_incidents_dds_status"), table_name="incidents")
    op.drop_column("incidents", "dds_status")
    incident_action_type.drop(op.get_bind(), checkfirst=False)
    dds_response_status.drop(op.get_bind(), checkfirst=False)
