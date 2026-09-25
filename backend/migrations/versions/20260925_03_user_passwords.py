"""Add password hashes for administrator-managed users.

Revision ID: 20260925_03
Revises: 20260925_02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_03"
down_revision: str | None = "20260925_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "password_hash" not in columns:
        op.add_column("users", sa.Column("password_hash", sa.String(256)))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "password_hash" in columns:
        op.drop_column("users", "password_hash")
