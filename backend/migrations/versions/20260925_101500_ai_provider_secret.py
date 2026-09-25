"""Store the AI provider secret encrypted at rest.

Revision ID: 20260925_101500_ai_secret
Revises: 20260925_074331_b9d594
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_101500_ai_secret"
down_revision: str | None = "20260925_074331_b9d594"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_provider_config", sa.Column("api_key_encrypted", sa.Text()))


def downgrade() -> None:
    op.drop_column("ai_provider_config", "api_key_encrypted")
