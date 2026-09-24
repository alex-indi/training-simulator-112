"""Link prepared instances to canonical incidents and runtime events.

Revision ID: 20260924_20
Revises: 20260924_19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_20"
down_revision: str | None = "20260924_19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scenario_events",
        sa.Column("origin", sa.String(20), nullable=False, server_default="INSTRUCTOR"),
    )
    op.add_column("scenario_events", sa.Column("scenario_instance_event_id", sa.Integer()))
    op.create_foreign_key(
        "fk_scenario_event_instance_event",
        "scenario_events",
        "scenario_instance_events",
        ["scenario_instance_event_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_scenario_event_instance_event", "scenario_events", ["scenario_instance_event_id"]
    )
    op.add_column("scenario_queue_items", sa.Column("scenario_instance_id", sa.Integer()))
    op.create_foreign_key(
        "fk_queue_scenario_instance",
        "scenario_queue_items",
        "scenario_instances",
        ["scenario_instance_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_queue_scenario_instance", "scenario_queue_items", ["scenario_instance_id"]
    )
    op.add_column("incidents", sa.Column("scenario_instance_id", sa.Integer()))
    op.create_foreign_key(
        "fk_incident_scenario_instance",
        "incidents",
        "scenario_instances",
        ["scenario_instance_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_incident_scenario_instance", "incidents", ["scenario_instance_id"]
    )
    op.create_table(
        "scenario_runtime_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "incident_id",
            sa.Integer(),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scenario_instance_event_id",
            sa.Integer(),
            sa.ForeignKey("scenario_instance_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("offset_seconds", sa.Integer(), nullable=False),
        sa.Column("payload_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("offset_seconds >= 0", name="ck_runtime_event_offset"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RELEASED', 'CANCELLED')", name="ck_runtime_event_status"
        ),
        sa.UniqueConstraint("incident_id", "scenario_instance_event_id"),
    )
    op.create_index(
        "ix_scenario_runtime_events_incident_id", "scenario_runtime_events", ["incident_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_scenario_event_instance_event", "scenario_events", type_="unique")
    op.drop_constraint("fk_scenario_event_instance_event", "scenario_events", type_="foreignkey")
    op.drop_column("scenario_events", "scenario_instance_event_id")
    op.drop_column("scenario_events", "origin")
    op.drop_index("ix_scenario_runtime_events_incident_id", table_name="scenario_runtime_events")
    op.drop_table("scenario_runtime_events")
    op.drop_constraint("uq_incident_scenario_instance", "incidents", type_="unique")
    op.drop_constraint("fk_incident_scenario_instance", "incidents", type_="foreignkey")
    op.drop_column("incidents", "scenario_instance_id")
    op.drop_constraint("uq_queue_scenario_instance", "scenario_queue_items", type_="unique")
    op.drop_constraint("fk_queue_scenario_instance", "scenario_queue_items", type_="foreignkey")
    op.drop_column("scenario_queue_items", "scenario_instance_id")
