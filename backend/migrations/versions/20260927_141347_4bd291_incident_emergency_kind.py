"""Store the dispatcher-selected emergency kind on an incident.

Revision ID: 20260927_141347_4bd291
Revises: 20260927_140120_a7c3e1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260927_141347_4bd291"
down_revision: str | Sequence[str] | None = "20260927_140120_a7c3e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("emergency_kind", sa.String(length=2), nullable=True))
    op.create_check_constraint(
        "ck_incidents_emergency_kind",
        "incidents",
        "emergency_kind IS NULL OR emergency_kind IN ('ЧС', 'ЧП')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_incidents_emergency_kind", "incidents", type_="check")
    op.drop_column("incidents", "emergency_kind")
