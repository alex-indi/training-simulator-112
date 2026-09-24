"""Добавляет стабильный ключ для демонстрационных виртуальных групп.

Revision ID: 20260924_12
Revises: 20260924_11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_12"
down_revision: str | None = "20260924_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("response_units", sa.Column("seed_code", sa.String(100), nullable=True))
    op.create_unique_constraint("uq_response_units_seed_code", "response_units", ["seed_code"])


def downgrade() -> None:
    op.drop_constraint("uq_response_units_seed_code", "response_units", type_="unique")
    op.drop_column("response_units", "seed_code")
