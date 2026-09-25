"""Store optional response state transitions in prepared scenario events.

Revision ID: 20260925_132935_b873df
Revises: 20260925_123708_8b8bb4
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_132935_b873df"
down_revision: str | None = "20260925_123708_8b8bb4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scenario_event_templates", sa.Column("target_response_state", sa.String(20)))


def downgrade() -> None:
    op.drop_column("scenario_event_templates", "target_response_state")
