"""Store manually entered order numbers on incident status actions.

Revision ID: 20260924_16
Revises: 20260924_15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_16"
down_revision: str | None = "20260924_15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("incident_actions")
    }
    if "order_number" not in columns:
        op.add_column("incident_actions", sa.Column("order_number", sa.String(80)))


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("incident_actions")
    }
    if "order_number" in columns:
        op.drop_column("incident_actions", "order_number")
