"""Persist AI assessment summary independently of instructor decision.

Revision ID: 20260926_152539_a73f0c
Revises: 20260926_150334_9b9cc7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_152539_a73f0c"
down_revision: str | None = "20260926_150334_9b9cc7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assessment_results", sa.Column("ai_summary", sa.Text(), nullable=True))
    op.add_column(
        "assessment_results",
        sa.Column("ai_summary_provider", sa.String(40), nullable=True),
    )
    op.add_column(
        "assessment_results",
        sa.Column("ai_summary_generated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assessment_results", "ai_summary_generated_at")
    op.drop_column("assessment_results", "ai_summary_provider")
    op.drop_column("assessment_results", "ai_summary")
