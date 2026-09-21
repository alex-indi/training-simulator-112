"""Создаёт начальную точку схемы проекта.

Revision ID: 20260921_01
Revises:
Create Date: 2026-09-21
"""

from collections.abc import Sequence

revision: str = "20260921_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Фиксирует пустую базовую схему до появления доменных таблиц."""


def downgrade() -> None:
    """Откатывает пустую базовую схему."""
