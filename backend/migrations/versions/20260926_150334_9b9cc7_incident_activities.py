"""Persist virtual service reactions and training brigade stages.

Revision ID: 20260926_150334_9b9cc7
Revises: 20260926_143353_2d0538
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_150334_9b9cc7"
down_revision: str | None = "20260926_143353_2d0538"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incident_activities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "incident_id",
            sa.Integer(),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_key", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("dispatch_services.id"), nullable=True),
        sa.Column("service_name", sa.String(200), nullable=False),
        sa.Column("stage", sa.String(32), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("incident_id", "event_key"),
    )
    op.create_index("ix_incident_activities_incident_id", "incident_activities", ["incident_id"])


def downgrade() -> None:
    op.drop_index("ix_incident_activities_incident_id", table_name="incident_activities")
    op.drop_table("incident_activities")
