"""Add archive flag to training sessions.

Revision ID: 20260926_183000_a4c7e2
Revises: 20260926_103849_b152dc
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_183000_a4c7e2"
down_revision: str | None = "20260926_103849_b152dc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "training_sessions",
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("training_sessions", "is_archived")
