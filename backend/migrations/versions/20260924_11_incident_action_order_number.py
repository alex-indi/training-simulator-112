"""Store manually entered order numbers on incident status actions.

Revision ID: 20260924_11
Revises: 20260924_10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_11"
down_revision: str | None = "20260924_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("incident_actions", sa.Column("order_number", sa.String(80)))


def downgrade() -> None:
    op.drop_column("incident_actions", "order_number")
