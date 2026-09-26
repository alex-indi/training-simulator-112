"""Attach prepared scenario instances to a training group.

Revision ID: 20260926_103849_b152dc
Revises: 20260926_100504_8a3d71, 20260926_101509_c72e4a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_103849_b152dc"
down_revision: tuple[str, str] = (
    "20260926_100504_8a3d71",
    "20260926_101509_c72e4a",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("scenario_instances", sa.Column("training_group_id", sa.Integer(), nullable=True))
    op.create_index("ix_scenario_instances_training_group_id", "scenario_instances", ["training_group_id"])
    op.create_foreign_key(
        "fk_scenario_instances_training_group_id",
        "scenario_instances", "training_groups", ["training_group_id"], ["id"], ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_scenario_instances_training_group_id", "scenario_instances", type_="foreignkey")
    op.drop_index("ix_scenario_instances_training_group_id", table_name="scenario_instances")
    op.drop_column("scenario_instances", "training_group_id")
