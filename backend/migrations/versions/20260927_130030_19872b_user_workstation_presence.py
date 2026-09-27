"""Keep trainee workstation presence independent of training sessions.

Revision ID: 20260927_130030_19872b
Revises: 20260927_120957_9880b4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260927_130030_19872b"
down_revision: str | Sequence[str] | None = "20260927_120957_9880b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("workstation_number", sa.Integer(), nullable=True))
    op.add_column(
        "users", sa.Column("workstation_last_seen_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_unique_constraint("uq_users_workstation_number", "users", ["workstation_number"])


def downgrade() -> None:
    op.drop_constraint("uq_users_workstation_number", "users", type_="unique")
    op.drop_column("users", "workstation_last_seen_at")
    op.drop_column("users", "workstation_number")
