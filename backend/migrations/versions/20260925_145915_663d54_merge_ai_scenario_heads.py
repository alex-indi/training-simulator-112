"""Merge AI provider and scenario workflow migration heads.

Revision ID: 20260925_145915_663d54
Revises: 20260925_101500_ai_secret, 20260925_132935_b873df
"""

from collections.abc import Sequence

revision: str = "20260925_145915_663d54"
down_revision: tuple[str, str] = (
    "20260925_101500_ai_secret",
    "20260925_132935_b873df",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join the two already-applied schema branches."""


def downgrade() -> None:
    """Restore the two independent branch heads."""
