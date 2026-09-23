"""Group-addressed incidents and atomic ownership.

Revision ID: 20260923_08
Revises: 20260923_07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_08"
down_revision: str | None = "20260923_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("scenario_queue_items", "training_run_id", nullable=True)
    op.add_column(
        "scenario_queue_items",
        sa.Column(
            "training_group_id",
            sa.Integer(),
            sa.ForeignKey("training_groups.id", ondelete="RESTRICT"),
        ),
    )
    op.create_index(
        "ix_scenario_queue_items_training_group_id", "scenario_queue_items", ["training_group_id"]
    )
    op.create_check_constraint(
        "ck_queue_target",
        "scenario_queue_items",
        "(training_run_id IS NULL) <> (training_group_id IS NULL)",
    )
    op.add_column(
        "incidents",
        sa.Column(
            "training_group_id",
            sa.Integer(),
            sa.ForeignKey("training_groups.id", ondelete="RESTRICT"),
        ),
    )
    op.add_column(
        "incidents",
        sa.Column(
            "claimed_by_training_run_id",
            sa.Integer(),
            sa.ForeignKey("training_runs.id", ondelete="RESTRICT"),
        ),
    )
    op.add_column("incidents", sa.Column("claimed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_incidents_training_group_id", "incidents", ["training_group_id"])
    op.create_index(
        "ix_incidents_claimed_by_training_run_id", "incidents", ["claimed_by_training_run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_incidents_claimed_by_training_run_id", "incidents")
    op.drop_index("ix_incidents_training_group_id", "incidents")
    op.drop_column("incidents", "claimed_at")
    op.drop_column("incidents", "claimed_by_training_run_id")
    op.drop_column("incidents", "training_group_id")
    op.drop_constraint("ck_queue_target", "scenario_queue_items", type_="check")
    op.drop_index("ix_scenario_queue_items_training_group_id", "scenario_queue_items")
    op.drop_column("scenario_queue_items", "training_group_id")
    op.alter_column("scenario_queue_items", "training_run_id", nullable=False)
