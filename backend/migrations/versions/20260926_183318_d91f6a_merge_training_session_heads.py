"""Merge training subgroup and session archive heads.

Revision ID: 20260926_183318_d91f6a
Revises: 20260926_181043_a341ac, 20260926_183000_a4c7e2
"""

from collections.abc import Sequence

revision: str = "20260926_183318_d91f6a"
down_revision: tuple[str, str] = (
    "20260926_181043_a341ac",
    "20260926_183000_a4c7e2",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
